"""客户留存规则引擎。

规则决定客户今天是否允许联系；Agent 只在规则通过后生成建议。新工作台使用
RetentionTask / RetentionContact / RetentionSuppression 作为权威数据，ReminderLog
仅保留给旧接口和历史数据兼容。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Optional
import uuid

from loguru import logger
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.database.finance import FinanceService
from backend.database.models import (
    Appointment,
    AppointmentStatus,
    NotificationKind,
    ReminderLog,
    ReminderStatus,
    ReminderType,
    RetentionContact,
    RetentionContactStatus,
    RetentionSuppression,
    RetentionTask,
    RetentionTaskStatus,
    Stylist,
    User,
    UserRole,
    WalletAccount,
)


# ===== 可调规则参数 =====

SERVICE_CYCLE_DAYS = {
    "剪": 28, "剪发": 28, "洗剪吹": 28,
    "烫": 56, "烫发": 56,
    "染": 49, "染发": 49,
    "护理": 30, "头皮": 30,
    "造型": 35,
}
DEFAULT_CYCLE_DAYS = 35
REPURCHASE_BUFFER = 1.2
BIRTHDAY_LOOKAHEAD_DAYS = 5
CHURN_THRESHOLD_DAYS = 150

BIRTHDAY_COOLDOWN_DAYS = 14
REPURCHASE_COOLDOWN_DAYS = 30
CHURN_COOLDOWN_DAYS = 50
BALANCE_CHURN_COOLDOWN_DAYS = 30
LEGACY_CONTACT_COOLDOWN_DAYS = 14

PRIORITY = {
    ReminderType.BIRTHDAY: 40,
    ReminderType.CHURN_RISK: 30,
    ReminderType.REPURCHASE: 20,
}

ACTIVE_TASK_STATUSES = (
    RetentionTaskStatus.PENDING_REVIEW,
    RetentionTaskStatus.SENDING,
    RetentionTaskStatus.SEND_FAILED,
    RetentionTaskStatus.MANUAL_FOLLOWUP,
)

# 联系记录只展示真实触达或已经进入人工处理链路的任务。
# 纯扫描生成的 pending_review / ignored 任务不属于联系记录。
CONTACT_RECORD_TASK_STATUSES = (
    RetentionTaskStatus.SENDING,
    RetentionTaskStatus.SENT,
    RetentionTaskStatus.SEND_FAILED,
    RetentionTaskStatus.REPLIED,
    RetentionTaskStatus.MANUAL_FOLLOWUP,
    RetentionTaskStatus.COOLING,
    RetentionTaskStatus.CLOSED,
)


class RetentionService:
    """计算客户留存资格、生成每日唯一任务，并保留旧提醒接口的兼容方法。"""

    # ---------- 基础计算 ----------

    @staticmethod
    def _past_visits(db: Session, customer_id: uuid.UUID) -> list[Appointment]:
        """返回已发生且未取消的到店记录，按时间升序。"""
        now = datetime.now()
        return db.query(Appointment).filter(
            Appointment.customer_id == customer_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.appointment_datetime <= now,
        ).order_by(Appointment.appointment_datetime.asc()).all()

    @staticmethod
    def _service_cycle(service: Optional[str]) -> int:
        if service:
            for keyword, days in SERVICE_CYCLE_DAYS.items():
                if keyword in service:
                    return days
        return DEFAULT_CYCLE_DAYS

    @classmethod
    def compute_cycle_days(cls, db: Session, customer: User) -> tuple[int, str]:
        """优先用客户历史平均间隔，历史不足时回退到最近服务默认周期。"""
        visits = cls._past_visits(db, customer.id)
        if len(visits) >= 2:
            gaps = [
                (visits[index].appointment_datetime - visits[index - 1].appointment_datetime).days
                for index in range(1, len(visits))
            ]
            gaps = [gap for gap in gaps if gap > 0]
            if gaps:
                average = round(sum(gaps) / len(gaps))
                return max(average, 7), f"个人节奏约 {average} 天（{len(visits)} 次到店）"

        last_service = visits[-1].service if visits else None
        cycle = cls._service_cycle(last_service)
        label = f"按 {last_service} " if last_service else "按"
        return cycle, f"{label}默认周期 {cycle} 天"

    @staticmethod
    def _preferred_stylist_id(db: Session, customer_id: uuid.UUID) -> Optional[uuid.UUID]:
        appointments = db.query(Appointment).filter(
            Appointment.customer_id == customer_id,
            Appointment.status != AppointmentStatus.CANCELLED,
        ).order_by(Appointment.appointment_datetime.desc()).all()
        if not appointments:
            return None
        counts = Counter(appointment.stylist_id for appointment in appointments)
        return max(
            counts,
            key=lambda stylist_id: (counts[stylist_id], -appointments.index(
                next(item for item in appointments if item.stylist_id == stylist_id)
            )),
        )

    @staticmethod
    def _days_until_birthday(birthday: str, now: datetime) -> Optional[int]:
        """birthday 使用 MM-DD；非闰年的 2 月 29 日按 2 月 28 日处理。"""
        try:
            month, day = (int(value) for value in birthday.split("-"))
            next_birthday = date(now.year, month, day)
        except ValueError:
            if birthday == "02-29":
                next_birthday = date(now.year, 2, 28)
            else:
                return None
        except (AttributeError, TypeError):
            return None

        if next_birthday < now.date():
            try:
                next_birthday = date(now.year + 1, month, day)
            except ValueError:
                next_birthday = date(now.year + 1, 2, 28)
        return (next_birthday - now.date()).days

    # ---------- 统一拦截 ----------

    @staticmethod
    def _active_suppression(
        db: Session, customer_id: uuid.UUID, now: datetime,
    ) -> Optional[RetentionSuppression]:
        return db.query(RetentionSuppression).filter(
            RetentionSuppression.customer_id == customer_id,
            RetentionSuppression.released_at.is_(None),
            RetentionSuppression.starts_at <= now,
            or_(
                RetentionSuppression.ends_at.is_(None),
                RetentionSuppression.ends_at > now,
            ),
        ).order_by(RetentionSuppression.created_at.desc()).first()

    @classmethod
    def _cooldown_days_for_task(cls, task: RetentionTask) -> int:
        if task.primary_type == ReminderType.BIRTHDAY:
            return BIRTHDAY_COOLDOWN_DAYS
        if task.primary_type == ReminderType.REPURCHASE:
            return REPURCHASE_COOLDOWN_DAYS
        if "balance_customer" in (task.strategy_tags or []):
            return BALANCE_CHURN_COOLDOWN_DAYS
        return CHURN_COOLDOWN_DAYS

    @classmethod
    def _is_in_cooldown(cls, db: Session, customer_id: uuid.UUID, now: datetime) -> bool:
        latest_contact = db.query(RetentionContact).filter(
            RetentionContact.customer_id == customer_id,
            RetentionContact.status == RetentionContactStatus.SENT,
            RetentionContact.sent_at.is_not(None),
        ).order_by(RetentionContact.sent_at.desc()).first()
        if latest_contact:
            next_allowed = latest_contact.sent_at + timedelta(
                days=cls._cooldown_days_for_task(latest_contact.task)
            )
            return next_allowed > now

        # 新规则上线前的已联系记录也至少保留原来的 14 天保护窗口。
        legacy_contact = db.query(ReminderLog).filter(
            ReminderLog.customer_id == customer_id,
            ReminderLog.status == ReminderStatus.CONTACTED,
            ReminderLog.contacted_at.is_not(None),
        ).order_by(ReminderLog.contacted_at.desc()).first()
        return bool(
            legacy_contact
            and legacy_contact.contacted_at + timedelta(days=LEGACY_CONTACT_COOLDOWN_DAYS) > now
        )

    @staticmethod
    def _has_active_task(db: Session, customer_id: uuid.UUID) -> bool:
        return db.query(RetentionTask.id).filter(
            RetentionTask.customer_id == customer_id,
            RetentionTask.status.in_(ACTIVE_TASK_STATUSES),
        ).first() is not None

    @classmethod
    def is_contact_eligible(cls, db: Session, customer_id: uuid.UUID, now: Optional[datetime] = None) -> bool:
        """退订/忽略/人工跟进优先于冷却期，全部通过后客户才有资格进入候选。"""
        now = now or datetime.now()
        if cls._active_suppression(db, customer_id, now):
            return False
        return not cls._is_in_cooldown(db, customer_id, now)

    # ---------- 候选生成与合并 ----------

    @staticmethod
    def _msg_birthday(name: str, days_until: int) -> str:
        when = "今天" if days_until == 0 else f"还有 {days_until} 天"
        return f"{name}您好，您生日{when}就到啦，提前祝您生日快乐！近期想打理头发的话，我可以帮您安排合适的时间。"

    @staticmethod
    def _msg_repurchase(name: str, last_service: Optional[str], days_since: int) -> str:
        service = f"上次做的{last_service}" if last_service else "上次的造型"
        return f"{name}您好，距上次到店已经 {days_since} 天，{service}差不多可以打理一下了。近期有空的话，我可以帮您安排时间。"

    @staticmethod
    def _msg_churn(name: str, days_since: int, balance_cents: int) -> str:
        if balance_cents > 0:
            return (
                f"{name}您好，距上次到店已经 {days_since} 天。"
                f"您账户当前还有余额 ¥{balance_cents / 100:.2f}，近期需要护理或造型时，我可以帮您安排。"
            )
        return f"{name}您好，距上次到店已经 {days_since} 天。近期想换个造型或做护理时，我可以帮您看看合适的时间。"

    @classmethod
    def _birthday_candidate(cls, customer: User, now: datetime) -> Optional[dict[str, Any]]:
        if not customer.birthday:
            return None
        days_until = cls._days_until_birthday(customer.birthday, now)
        if days_until is None or not 0 <= days_until <= BIRTHDAY_LOOKAHEAD_DAYS:
            return None
        reason = "今天生日" if days_until == 0 else f"{days_until} 天后生日"
        return {
            "type": ReminderType.BIRTHDAY,
            "reason": reason,
            "message": cls._msg_birthday(customer.name, days_until),
            "tags": [],
            "evidence": {
                "birthday": customer.birthday,
                "days_until_birthday": days_until,
                "lookahead_days": BIRTHDAY_LOOKAHEAD_DAYS,
            },
        }

    @classmethod
    def _lifecycle_candidate(
        cls, db: Session, customer: User, now: datetime, balance_cents: int,
    ) -> Optional[dict[str, Any]]:
        if not customer.last_visit:
            return None
        days_since = (now - customer.last_visit).days
        cycle_days, cycle_basis = cls.compute_cycle_days(db, customer)
        visits = cls._past_visits(db, customer.id)
        last_service = visits[-1].service if visits else None

        if days_since >= CHURN_THRESHOLD_DAYS:
            tags = ["balance_customer"] if balance_cents > 0 else []
            return {
                "type": ReminderType.CHURN_RISK,
                "reason": f"距上次到店 {days_since} 天，已达到 {CHURN_THRESHOLD_DAYS} 天流失风险线",
                "message": cls._msg_churn(customer.name, days_since, balance_cents),
                "tags": tags,
                "evidence": {
                    "days_since_last_visit": days_since,
                    "churn_threshold_days": CHURN_THRESHOLD_DAYS,
                    "cycle_days": cycle_days,
                    "cycle_basis": cycle_basis,
                    "balance_cents": balance_cents,
                    "balance": round(balance_cents / 100, 2),
                },
            }

        threshold_days = round(cycle_days * REPURCHASE_BUFFER)
        if days_since >= threshold_days:
            return {
                "type": ReminderType.REPURCHASE,
                "reason": f"距上次到店 {days_since} 天，{cycle_basis}，已达到复购提醒阈值",
                "message": cls._msg_repurchase(customer.name, last_service, days_since),
                "tags": [],
                "evidence": {
                    "days_since_last_visit": days_since,
                    "cycle_days": cycle_days,
                    "threshold_days": threshold_days,
                    "cycle_basis": cycle_basis,
                    "last_service": last_service,
                },
            }
        return None

    @classmethod
    def evaluate_customer(
        cls,
        db: Session,
        customer: User,
        now: Optional[datetime] = None,
        balance_cents: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """返回一条合并后的客户候选；不符合资格或没有命中规则时返回 None。"""
        now = now or datetime.now()
        if not cls.is_contact_eligible(db, customer.id, now):
            return None

        if balance_cents is None:
            wallet = db.query(WalletAccount).filter(WalletAccount.user_id == customer.id).first()
            balance_cents = wallet.balance_cents if wallet else 0

        candidates = [
            candidate for candidate in (
                cls._birthday_candidate(customer, now),
                cls._lifecycle_candidate(db, customer, now, balance_cents),
            ) if candidate
        ]
        if not candidates:
            return None

        # 生日窗口短，优先作为主任务；复购与流失在生命周期规则中已天然互斥。
        primary = next(
            (candidate for candidate in candidates if candidate["type"] == ReminderType.BIRTHDAY),
            candidates[0],
        )
        tags = sorted({tag for candidate in candidates for tag in candidate["tags"]})
        trigger_reasons = [
            {
                "type": candidate["type"].value,
                "reason": candidate["reason"],
                "evidence": candidate["evidence"],
            }
            for candidate in candidates
        ]
        priority = PRIORITY[primary["type"]]
        if primary["type"] == ReminderType.CHURN_RISK and "balance_customer" in tags:
            priority += 5
        return {
            "type": primary["type"],
            "reason": primary["reason"],
            "message": primary["message"],
            "tags": tags,
            "trigger_reasons": trigger_reasons,
            "evidence": {"primary": primary["evidence"], "all": trigger_reasons},
            "priority": priority,
        }

    # ---------- 每日扫描 / 查询 ----------

    @classmethod
    def scan_and_generate(cls, db: Session, now: Optional[datetime] = None) -> dict[str, int]:
        """幂等扫描：同客户同业务日及已有活跃任务均不会重复创建。"""
        now = now or datetime.now()
        business_date = now.date()
        logger.info("开始执行留存工作台扫描")
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
        wallet_balances = {
            wallet.user_id: wallet.balance_cents
            for wallet in db.query(WalletAccount).all()
        }
        created = {"repurchase": 0, "birthday": 0, "churn_risk": 0}

        for customer in customers:
            existing_today = db.query(RetentionTask.id).filter(
                RetentionTask.customer_id == customer.id,
                RetentionTask.business_date == business_date,
            ).first()
            if existing_today or cls._has_active_task(db, customer.id):
                continue

            candidate = cls.evaluate_customer(
                db,
                customer,
                now=now,
                balance_cents=wallet_balances.get(customer.id, 0),
            )
            if not candidate:
                continue

            task = RetentionTask(
                customer_id=customer.id,
                stylist_id=cls._preferred_stylist_id(db, customer.id),
                business_date=business_date,
                primary_type=candidate["type"],
                strategy_tags=candidate["tags"],
                trigger_reasons=candidate["trigger_reasons"],
                evidence=candidate["evidence"],
                priority=candidate["priority"],
                status=RetentionTaskStatus.PENDING_REVIEW,
                suggested_message=candidate["message"],
                suggestion_reason=candidate["reason"],
            )
            db.add(task)
            created[candidate["type"].value] += 1

        db.commit()
        created["total"] = sum(created.values())
        logger.info(f"留存工作台扫描完成：{created}")
        return created

    @staticmethod
    def list_tasks(
        db: Session,
        status: Optional[RetentionTaskStatus] = None,
        stylist_id: Optional[str] = None,
        today_only: bool = False,
        records_only: bool = False,
    ) -> list[RetentionTask]:
        query = db.query(RetentionTask)
        if status:
            query = query.filter(RetentionTask.status == status)
        if today_only:
            query = query.filter(RetentionTask.status.in_(
                (RetentionTaskStatus.PENDING_REVIEW, RetentionTaskStatus.SEND_FAILED)
            ))
        if records_only:
            query = query.filter(or_(
                RetentionTask.status.in_(CONTACT_RECORD_TASK_STATUSES),
                RetentionTask.contacts.any(),
            ))
        if stylist_id:
            query = query.filter(RetentionTask.stylist_id == uuid.UUID(stylist_id))
        return query.order_by(RetentionTask.priority.desc(), RetentionTask.created_at.desc()).all()

    # ---------- 旧接口兼容：待新工作台 API 切换后删除 ----------

    @staticmethod
    def list_reminders(
        db: Session, stylist_id: Optional[str] = None, status: str = "pending",
    ) -> list[ReminderLog]:
        query = db.query(ReminderLog)
        if status:
            query = query.filter(ReminderLog.status == ReminderStatus[status.upper()])
        if stylist_id:
            query = query.filter(ReminderLog.stylist_id == uuid.UUID(stylist_id))
        return query.order_by(ReminderLog.priority.desc(), ReminderLog.created_at.desc()).all()

    @staticmethod
    def mark_contacted(db: Session, reminder_id: str, actor: Optional[User] = None) -> bool:
        reminder = db.query(ReminderLog).filter(ReminderLog.id == uuid.UUID(reminder_id)).first()
        if not reminder:
            return False
        if reminder.status == ReminderStatus.CONTACTED:
            return True
        reminder.status = ReminderStatus.CONTACTED
        reminder.contacted_at = datetime.now()
        if reminder.customer and reminder.suggested_message:
            FinanceService.create_notification(
                db,
                reminder.customer_id,
                NotificationKind.MARKETING,
                "留存提醒",
                reminder.suggested_message,
            )
        if actor:
            FinanceService.create_audit(
                db,
                actor.id,
                "retention.reminder_contacted",
                "reminder_log",
                str(reminder.id),
                {"customer_id": str(reminder.customer_id), "reminder_type": reminder.reminder_type.value},
            )
        db.commit()
        return True

    @staticmethod
    def dismiss(db: Session, reminder_id: str, actor: Optional[User] = None) -> bool:
        reminder = db.query(ReminderLog).filter(ReminderLog.id == uuid.UUID(reminder_id)).first()
        if not reminder:
            return False
        reminder.status = ReminderStatus.DISMISSED
        if actor:
            FinanceService.create_audit(
                db,
                actor.id,
                "retention.reminder_dismissed",
                "reminder_log",
                str(reminder.id),
                {"customer_id": str(reminder.customer_id), "reminder_type": reminder.reminder_type.value},
            )
        db.commit()
        return True
