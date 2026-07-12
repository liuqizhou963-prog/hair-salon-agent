"""客户维护 / 留存引擎 — 纯规则，不依赖 LLM

每日扫描全店客户，按「每个客户自己的历史到店节奏」判断谁该被联系，
生成待办写入 ReminderLog，由发型师在工作台用自己微信联系客户。

三条规则：
  1. 复购提醒   REPURCHASE   —— 距上次到店 > 个人节奏（含缓冲），该回来了
  2. 生日提醒   BIRTHDAY     —— 生日前若干天，发型师好提前约
  3. 流失预警   CHURN_RISK   —— 距上次到店 > 个人节奏 × 流失倍数，高优先级
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
from collections import Counter
from loguru import logger
import uuid

from backend.database.models import (
    User, Stylist, Appointment, Member, ReminderLog,
    UserRole, AppointmentStatus, ReminderType, ReminderStatus, NotificationKind,
)
from backend.database.finance import FinanceService

# ===== 可调参数 =====

# 各服务的默认复购周期（天）——新客户没有历史时的兜底
SERVICE_CYCLE_DAYS = {
    "剪": 28, "剪发": 28, "洗剪吹": 28,
    "烫": 56, "烫发": 56,
    "染": 49, "染发": 49,
    "护理": 30, "头皮": 30,
    "造型": 35,
}
DEFAULT_CYCLE_DAYS = 35        # 完全无信息时的全局兜底
REPURCHASE_BUFFER = 1.2        # 到「个人节奏 × 缓冲」才提醒，避免太吵
CHURN_MULTIPLIER = 2.5         # 超过「个人节奏 × 倍数」判为流失高风险
BIRTHDAY_LOOKAHEAD_DAYS = 5    # 生日前几天提醒
REMINDER_COOLDOWN_DAYS = 14    # 同类提醒的冷却期，防止反复打扰
MIN_VISITS_FOR_PERSONAL = 2    # 至少几次到店才用个人节奏，否则用服务默认

# 优先级：数字越大越靠前
PRIORITY = {
    ReminderType.CHURN_RISK: 30,
    ReminderType.BIRTHDAY: 20,
    ReminderType.REPURCHASE: 10,
}

class RetentionService:
    """留存引擎：计算节奏、跑规则、生成待办"""

    # ---------- 基础计算 ----------

    @staticmethod
    def _past_visits(db: Session, customer_id: uuid.UUID) -> List[Appointment]:
        """某客户已发生的到店（已完成，或时间已过且未取消），按时间升序"""
        now = datetime.now()
        appts = db.query(Appointment).filter(
            Appointment.customer_id == customer_id,
            Appointment.status != AppointmentStatus.CANCELLED,
            Appointment.appointment_datetime <= now,
        ).order_by(Appointment.appointment_datetime.asc()).all()
        return appts

    @staticmethod
    def _service_cycle(service: Optional[str]) -> int:
        """根据服务名匹配默认复购周期"""
        if service:
            for keyword, days in SERVICE_CYCLE_DAYS.items():
                if keyword in service:
                    return days
        return DEFAULT_CYCLE_DAYS

    @classmethod
    def compute_cycle_days(cls, db: Session, customer: User) -> tuple[int, str]:
        """算出这个客户的复购节奏（天），并返回依据说明。

        有 >=2 次到店 → 用历史平均间隔；否则回退到最近一次服务的默认周期。
        """
        visits = cls._past_visits(db, customer.id)

        if len(visits) >= MIN_VISITS_FOR_PERSONAL:
            gaps = [
                (visits[i].appointment_datetime - visits[i - 1].appointment_datetime).days
                for i in range(1, len(visits))
            ]
            gaps = [g for g in gaps if g > 0]
            if gaps:
                avg = round(sum(gaps) / len(gaps))
                return max(avg, 7), f"个人节奏约 {avg} 天（{len(visits)} 次到店）"

        last_service = visits[-1].service if visits else None
        cycle = cls._service_cycle(last_service)
        label = f"{last_service} " if last_service else ""
        return cycle, f"按 {label}默认周期 {cycle} 天"

    @staticmethod
    def _preferred_stylist_id(db: Session, customer_id: uuid.UUID) -> Optional[uuid.UUID]:
        """客户的专属发型师：取历史预约里出现最多的那个（最近的优先）"""
        appts = db.query(Appointment).filter(
            Appointment.customer_id == customer_id,
            Appointment.status != AppointmentStatus.CANCELLED,
        ).order_by(Appointment.appointment_datetime.desc()).all()
        if not appts:
            return None
        counts = Counter(a.stylist_id for a in appts)
        # 出现次数最多；并列时取最近一次
        best = max(counts, key=lambda sid: (counts[sid], -appts.index(
            next(a for a in appts if a.stylist_id == sid))))
        return best

    @staticmethod
    def _has_recent_reminder(db: Session, customer_id: uuid.UUID,
                             reminder_type: ReminderType) -> bool:
        """冷却期内是否已有同类提醒（PENDING 或近期 CONTACTED），避免重复生成"""
        cutoff = datetime.now() - timedelta(days=REMINDER_COOLDOWN_DAYS)
        existing = db.query(ReminderLog).filter(
            ReminderLog.customer_id == customer_id,
            ReminderLog.reminder_type == reminder_type,
            ReminderLog.status != ReminderStatus.DISMISSED,
            ReminderLog.created_at >= cutoff,
        ).first()
        return existing is not None

    # ---------- 话术生成（纯模板，第二步再换 LLM） ----------

    @staticmethod
    def _msg_repurchase(name: str, last_service: Optional[str], days: int) -> str:
        svc = f"上次做的{last_service}" if last_service else "上次的造型"
        return (f"{name}您好~ 距上次到店已经 {days} 天啦，{svc}这会儿差不多该打理了，"
                f"这周有空我帮您留个位置？")

    @staticmethod
    def _msg_birthday(name: str, days_until: int) -> str:
        when = "今天" if days_until == 0 else f"还有 {days_until} 天"
        return (f"{name}您好~ 您生日{when}就到啦，提前祝您生日快乐！"
                f"给您备了一份生日护理，想约哪天过来我帮您安排~")

    @staticmethod
    def _msg_churn(name: str, days: int) -> str:
        return (f"{name}您好~ 好久没见您啦，算下来有 {days} 天没来了，挺想念的~ "
                f"最近店里有老客回归的优惠，要不要找个时间过来我帮您弄一下？")

    # ---------- 单客户判定 ----------

    @classmethod
    def _evaluate_customer(cls, db: Session, customer: User) -> Optional[dict]:
        """对单个客户跑三条规则，返回命中的最高优先级待办（或 None）。

        同一客户一次扫描只生成一条最重要的提醒，避免刷屏。
        """
        now = datetime.now()
        name = customer.name

        # --- 生日：先看窗口内（生日与复购/流失可能同时命中，生日体验更好优先） ---
        if customer.birthday:
            days_until = cls._days_until_birthday(customer.birthday, now)
            if days_until is not None and 0 <= days_until <= BIRTHDAY_LOOKAHEAD_DAYS:
                if not cls._has_recent_reminder(db, customer.id, ReminderType.BIRTHDAY):
                    return {
                        "type": ReminderType.BIRTHDAY,
                        "reason": f"{days_until} 天后生日" if days_until else "今天生日",
                        "message": cls._msg_birthday(name, days_until),
                        "reference_date": now,
                    }

        # --- 复购 / 流失：都依赖到店节奏 ---
        if not customer.last_visit:
            return None
        days_since = (now - customer.last_visit).days
        cycle, basis = cls.compute_cycle_days(db, customer)
        last_service = None
        visits = cls._past_visits(db, customer.id)
        if visits:
            last_service = visits[-1].service

        if days_since >= cycle * CHURN_MULTIPLIER:
            if cls._has_recent_reminder(db, customer.id, ReminderType.CHURN_RISK):
                return None
            return {
                "type": ReminderType.CHURN_RISK,
                "reason": f"距上次到店 {days_since} 天，{basis}，已达流失风险",
                "message": cls._msg_churn(name, days_since),
                "reference_date": customer.last_visit,
            }

        if days_since >= cycle * REPURCHASE_BUFFER:
            if cls._has_recent_reminder(db, customer.id, ReminderType.REPURCHASE):
                return None
            return {
                "type": ReminderType.REPURCHASE,
                "reason": f"距上次到店 {days_since} 天，{basis}，该回店了",
                "message": cls._msg_repurchase(name, last_service, days_since),
                "reference_date": customer.last_visit,
            }

        return None

    @staticmethod
    def _days_until_birthday(birthday: str, now: datetime) -> Optional[int]:
        """birthday 存的是 MM-DD，算距下一个生日还有几天（跨年也对）"""
        try:
            month, day = (int(x) for x in birthday.split("-"))
        except (ValueError, AttributeError):
            return None
        this_year = now.year
        try:
            next_bday = datetime(this_year, month, day)
        except ValueError:
            return None  # 2-29 等非法日期直接跳过
        if next_bday.date() < now.date():
            try:
                next_bday = datetime(this_year + 1, month, day)
            except ValueError:
                return None
        return (next_bday.date() - now.date()).days

    # ---------- 扫描入口 ----------

    @classmethod
    def scan_and_generate(cls, db: Session) -> dict:
        """扫描全店客户，生成待办写入 ReminderLog，返回本次统计"""
        logger.info("🔍 留存引擎开始扫描...")
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()

        created = {ReminderType.REPURCHASE: 0, ReminderType.BIRTHDAY: 0,
                   ReminderType.CHURN_RISK: 0}

        for customer in customers:
            hit = cls._evaluate_customer(db, customer)
            if not hit:
                continue
            stylist_id = cls._preferred_stylist_id(db, customer.id)
            reminder = ReminderLog(
                id=uuid.uuid4(),
                customer_id=customer.id,
                stylist_id=stylist_id,
                reminder_type=hit["type"],
                status=ReminderStatus.PENDING,
                priority=PRIORITY[hit["type"]],
                reason=hit["reason"],
                suggested_message=hit["message"],
                reference_date=hit["reference_date"],
            )
            db.add(reminder)
            created[hit["type"]] += 1

        db.commit()
        total = sum(created.values())
        logger.info(f"✅ 扫描完成，新增 {total} 条待办：{ {k.value: v for k, v in created.items()} }")
        return {
            "total": total,
            "repurchase": created[ReminderType.REPURCHASE],
            "birthday": created[ReminderType.BIRTHDAY],
            "churn_risk": created[ReminderType.CHURN_RISK],
        }

    # ---------- 工作台查询 / 操作 ----------

    @staticmethod
    def list_reminders(db: Session, stylist_id: Optional[str] = None,
                       status: str = "pending") -> List[ReminderLog]:
        """工作台清单：某发型师（或全店）的待办，按优先级+时间排序"""
        query = db.query(ReminderLog)
        if status:
            query = query.filter(ReminderLog.status == ReminderStatus[status.upper()])
        if stylist_id:
            query = query.filter(ReminderLog.stylist_id == uuid.UUID(stylist_id))
        return query.order_by(
            ReminderLog.priority.desc(),
            ReminderLog.created_at.desc(),
        ).all()

    @staticmethod
    def mark_contacted(db: Session, reminder_id: str, actor: Optional[User] = None) -> bool:
        """发型师点「已联系」"""
        reminder = db.query(ReminderLog).filter(
            ReminderLog.id == uuid.UUID(reminder_id)
        ).first()
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
        logger.info(f"✅ 提醒 {reminder_id} 标记为已联系")
        return True

    @staticmethod
    def dismiss(db: Session, reminder_id: str) -> bool:
        """忽略某条提醒"""
        reminder = db.query(ReminderLog).filter(
            ReminderLog.id == uuid.UUID(reminder_id)
        ).first()
        if not reminder:
            return False
        reminder.status = ReminderStatus.DISMISSED
        db.commit()
        return True
