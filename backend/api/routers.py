"""API 路由 — 所有 REST 接口"""

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session
from loguru import logger
from datetime import datetime, timedelta
import uuid
import json
import re

from backend.database.connection import get_db
from backend.config import settings
from backend.database.service import (
    UserService, StylistService, TimeSlotService, AppointmentService, MemberService,
)
from backend.database.retention import (
    BIRTHDAY_LOOKAHEAD_DAYS,
    CHURN_THRESHOLD_DAYS,
    REPURCHASE_BUFFER,
    RetentionService,
)
from backend.database.finance import FinanceError, FinanceService, amount_to_cents, cents_to_amount
from backend.database.membership import member_display_level
from backend.database.appointment_change import AppointmentChangeError
from backend.database.init_db import init_database, seed_sample_data
from backend.database.models import (
    AuditLog, Member, Notification, NotificationKind, PointTransaction,
    RefundRequest, Transaction, User, ReminderLog, WalletAccount,
    WalletTransaction, Appointment, Stylist, UserRole, AgentTaskState, AgentTaskStatus,
    RefundStatus, WalletDirection, WalletTransactionType, AppointmentStatus,
    ServicePackage, CustomerPackage, CustomerPackageStatus,
    ServiceVerification, ServiceVerificationStatus, StylistTimeSlot,
    RetentionContact, RetentionContactStatus, RetentionSuppression,
    RetentionSuppressionType, RetentionTask, RetentionTaskStatus, ReminderType,
)
from backend.auth.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_customer,
    require_staff,
    require_admin,
    verify_password,
)
from backend.client.appointment import client_appointment_service
from backend.staff.schedule import staff_schedule_service
from backend.agents.chat_agent import chat_agent
from backend.agents.langchain_agent import langchain_agent
from backend.api.schemas import (
    ChatRequest, ChatResponse,
    StylistResponse, TimeSlotResponse,
    AppointmentCreate, AppointmentResponse, StaffAppointmentCreate, StaffBookingResponse,
    CustomerResponse, MemberCreate, MemberResponse,
    TransactionCreate, TransactionResponse, BirthdayCampaignResponse,
    StaffScheduleResponse, InitDBResponse,
    ReminderResponse, ScanResultResponse,
    AuthRegisterRequest, AuthLoginRequest, WechatLoginRequest, TokenResponse, CurrentUserResponse,
    ProfileUpdate,
    RechargeRequest, WalletResponse, WalletTransactionResponse,
    RefundCreate, RefundDecisionRequest, RefundResponse, NotificationResponse, AuditLogResponse,
    PointTransactionResponse,
    StaffCustomerWalletResponse, StaffServiceBreakdownResponse, StaffVerifiedServiceResponse,
    StaffPerformanceCustomerResponse, StaffPerformanceResponse, StaffOverviewResponse,
    ServicePackageCreate, ServicePackageResponse,
    CustomerPackageAssignRequest, CustomerPackageResponse,
    ServiceVerificationCreate, ServiceCompletionRequest, ServiceVerificationResponse,
    ServiceVerificationOptionsResponse,
    StaffAgentQueryRequest, StaffAgentQueryResponse,
    AppointmentChangeProposalRequest, AppointmentApprovalProposalRequest, RefundDecisionProposalRequest,
    AgentTaskResponse, AgentConfirmationRequest,
    RetentionAgentResponse,
    RetentionCloseRequest, RetentionContactResponse, RetentionIgnoreRequest,
    RetentionManualFollowupRequest, RetentionReplyRequest, RetentionSendRequest,
    RetentionTaskDetailResponse, RetentionTaskResponse,
)
from backend.agents.staff_graph import run_staff_query
from backend.agents.staff_intent import classify_staff_intent
from backend.agents.appointment_change_graph import run_appointment_change_workflow
from backend.agents.retention_graph import run_retention_graph
from backend.retention.sender import MockMessageSender

router = APIRouter(prefix="/api", tags=["API"])

def _validate_birthday(value: str | None) -> None:
    """Validate MM-DD birthdays, including real calendar days such as 02-29."""
    if value is None:
        return
    try:
        datetime.strptime(f"2000-{value}", "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="生日必须是有效的 MM-DD 日期") from exc

def _member_balance_cents(member: Member) -> int:
    wallet = getattr(member.user, "wallet_account", None)
    return int(wallet.balance_cents) if wallet else 0


def _member_display_level(member: Member) -> str:
    return member_display_level(member.level.value, _member_balance_cents(member))


def verify_admin_token(x_admin_token: str | None = Header(None)):
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ===== 登录与身份 =====

async def _fetch_wechat_openid(code: str) -> str:
    if not settings.WECHAT_APP_ID or not settings.WECHAT_APP_SECRET:
        raise HTTPException(status_code=503, detail="微信登录尚未配置 AppID 和 AppSecret")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": settings.WECHAT_APP_ID,
                    "secret": settings.WECHAT_APP_SECRET,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("WeChat login exchange failed: {}", exc)
        raise HTTPException(status_code=502, detail="微信服务暂时不可用，请稍后重试") from exc

    if payload.get("errcode") or not payload.get("openid"):
        raise HTTPException(status_code=401, detail="微信登录凭证无效，请重试")
    return payload["openid"]

@router.post("/auth/register", response_model=CurrentUserResponse, status_code=201)
async def register_customer(request: AuthRegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.phone == request.phone).first()
    if existing:
        raise HTTPException(status_code=409, detail="手机号已注册")

    user = User(
        id=uuid.uuid4(),
        name=request.name,
        phone=request.phone,
        role=UserRole.CUSTOMER,
        password_hash=hash_password(request.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return CurrentUserResponse(
        user_id=str(user.id), name=user.name, phone=user.phone, role=user.role.value
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    request: AuthLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.phone == request.phone,
        User.is_active.is_(True),
    ).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="手机号或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(user)
    _set_auth_cookie(response, access_token)
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/wechat", response_model=TokenResponse)
async def wechat_login(
    request: WechatLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    openid = await _fetch_wechat_openid(request.code)
    user = db.query(User).filter(User.wechat_openid == openid).first()

    if user and not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用，请联系门店")

    if not user:
        user = User(
            name="微信用户",
            phone=None,
            wechat_openid=openid,
            role=UserRole.CUSTOMER,
            password_hash=None,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(user)
    _set_auth_cookie(response, access_token)
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(key="access_token", samesite="lax")


@router.get("/auth/me", response_model=CurrentUserResponse)
async def get_current_user_profile(user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        user_id=str(user.id),
        name=user.name,
        phone=user.phone,
        role=user.role.value,
        birthday=user.birthday,
    )


@router.patch("/profile", response_model=CurrentUserResponse)
async def update_customer_profile(
    request: ProfileUpdate,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if request.name is not None:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="姓名不能为空")
        current_user.name = name
    if request.birthday is not None:
        _validate_birthday(request.birthday)
        current_user.birthday = request.birthday

    db.commit()
    db.refresh(current_user)
    return CurrentUserResponse(
        user_id=str(current_user.id),
        name=current_user.name,
        phone=current_user.phone,
        role=current_user.role.value,
        birthday=current_user.birthday,
    )


# ===== AI 对话 =====

@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, current_user: User = Depends(require_customer)):
    logger.info(f"Chat: {current_user.phone} -> {request.message[:50]}")
    result = chat_agent.handle_message(
        message=request.message,
        phone=current_user.phone,
        name=current_user.name,
    )
    return ChatResponse(**result)


@router.post("/chat/langchain", response_model=ChatResponse)
def chat_with_langchain_adapter(
    request: ChatRequest, current_user: User = Depends(require_customer)
):
    role = "staff" if current_user.role in {UserRole.STYLIST, UserRole.ADMIN} else "customer"
    logger.info(f"LangChain agent: {role} {current_user.phone} -> {request.message[:50]}")
    result = langchain_agent.handle_message(
        message=request.message,
        phone=current_user.phone,
        name=current_user.name,
        role=role,
    )
    return ChatResponse(**result)


def _find_pending_appointment_from_message(db: Session, message: str) -> tuple[Appointment | None, str | None]:
    compact = message.replace(" ", "")
    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    phone_matches = [customer for customer in customers if customer.phone and customer.phone in compact]
    name_matches = [customer for customer in customers if len(customer.name or "") >= 2 and customer.name in compact]
    matched = {customer.id: customer for customer in [*phone_matches, *name_matches]}
    if len(matched) != 1:
        if len(matched) > 1:
            return None, "找到多位同名或匹配客户，请补充手机号后再批复。"
        return None, "请提供客户姓名或手机号，我才能定位待确认预约。"

    customer = next(iter(matched.values()))
    appointments = db.query(Appointment).filter(
        Appointment.customer_id == customer.id,
        Appointment.status == AppointmentStatus.PENDING,
    ).order_by(Appointment.appointment_datetime.asc()).all()
    if not appointments:
        return None, f"没有找到{customer.name}的待确认预约。"
    if len(appointments) > 1:
        options = "；".join(
            f"{item.appointment_datetime:%Y-%m-%d %H:%M} {item.service}（预约ID {item.id}）"
            for item in appointments[:5]
        )
        return None, f"{customer.name}有多条待确认预约：{options}。请提供要批复的预约ID。"
    return appointments[0], None


def _find_active_appointment_from_message(db: Session, message: str) -> tuple[Appointment | None, str | None]:
    """Resolve one mutable appointment without treating a name match as sufficient."""
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        appointment = db.query(Appointment).filter(Appointment.id == uuid.UUID(identifiers[0])).first()
        if not appointment:
            return None, "没有找到该预约编号。"
        if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
            return None, "已取消或已完成的预约不能调整。"
        return appointment, None

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) != 1:
        return None, "请提供客户姓名或手机号，我才能定位要调整的预约。"

    customer = next(iter(matches.values()))
    appointments = db.query(Appointment).filter(
        Appointment.customer_id == customer.id,
        Appointment.status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED]),
    ).order_by(Appointment.appointment_datetime.asc()).all()
    if not appointments:
        return None, f"没有找到{customer.name}可以调整的预约。"
    if len(appointments) > 1:
        options = "；".join(
            f"{item.appointment_datetime:%Y-%m-%d %H:%M} {item.service}（预约ID {item.id}）"
            for item in appointments[:5]
        )
        return None, f"{customer.name}有多条可调整预约：{options}。请提供预约ID。"
    return appointments[0], None


def _date_from_manager_message(message: str) -> str | None:
    compact = message.replace(" ", "")
    matched = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", compact)
    if matched:
        try:
            return datetime(int(matched.group(1)), int(matched.group(2)), int(matched.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return None
    days_after = 1 if "明天" in compact else 2 if "后天" in compact else 0 if any(word in compact for word in ("今天", "今日")) else None
    return (datetime.now() + timedelta(days=days_after)).strftime("%Y-%m-%d") if days_after is not None else None


def _time_from_manager_message(message: str) -> str | None:
    compact = message.replace(" ", "")
    matched = re.search(r"(?:(上午|下午|晚上|中午))?(\d{1,2})[:：](\d{2})", compact)
    if not matched:
        matched = re.search(r"(?:(上午|下午|晚上|中午))?(\d{1,2})(?:点|时)", compact)
    if not matched:
        return None
    period, hour, minute = matched.groups()
    value = int(hour)
    if period in {"下午", "晚上"} and value < 12:
        value += 12
    if period == "中午" and value < 11:
        value += 12
    if not 0 <= value <= 23:
        return None
    return f"{value:02d}:{minute or '00'}"


def _find_target_slot_from_message(
    db: Session, message: str, appointment: Appointment,
) -> tuple[StylistTimeSlot | None, str | None]:
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if len(identifiers) >= 2:
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.id == uuid.UUID(identifiers[1])).first()
        return (slot, None) if slot else (None, "没有找到新的时间槽编号。")

    date = _date_from_manager_message(compact)
    time = _time_from_manager_message(compact)
    if not date or not time:
        return None, "请补充新的日期和时间，例如“改到明天下午3点”。"

    slots = db.query(StylistTimeSlot).filter(
        StylistTimeSlot.date == date,
        StylistTimeSlot.time == time,
        StylistTimeSlot.is_booked.is_(False),
    ).all()
    named_stylists = [stylist for stylist in db.query(Stylist).all() if stylist.user and stylist.user.name in compact]
    slots = [slot for slot in slots if slot.stylist_id == (named_stylists[0].id if named_stylists else appointment.stylist_id)]
    if len(slots) == 1:
        return slots[0], None
    if not slots:
        return None, f"没有找到{date} {time}的可用时间槽，请换一个时间或指定发型师。"
    options = "；".join(f"{slot.stylist.user.name}老师（时间槽ID {slot.id}）" for slot in slots[:5])
    return None, f"{date} {time}有多个可用发型师：{options}。请指定发型师或时间槽ID。"


def _find_customer_for_agent(
    db: Session, message: str,
) -> tuple[User | None, str | None]:
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        customer = db.query(User).filter(
            User.id == uuid.UUID(identifiers[0]),
            User.role == UserRole.CUSTOMER,
        ).first()
        return (customer, None) if customer else (None, "没有找到这个客户编号对应的客户。")

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) == 1:
        return next(iter(matches.values())), None
    if len(matches) > 1:
        return None, "找到多个匹配客户，请补充手机号。"
    return None, "请提供客户姓名或手机号。"


def _service_from_manager_message(message: str) -> str | None:
    compact = message.replace(" ", "")
    services = ("头皮护理", "洗剪吹", "染发", "烫发", "护理", "剪发")
    return next((service for service in services if service in compact), None)


def _find_staff_booking_request(
    db: Session, message: str,
) -> tuple[StaffAppointmentCreate | None, str | None]:
    customer, clarification = _find_customer_for_agent(db, message)
    if not customer:
        return None, clarification
    service = _service_from_manager_message(message)
    if not service:
        return None, "请补充服务项目，例如剪发、染发或护理。"
    date = _date_from_manager_message(message)
    time = _time_from_manager_message(message)
    if not date or not time:
        return None, "请补充预约日期和时间，例如“明天下午3点”。"

    compact = message.replace(" ", "")
    stylists = db.query(Stylist).filter(Stylist.is_available.is_(True)).all()
    named_stylists = [stylist for stylist in stylists if stylist.user and stylist.user.name in compact]
    slots = db.query(StylistTimeSlot).filter(
        StylistTimeSlot.date == date,
        StylistTimeSlot.time == time,
        StylistTimeSlot.is_booked.is_(False),
    ).all()
    if named_stylists:
        slots = [slot for slot in slots if slot.stylist_id == named_stylists[0].id]
    if len(slots) != 1:
        if not slots:
            return None, f"没有找到{date} {time}的可用时间槽，请换个时间或指定发型师。"
        options = "；".join(f"{slot.stylist.user.name}老师（时间槽ID {slot.id}）" for slot in slots[:5])
        return None, f"{date} {time}有多个可用发型师，请指定一位：{options}。"
    slot = slots[0]
    return StaffAppointmentCreate(
        customer_id=str(customer.id),
        stylist_id=str(slot.stylist_id),
        slot_id=str(slot.id),
        service=service,
    ), None


def _find_retention_task_from_message(
    db: Session, message: str,
) -> tuple[RetentionTask | None, str | None]:
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        task = db.query(RetentionTask).filter(RetentionTask.id == uuid.UUID(identifiers[0])).first()
        return (task, None) if task else (None, "没有找到留存任务编号。")

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) != 1:
        return None, "请提供客户姓名、手机号或留存任务编号。"
    customer = next(iter(matches.values()))
    tasks = db.query(RetentionTask).filter(
        RetentionTask.customer_id == customer.id,
    ).order_by(RetentionTask.created_at.desc()).all()
    if not tasks:
        return None, f"没有找到{customer.name}的留存任务。"
    if len(tasks) > 1:
        options = "；".join(f"{item.primary_type.value}（任务ID {item.id}）" for item in tasks[:5])
        return None, f"{customer.name}有多条留存任务：{options}。请提供任务ID。"
    return tasks[0], None


def _retention_management_action_from_message(message: str) -> str | None:
    compact = message.replace(" ", "")
    if any(word in compact for word in ("转人工", "人工跟进")):
        return "manual_followup"
    if any(word in compact for word in ("忽略", "不再联系", "退订")):
        return "ignore"
    if any(word in compact for word in ("记录回复", "客户回复")):
        return "reply"
    if any(word in compact for word in ("关闭任务", "完成跟进", "关闭跟进")) or (
        "关闭" in compact and any(word in compact for word in ("留存", "跟进"))
    ):
        return "close"
    return None


def _retention_ignore_mode_from_message(message: str) -> str:
    compact = message.replace(" ", "")
    if "90天" in compact:
        return "90_days"
    if "永久" in compact:
        return "permanent"
    if "退订" in compact:
        return "unsubscribe"
    return "30_days"


def _amount_from_manager_message(message: str) -> float | None:
    compact = message.replace(" ", "")
    matched = re.search(r"(\d+(?:\.\d+)?)元", compact)
    return float(matched.group(1)) if matched else None


def _find_verified_service_from_message(
    db: Session, message: str,
) -> tuple[ServiceVerification | None, str | None]:
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        verification = db.query(ServiceVerification).filter(
            ServiceVerification.id == uuid.UUID(identifiers[0]),
        ).first()
        if not verification:
            return None, "没有找到该服务核验编号。"
        if verification.status != ServiceVerificationStatus.VERIFIED:
            return None, "该服务当前不是“已核验”状态，不能完成。"
        return verification, None

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) != 1:
        return None, "请提供客户姓名、手机号或服务核验编号，我才能定位要完成的服务。"
    customer = next(iter(matches.values()))
    verifications = db.query(ServiceVerification).filter(
        ServiceVerification.customer_id == customer.id,
        ServiceVerification.status == ServiceVerificationStatus.VERIFIED,
    ).order_by(ServiceVerification.verified_at.asc()).all()
    if not verifications:
        return None, f"没有找到{customer.name}已核验但未完成的服务。"
    if len(verifications) > 1:
        options = "；".join(
            f"{item.service} {item.amount:.2f}元（核验ID {item.id}）"
            for item in verifications[:5]
        )
        return None, f"{customer.name}有多条待完成服务：{options}。请提供核验ID。"
    return verifications[0], None


def _find_sendable_retention_task_from_message(
    db: Session, message: str,
) -> tuple[RetentionTask | None, str | None]:
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        task = db.query(RetentionTask).filter(RetentionTask.id == uuid.UUID(identifiers[0])).first()
        if not task:
            return None, "没有找到留存任务编号。"
        if task.status not in {RetentionTaskStatus.PENDING_REVIEW, RetentionTaskStatus.SEND_FAILED}:
            return None, "该留存任务当前不能发送。"
        return task, None

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) != 1:
        return None, "请提供客户姓名、手机号或留存任务编号，我才能定位要发送的提醒。"
    customer = next(iter(matches.values()))
    tasks = db.query(RetentionTask).filter(
        RetentionTask.customer_id == customer.id,
        RetentionTask.status.in_([RetentionTaskStatus.PENDING_REVIEW, RetentionTaskStatus.SEND_FAILED]),
    ).order_by(RetentionTask.priority.desc(), RetentionTask.created_at.asc()).all()
    if not tasks:
        return None, f"没有找到{customer.name}可以发送的留存任务。"
    if len(tasks) > 1:
        options = "；".join(
            f"{item.primary_type.value}（任务ID {item.id}）" for item in tasks[:5]
        )
        return None, f"{customer.name}有多条可发送的留存任务：{options}。请提供任务ID。"
    return tasks[0], None


def _retention_message_from_manager_request(message: str, fallback: str | None) -> str:
    matched = re.search(r"[：:](.+)$", message.strip())
    candidate = matched.group(1).strip() if matched else ""
    return candidate or (fallback or "")


def _is_batch_birthday_retention_request(db: Session, message: str) -> bool:
    compact = message.replace(" ", "")
    send_words = ("发送", "发出", "发了", "发一下", "推送")
    if "生日" not in compact or not any(word in compact for word in send_words):
        return False
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        return False
    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    has_target = any(
        (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
        for customer in customers
    )
    return not has_target or any(word in compact for word in ("全部", "所有", "批量", "一键", "一起", "都", "全量"))


def _deny_staff_workbench_action(
    db: Session,
    task: AgentTaskState,
    current_user: User,
    intent: str,
    action_label: str,
) -> StaffAgentQueryResponse:
    reply = f"当前员工账号不能{action_label}，只有店长账号可以通过员工助手操作工作台。"
    task.status = AgentTaskStatus.COMPLETED
    task.result_payload = json.dumps(
        {"reply": reply, "intent": intent, "permission_denied": True},
        ensure_ascii=False,
    )
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.workbench_action_denied",
        "agent_task",
        str(task.id),
        {"intent": intent, "action": action_label},
    )
    db.commit()
    return StaffAgentQueryResponse(
        task_id=str(task.id),
        status=task.status.value,
        reply=reply,
        actions=[f"intent:{intent}", "permission_denied"],
        sources=["authorization:admin_only_workbench_actions"],
        trace_id=str(task.id),
    )


def _send_birthday_retention_tasks(
    db: Session,
    current_user: User,
) -> dict[str, object]:
    tasks = db.query(RetentionTask).filter(
        RetentionTask.primary_type == ReminderType.BIRTHDAY,
        RetentionTask.status.in_([
            RetentionTaskStatus.PENDING_REVIEW,
            RetentionTaskStatus.SEND_FAILED,
        ]),
    ).order_by(RetentionTask.priority.desc(), RetentionTask.created_at.asc()).all()

    success_count = 0
    failed: list[dict[str, str]] = []
    for retention_task in tasks:
        task_id = str(retention_task.id)
        customer_name = retention_task.customer.name
        retry_only = retention_task.status == RetentionTaskStatus.SEND_FAILED
        try:
            result = _send_retention_task(
                db,
                task_id,
                current_user,
                RetentionSendRequest(message=retention_task.suggested_message or "生日快乐，欢迎回来体验服务。"),
                retry_only=retry_only,
                commit=True,
            )
            if result.status == RetentionTaskStatus.COOLING.value:
                success_count += 1
            else:
                failed.append({"customer_name": customer_name, "reason": "消息渠道发送失败"})
        except HTTPException as exc:
            db.rollback()
            failed.append({"customer_name": customer_name, "reason": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            logger.exception("批量发送生日提醒失败: {}", task_id)
            failed.append({"customer_name": customer_name, "reason": str(exc)})

    summary = {
        "total": len(tasks),
        "success_count": success_count,
        "failed_count": len(failed),
        "failed": failed,
    }
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.retention_birthday_batch_send_completed",
        "retention_tasks",
        "birthday",
        summary,
    )
    db.commit()
    return summary


def _find_legacy_reminder_from_message(
    db: Session,
    message: str,
) -> tuple[ReminderLog | None, str | None]:
    """解析旧版提醒按钮对应的 ReminderLog，保持 Agent 与按钮共用同一状态。"""
    compact = message.replace(" ", "")
    identifiers = re.findall(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", compact)
    if identifiers:
        reminder = db.query(ReminderLog).filter(ReminderLog.id == uuid.UUID(identifiers[0])).first()
        return (reminder, None) if reminder else (None, "没有找到这个提醒编号。")

    customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    matches = {
        customer.id: customer
        for customer in customers
        if (customer.phone and customer.phone in compact)
        or (len(customer.name or "") >= 2 and customer.name in compact)
    }
    if len(matches) != 1:
        if len(matches) > 1:
            return None, "找到多个匹配客户，请补充手机号或提醒编号。"
        return None, "请提供客户姓名、手机号或提醒编号。"

    customer = next(iter(matches.values()))
    reminders = db.query(ReminderLog).filter(
        ReminderLog.customer_id == customer.id,
    ).order_by(ReminderLog.created_at.desc()).all()
    if not reminders:
        return None, f"没有找到{customer.name}的旧版留存提醒。"
    if len(reminders) > 1:
        options = "；".join(
            f"{item.reminder_type.value}（提醒ID {item.id}）"
            for item in reminders[:5]
        )
        return None, f"{customer.name}有多条旧版留存提醒：{options}。请提供提醒ID。"
    return reminders[0], None


def _task_has_visit_age(task: RetentionTask, days: int) -> bool:
    evidence = task.evidence or {}
    values: list[object] = []
    values.append(evidence.get("days_since_last_visit"))
    primary = evidence.get("primary") or {}
    values.append(primary.get("days_since_last_visit"))
    for reason in evidence.get("all") or []:
        values.append(reason.get("evidence", {}).get("days_since_last_visit"))
    return any(isinstance(value, (int, float)) and value >= days for value in values)


def _send_retention_tasks_since_visit(
    db: Session,
    current_user: User,
    days: int,
    message: str | None,
) -> dict[str, object]:
    """按真实 last_visit 解析人群，再复用单任务发送函数逐条发送。"""
    RetentionService.scan_and_generate(db)
    cutoff = datetime.now() - timedelta(days=days)
    raw_customers = db.query(User).filter(
        User.role == UserRole.CUSTOMER,
        User.last_visit.is_not(None),
        User.last_visit <= cutoff,
    ).all()
    customer_ids = {customer.id for customer in raw_customers}
    all_tasks = db.query(RetentionTask).filter(
        RetentionTask.customer_id.in_(customer_ids) if customer_ids else False,
    ).order_by(RetentionTask.priority.desc(), RetentionTask.created_at.asc()).all()

    matching_tasks: dict[uuid.UUID, list[RetentionTask]] = {}
    for retention_task in all_tasks:
        if retention_task.primary_type != ReminderType.CHURN_RISK and not _task_has_visit_age(retention_task, days):
            continue
        matching_tasks.setdefault(retention_task.customer_id, []).append(retention_task)

    audience_customers = [customer for customer in raw_customers if customer.id in matching_tasks]
    selected: dict[uuid.UUID, RetentionTask] = {}
    skipped: list[dict[str, str]] = []
    for customer in audience_customers:
        customer_tasks = matching_tasks[customer.id]
        sendable = [
            task for task in customer_tasks
            if task.status in {RetentionTaskStatus.PENDING_REVIEW, RetentionTaskStatus.SEND_FAILED}
        ]
        if sendable:
            selected[customer.id] = sendable[0]
            continue
        current = customer_tasks[0]
        reason = {
            RetentionTaskStatus.COOLING: "任务正在冷却期",
            RetentionTaskStatus.SENDING: "任务正在发送",
            RetentionTaskStatus.SENT: "任务已发送",
            RetentionTaskStatus.MANUAL_FOLLOWUP: "客户已转人工跟进",
            RetentionTaskStatus.IGNORED: "任务已忽略",
            RetentionTaskStatus.CLOSED: "任务已关闭",
        }.get(current.status, f"任务状态为 {current.status.value}")
        skipped.append({"customer_name": customer.name, "reason": reason})

    success_count = 0
    failed: list[dict[str, str]] = []
    for retention_task in selected.values():
        retry_only = retention_task.status == RetentionTaskStatus.SEND_FAILED
        actual_message = (message or retention_task.suggested_message or "近期有空的话，欢迎回来打理头发。").strip()
        try:
            result = _send_retention_task(
                db,
                str(retention_task.id),
                current_user,
                RetentionSendRequest(message=actual_message),
                retry_only=retry_only,
                commit=True,
            )
            if result.status == RetentionTaskStatus.COOLING.value:
                success_count += 1
            else:
                failed.append({"customer_name": retention_task.customer.name, "reason": "消息渠道发送失败"})
        except HTTPException as exc:
            db.rollback()
            failed.append({"customer_name": retention_task.customer.name, "reason": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            logger.exception("按到店天数批量发送留存消息失败: {}", retention_task.id)
            failed.append({"customer_name": retention_task.customer.name, "reason": str(exc)})

    summary: dict[str, object] = {
        "days_since_visit": days,
        "matched_customers": len(audience_customers),
        "total": len(selected),
        "sendable_tasks": len(selected),
        "success_count": success_count,
        "failed_count": len(failed),
        "failed": failed,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.retention_age_batch_send_completed",
        "retention_tasks",
        str(days),
        summary,
    )
    db.commit()
    return summary


def _looks_like_workbench_operation(message: str) -> bool:
    compact = message.replace(" ", "")
    return any(word in compact for word in (
        "预约", "改约", "退款", "核验", "核销", "完成服务", "留存", "提醒",
        "发送", "发消息", "发一次消息", "发一条消息", "发一下", "发一次", "发一条",
        "转人工", "忽略", "关闭任务", "批复", "批准", "扫描",
        "记录回复", "标记联系",
    ))


def _planning_clarification_response(
    db: Session,
    task: AgentTaskState,
    current_user: User,
    plan,
) -> StaffAgentQueryResponse:
    interpretation = plan.interpretation or "我暂时无法确定你要操作的工作台模块。"
    clarification = plan.clarification or "请补充模块、对象和动作。"
    reply = f"我理解你的意思是：{interpretation}。\n但还需要确认：{clarification}"
    task.status = AgentTaskStatus.COMPLETED
    task.result_payload = json.dumps(
        {"reply": reply, "planner": plan.model_dump(), "needs_clarification": True},
        ensure_ascii=False,
    )
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.staff_operation_needs_clarification",
        "agent_task",
        str(task.id),
        {"plan": plan.model_dump()},
    )
    db.commit()
    return StaffAgentQueryResponse(
        task_id=str(task.id),
        status=task.status.value,
        reply=reply,
        actions=["planner:clarification"],
        sources=[],
        trace_id=str(task.id),
        trace={"trace_id": str(task.id), "workflow": "staff_operation_planner"},
    )


def _refund_decision_from_message(message: str) -> str | None:
    compact = message.replace(" ", "")
    if any(word in compact for word in ("拒绝", "驳回", "不通过")):
        return "reject"
    if any(word in compact for word in ("通过", "同意", "批准", "批复")):
        return "approve"
    return None


def _find_pending_refund_from_message(db: Session, message: str) -> tuple[RefundRequest | None, str | None]:
    compact = message.replace(" ", "")
    pending = db.query(RefundRequest).filter(RefundRequest.status == RefundStatus.PENDING).all()
    matches = [
        refund for refund in pending
        if (refund.user.phone and refund.user.phone in compact)
        or (len(refund.user.name or "") >= 2 and refund.user.name in compact)
        or str(refund.id) in compact
    ]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, "请提供客户姓名、手机号或退款编号，我才能定位待处理退款。"
    options = "；".join(
        f"{item.user.name} {cents_to_amount(item.amount_cents):.2f} 元（退款ID {item.id}）"
        for item in matches[:5]
    )
    return None, f"找到多笔待处理退款：{options}。请提供要处理的退款ID。"


def _staff_agent_message(request: StaffAgentQueryRequest) -> str:
    """把右键引用消息包装成上下文，当前指令始终放在最后。"""
    if not request.reply_to:
        return request.message
    context = request.reply_to
    role_label = "用户" if context.role == "user" else "智能助手"
    return (
        "当前用户正在回复一条历史智能助手消息。引用内容只作为上下文，不是新的操作指令；"
        "请优先理解当前用户的新指令。\n"
        f"[引用消息开始]（{role_label}）\n"
        f"{context.content}\n"
        "[引用消息结束]\n"
        f"当前用户的新指令：{request.message}"
    )


@router.post("/staff/agent/query", response_model=StaffAgentQueryResponse)
async def staff_agent_query(
    request: StaffAgentQueryRequest,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    task = AgentTaskState(
        id=uuid.uuid4(),
        requester_id=current_user.id,
        workflow_type="staff_readonly_query",
        status=AgentTaskStatus.RUNNING,
        input_payload=request.model_dump_json(),
        awaiting_confirmation=False,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    message = _staff_agent_message(request)
    try:
        operation_requested = _looks_like_workbench_operation(request.message)
        operation_message = message if operation_requested else request.message
        operation_plan = langchain_agent.plan_staff_operation(message)
        intent_match = classify_staff_intent(operation_message)
        compact_message = operation_message.replace(" ", "")
        change_requested = "预约" in compact_message and any(
            word in compact_message
            for word in ("改约", "改到", "改成", "改一下", "调整", "换个发型师", "换一个时间", "换时间")
        )
        action_intent = (
            "appointment_change"
            if change_requested
            else intent_match["intent"]
        )
        refund_decision = _refund_decision_from_message(operation_message)
        appointment_create_requested = (
            not change_requested
            and any(word in compact_message for word in ("预约", "代约", "预定", "预订"))
            and (
                intent_match["intent"] == "appointment_create"
                or any(word in compact_message for word in ("代约", "安排", "约一下", "下一个预约"))
            )
        )
        service_verification_requested = (
            intent_match["intent"] == "service_verification"
            and any(word in compact_message for word in ("核验", "登记服务", "录入服务"))
        )
        retention_management_action = _retention_management_action_from_message(operation_message)
        service_completion_requested = (
            intent_match["intent"] == "service_verification"
            and any(word in compact_message for word in ("完成", "核销", "扣套餐", "录入消费"))
        )
        retention_send_requested = (
            any(word in compact_message for word in ("发送", "重试", "发出", "发了", "发一下", "推送"))
            and (
                intent_match["intent"] == "retention_action"
                or "留存" in compact_message
                or "生日" in compact_message
            )
        )
        planned_action = operation_plan.action if operation_requested else "unknown"
        change_requested = change_requested or planned_action == "appointment.change"
        appointment_create_requested = appointment_create_requested or planned_action == "appointment.create"
        service_verification_requested = service_verification_requested or planned_action == "service.verify"
        service_completion_requested = service_completion_requested or planned_action == "service.complete"
        retention_send_requested = retention_send_requested or planned_action == "retention.send"
        if planned_action in {
            "retention.manual_followup",
            "retention.ignore",
            "retention.reply",
            "retention.close",
        }:
            retention_management_action = planned_action.removeprefix("retention.")
        if planned_action == "refund.approve":
            refund_decision = "approve"
        elif planned_action == "refund.reject":
            refund_decision = "reject"
        batch_birthday_requested = (
            _is_batch_birthday_retention_request(db, operation_message)
        )
        write_action = (
            (intent_match["intent"] == "refund" and refund_decision is not None)
            or intent_match["intent"] == "appointment_approval"
            or change_requested
            or appointment_create_requested
            or service_verification_requested
            or service_completion_requested
            or retention_send_requested
            or retention_management_action is not None
            or planned_action in {
                "retention.scan",
                "retention.reminder_contacted",
                "retention.reminder_dismiss",
            }
        )
        if write_action and current_user.role != UserRole.ADMIN:
            denied_intent = (
                "retention_action"
                if retention_send_requested or retention_management_action
                else "appointment_create"
                if appointment_create_requested
                else "service_verification"
                if service_verification_requested
                else action_intent
            )
            action_label = {
                "refund": "处理退款",
                "appointment_approval": "批复预约",
                "appointment_change": "改约",
                "appointment_create": "创建预约",
                "service_verification": "完成服务",
                "retention_action": "发送留存提醒",
                "retention.scan": "运行留存扫描",
                "retention.reminder_contacted": "标记留存提醒已联系",
                "retention.reminder_dismiss": "忽略留存提醒",
            }.get(denied_intent, "执行工作台操作")
            if retention_management_action:
                action_label = "处理留存任务"
            if planned_action in {"retention.scan", "retention.reminder_contacted", "retention.reminder_dismiss"}:
                denied_intent = planned_action
                action_label = {
                    "retention.scan": "运行留存扫描",
                    "retention.reminder_contacted": "标记留存提醒",
                    "retention.reminder_dismiss": "忽略留存提醒",
                }[planned_action]
            return _deny_staff_workbench_action(
                db,
                task,
                current_user,
                denied_intent,
                action_label,
            )

        if planned_action == "unknown" and operation_requested:
            return _planning_clarification_response(db, task, current_user, operation_plan)

        if planned_action == "retention.scan":
            scan_result = await scan_retention(None, current_user, db)
            reply = (
                f"留存扫描完成：新增复购 {scan_result.repurchase} 条、"
                f"生日 {scan_result.birthday} 条、流失风险 {scan_result.churn_risk} 条。"
            )
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": "retention.scan", "scan": scan_result.model_dump()},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db,
                current_user.id,
                "agent.retention_scan_completed",
                "retention_scan",
                str(task.id),
                scan_result.model_dump(),
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id),
                status=task.status.value,
                reply=reply,
                actions=["intent:retention.scan", "tool:scan_retention"],
                sources=["database:customers", "database:retention_tasks"],
                trace_id=str(task.id),
            )

        if planned_action in {"retention.reminder_contacted", "retention.reminder_dismiss"}:
            reminder, clarification = _find_legacy_reminder_from_message(db, message)
            if not reminder:
                return _planning_clarification_response(
                    db,
                    task,
                    current_user,
                    operation_plan.model_copy(update={"clarification": clarification or operation_plan.clarification}),
                )
            if planned_action == "retention.reminder_contacted":
                result = await mark_reminder_contacted(str(reminder.id), current_user, db)
                action_label = "已联系"
            else:
                result = await dismiss_reminder(str(reminder.id), current_user, db)
                action_label = "已忽略"
            reply = f"{reminder.customer.name}的留存提醒{action_label}。"
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": planned_action, "result": result},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db,
                current_user.id,
                "agent.legacy_reminder_action_completed",
                "reminder_log",
                str(reminder.id),
                {"action": planned_action},
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id),
                status=task.status.value,
                reply=reply,
                actions=[f"intent:{planned_action}", "tool:legacy_reminder_action"],
                sources=["database:reminder_logs", "notification:customer"],
                trace_id=str(task.id),
            )

        if planned_action == "retention.send" and operation_plan.days_since_visit:
            summary = _send_retention_tasks_since_visit(
                db,
                current_user,
                operation_plan.days_since_visit,
                operation_plan.message,
            )
            failed_names = "、".join(item["customer_name"] for item in summary["failed"])
            skipped_names = "、".join(
                f"{item['customer_name']}（{item['reason']}）"
                for item in summary["skipped"]
            )
            reply = (
                f"已按距上次到店 {summary['days_since_visit']} 天以上筛选流失客户："
                f"命中 {summary['matched_customers']} 人，可发送任务 {summary['sendable_tasks']} 条，"
                f"成功 {summary['success_count']} 条，失败 {summary['failed_count']} 条，"
                f"跳过 {summary['skipped_count']} 人。"
            )
            if failed_names:
                reply += f"失败客户：{failed_names}。"
            if skipped_names:
                reply += f"跳过客户：{skipped_names}。"
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": "retention.send", "batch": summary},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db,
                current_user.id,
                "agent.retention_age_batch_send_reported",
                "agent_task",
                str(task.id),
                summary,
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id),
                status=task.status.value,
                reply=reply,
                actions=["intent:retention.send", "tool:batch_send_retention_by_visit_age"],
                sources=["database:customers", "database:retention_tasks", "notification:customer"],
                trace_id=str(task.id),
            )

        if (intent_match["intent"] == "refund" or planned_action in {"refund.approve", "refund.reject"}) and refund_decision:
            trace = {
                "trace_id": str(task.id),
                "workflow": "manager_action_router",
                "steps": [{
                    "node": "semantic_intent_retrieval",
                    "status": "completed",
                    "intent": intent_match["intent"],
                    "method": intent_match["method"],
                    "score": intent_match["score"],
                }],
            }

            refund, clarification = _find_pending_refund_from_message(db, message)
            if not refund:
                reply = clarification or "没有找到可以处理的退款。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "refund", "trace": trace}, ensure_ascii=False)
                FinanceService.create_audit(
                    db, current_user.id, "agent.refund_decision_needs_clarification", "agent_task", str(task.id),
                    {"message": request.message, "decision": refund_decision},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:refund", "tool:lookup_pending_refund"],
                    sources=["database:refund_requests"], trace_id=str(task.id), trace=trace,
                )

            refund_task = _create_refund_decision_task(
                db, refund, refund_decision, current_user, source_message=request.message
            )
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps({
                "intent": "refund", "refund_task_id": str(refund_task.id), "trace": trace,
            }, ensure_ascii=False)
            FinanceService.create_audit(
                db, current_user.id, "agent.manager_action_routed", "agent_task", str(task.id),
                {"intent": "refund", "refund_task_id": str(refund_task.id)},
            )
            db.commit()
            db.refresh(refund_task)
            proposal = _refund_decision_proposal(refund, refund_decision)
            action_text = "通过" if refund_decision == "approve" else "拒绝"
            reply = (
                f"已找到{proposal['customer_name']}的退款申请：{proposal['amount']:.2f} 元。"
                f"请再次输入当前员工登录密码，确认{action_text}退款。"
            )
            return StaffAgentQueryResponse(
                task_id=str(refund_task.id), status=refund_task.status.value, reply=reply,
                actions=["intent:refund", "tool:propose_refund_decision"],
                sources=["database:refund_requests", "database:wallets"],
                trace_id=str(task.id), trace=trace,
                agent_task=_agent_task_response(refund_task).model_dump(),
            )

        if intent_match["intent"] == "appointment_approval" or planned_action == "appointment.approve":
            trace = {
                "trace_id": str(task.id),
                "workflow": "manager_action_router",
                "steps": [{
                    "node": "semantic_intent_retrieval",
                    "status": "completed",
                    "intent": intent_match["intent"],
                    "method": intent_match["method"],
                    "score": intent_match["score"],
                }],
            }

            appointment, clarification = _find_pending_appointment_from_message(db, message)
            if not appointment:
                reply = clarification or "没有找到可以批复的预约。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": intent_match["intent"], "trace": trace}, ensure_ascii=False)
                FinanceService.create_audit(
                    db,
                    current_user.id,
                    "agent.appointment_approval_needs_clarification",
                    "agent_task",
                    str(task.id),
                    {"message": request.message},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:appointment_approval", "tool:lookup_pending_appointment"],
                    sources=["database:customers", "database:appointments"],
                    trace_id=str(task.id), trace=trace,
                )

            approval_task = _create_appointment_approval_task(
                db, appointment, current_user, source_message=request.message
            )
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps({
                "intent": intent_match["intent"],
                "approval_task_id": str(approval_task.id),
                "trace": trace,
            }, ensure_ascii=False)
            FinanceService.create_audit(
                db,
                current_user.id,
                "agent.manager_action_routed",
                "agent_task",
                str(task.id),
                {"intent": intent_match["intent"], "approval_task_id": str(approval_task.id)},
            )
            db.commit()
            db.refresh(approval_task)
            proposal = _appointment_approval_proposal(appointment)
            reply = (
                f"已找到{proposal['customer_name']}的待确认预约："
                f"{proposal['appointment_datetime'][:16]} {proposal['service']}，"
                f"{proposal['stylist_name']}老师。请确认是否批复。"
            )
            return StaffAgentQueryResponse(
                task_id=str(approval_task.id), status=approval_task.status.value, reply=reply,
                actions=["intent:appointment_approval", "tool:propose_appointment_approval"],
                sources=["database:customers", "database:appointments"],
                trace_id=str(task.id), trace=trace,
                agent_task=_agent_task_response(approval_task).model_dump(),
            )

        if appointment_create_requested:
            booking_request, clarification = _find_staff_booking_request(db, message)
            if not booking_request:
                reply = clarification or "请补充客户、服务、日期和时间。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps(
                    {"reply": reply, "intent": "appointment_create"},
                    ensure_ascii=False,
                )
                FinanceService.create_audit(
                    db,
                    current_user.id,
                    "agent.appointment_create_needs_clarification",
                    "agent_task",
                    str(task.id),
                    {"message": request.message},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id),
                    status=task.status.value,
                    reply=reply,
                    actions=["intent:appointment_create", "needs_parameters"],
                    sources=["database:customers", "database:stylist_time_slots"],
                    trace_id=str(task.id),
                )

            try:
                booking = await create_staff_appointment(booking_request, current_user, db)
            except HTTPException as exc:
                db.rollback()
                reply = f"代客预约失败：{exc.detail}"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps(
                    {"reply": reply, "intent": "appointment_create"},
                    ensure_ascii=False,
                )
                FinanceService.create_audit(
                    db,
                    current_user.id,
                    "agent.appointment_create_failed",
                    "agent_task",
                    str(task.id),
                    {"message": request.message, "reason": str(exc.detail)},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id),
                    status=task.status.value,
                    reply=reply,
                    actions=["intent:appointment_create", "tool:create_staff_appointment"],
                    sources=["database:appointments", "database:stylist_time_slots"],
                    trace_id=str(task.id),
                )

            reply = (
                f"已为{booking.customer_name}创建{booking.service}预约："
                f"{booking.appointment_datetime[:16]}，{booking.stylist_name}老师。"
            )
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": "appointment_create", "booking": booking.model_dump()},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db,
                current_user.id,
                "agent.appointment_created",
                "appointment",
                booking.appointment_id,
                {"agent_task_id": str(task.id), "source_message": request.message},
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id),
                status=task.status.value,
                reply=reply,
                actions=["intent:appointment_create", "tool:create_staff_appointment"],
                sources=["database:appointments", "database:stylist_time_slots", "notification:customer"],
                trace_id=str(task.id),
            )

        if change_requested:
            trace = {
                "trace_id": str(task.id),
                "workflow": "manager_action_router",
                "steps": [{
                    "node": "semantic_intent_retrieval",
                    "status": "completed",
                    "intent": action_intent,
                    "method": intent_match["method"],
                    "score": intent_match["score"],
                }],
            }

            appointment, clarification = _find_active_appointment_from_message(db, message)
            slot = None
            if appointment:
                slot, clarification = _find_target_slot_from_message(db, message, appointment)
            if not appointment or not slot:
                reply = clarification or "没有找到可以执行的预约调整。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": action_intent, "trace": trace}, ensure_ascii=False)
                FinanceService.create_audit(db, current_user.id, "agent.appointment_change_needs_clarification", "agent_task", str(task.id), {"message": request.message})
                db.commit()
                return StaffAgentQueryResponse(task_id=str(task.id), status=task.status.value, reply=reply, actions=["intent:appointment_change", "tool:lookup_appointment_and_slot"], sources=["database:customers", "database:appointments", "database:stylist_time_slots"], trace_id=str(task.id), trace=trace)

            payload = {"appointment_id": str(appointment.id), "new_slot_id": str(slot.id), "new_stylist_id": str(slot.stylist_id)}
            try:
                workflow = run_appointment_change_workflow(payload, str(current_user.id), db, confirmed=False)
            except AppointmentChangeError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            change_task = AgentTaskState(
                id=uuid.uuid4(), requester_id=current_user.id, workflow_type="appointment_change",
                status=AgentTaskStatus.AWAITING_CONFIRMATION,
                input_payload=json.dumps(payload, ensure_ascii=False),
                result_payload=json.dumps({**workflow["proposal"], "_trace": {"trace_id": workflow.get("trace_id"), "trace": workflow.get("trace", {})}}, ensure_ascii=False),
                awaiting_confirmation=True,
            )
            db.add(change_task)
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps({"intent": action_intent, "change_task_id": str(change_task.id), "trace": trace}, ensure_ascii=False)
            FinanceService.create_audit(db, current_user.id, "agent.appointment_change_proposed", "agent_task", str(change_task.id), {"appointment_id": str(appointment.id), "new_slot_id": str(slot.id), "source_message": request.message})
            db.commit()
            db.refresh(change_task)
            proposal = json.loads(change_task.result_payload)
            reply = f"已生成{proposal['customer_name']}的改约方案：{proposal['old_datetime'][:16]} {proposal['old_stylist_name']}老师，调整为 {proposal['new_datetime'][:16]} {proposal['new_stylist_name']}老师。请确认。"
            return StaffAgentQueryResponse(task_id=str(change_task.id), status=change_task.status.value, reply=reply, actions=["intent:appointment_change", "tool:propose_appointment_change"], sources=["database:customers", "database:appointments", "database:stylist_time_slots"], trace_id=str(task.id), trace=trace, agent_task=_agent_task_response(change_task).model_dump())

        if service_verification_requested:
            appointment, clarification = _find_active_appointment_from_message(db, message)
            if not appointment:
                reply = clarification or "没有找到可以核验的预约。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "service_verification"}, ensure_ascii=False)
                FinanceService.create_audit(
                    db, current_user.id, "agent.service_verification_needs_clarification", "agent_task",
                    str(task.id), {"message": request.message},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:service_verification", "needs_parameters"],
                    sources=["database:appointments"], trace_id=str(task.id),
                )

            packages = _eligible_customer_packages(appointment, db)
            amount = _amount_from_manager_message(message)
            use_package = "套餐" in compact_message or (amount is None and len(packages) == 1)
            if use_package and len(packages) > 1 and "套餐ID" not in compact_message:
                options = "；".join(f"{package.package.name}（套餐ID {package.id}）" for package in packages[:5])
                reply = f"{appointment.customer.name}有多个可用套餐，请指定一个：{options}。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "service_verification"}, ensure_ascii=False)
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:service_verification", "needs_package"],
                    sources=["database:customer_packages"], trace_id=str(task.id),
                )
            package = packages[0] if use_package and packages else None
            if not package and amount is None:
                reply = "请补充直接消费金额，例如“核验这单，金额88元”，或说明使用哪个套餐。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "service_verification"}, ensure_ascii=False)
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:service_verification", "needs_amount_or_package"],
                    sources=["database:appointments", "database:customer_packages"], trace_id=str(task.id),
                )
            try:
                verification = await verify_appointment_service(
                    str(appointment.id),
                    ServiceVerificationCreate(
                        customer_package_id=str(package.id) if package else None,
                        amount=None if package else amount,
                    ),
                    current_user,
                    db,
                )
            except HTTPException as exc:
                db.rollback()
                reply = f"服务核验失败：{exc.detail}"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "service_verification"}, ensure_ascii=False)
                FinanceService.create_audit(
                    db, current_user.id, "agent.service_verification_failed", "agent_task", str(task.id),
                    {"message": request.message, "reason": str(exc.detail)},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:service_verification", "tool:verify_appointment_service"],
                    sources=["database:appointments", "database:customer_packages"], trace_id=str(task.id),
                )

            reply = f"已核验{verification.customer_name}的{verification.service}服务，金额 {verification.amount:.2f} 元；请继续确认完成服务。"
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": "service_verification", "verification": verification.model_dump()},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db, current_user.id, "agent.service_verification_created", "service_verification",
                verification.verification_id, {"agent_task_id": str(task.id), "source_message": request.message},
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id), status=task.status.value, reply=reply,
                actions=["intent:service_verification", "tool:verify_appointment_service"],
                sources=["database:appointments", "database:customer_packages"], trace_id=str(task.id),
            )

        if service_completion_requested:
            trace = {
                "trace_id": str(task.id),
                "workflow": "manager_action_router",
                "steps": [{
                    "node": "semantic_intent_retrieval",
                    "status": "completed",
                    "intent": "service_completion",
                    "method": intent_match["method"],
                    "score": intent_match["score"],
                }],
            }

            verification, clarification = _find_verified_service_from_message(db, message)
            if not verification:
                reply = clarification or "没有找到可完成的服务。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "service_completion", "trace": trace}, ensure_ascii=False)
                FinanceService.create_audit(db, current_user.id, "agent.service_completion_needs_clarification", "agent_task", str(task.id), {"message": request.message})
                db.commit()
                return StaffAgentQueryResponse(task_id=str(task.id), status=task.status.value, reply=reply, actions=["intent:service_completion", "tool:lookup_verified_service"], sources=["database:service_verifications", "database:customers", "database:customer_packages"], trace_id=str(task.id), trace=trace)

            package = verification.customer_package
            proposal = {
                "verification_id": str(verification.id),
                "appointment_id": str(verification.appointment_id),
                "customer_name": verification.customer.name,
                "customer_phone": verification.customer.phone,
                "stylist_name": verification.stylist.user.name,
                "service": verification.service,
                "amount": verification.amount,
                "package_name": package.package.name if package else None,
                "remaining_uses_before": package.remaining_uses if package else None,
                "risk_level": "high",
            }
            completion_task = AgentTaskState(
                id=uuid.uuid4(), requester_id=current_user.id, workflow_type="service_completion",
                status=AgentTaskStatus.AWAITING_CONFIRMATION,
                input_payload=json.dumps({"verification_id": str(verification.id), "source_message": request.message}, ensure_ascii=False),
                result_payload=json.dumps(proposal, ensure_ascii=False, default=str), awaiting_confirmation=True,
            )
            db.add(completion_task)
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps({"intent": "service_completion", "service_completion_task_id": str(completion_task.id), "trace": trace}, ensure_ascii=False)
            FinanceService.create_audit(db, current_user.id, "agent.service_completion_proposed", "agent_task", str(completion_task.id), {"verification_id": str(verification.id), "source_message": request.message})
            db.commit()
            db.refresh(completion_task)
            reply = f"已找到{proposal['customer_name']}的{proposal['service']}服务，金额 {proposal['amount']:.2f} 元。" + (f"确认后将扣除{proposal['package_name']} 1 次（剩余 {proposal['remaining_uses_before']} 次）。" if package else "确认后将计入消费、积分和员工绩效。") + "请核对后确认。"
            return StaffAgentQueryResponse(task_id=str(completion_task.id), status=completion_task.status.value, reply=reply, actions=["intent:service_completion", "tool:propose_service_completion"], sources=["database:service_verifications", "database:customer_packages"], trace_id=str(task.id), trace=trace, agent_task=_agent_task_response(completion_task).model_dump())

        if retention_management_action:
            retention_task, clarification = _find_retention_task_from_message(db, message)
            if not retention_task:
                reply = clarification or "没有找到可以处理的留存任务。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "retention_action"}, ensure_ascii=False)
                FinanceService.create_audit(
                    db, current_user.id, "agent.retention_action_needs_clarification", "agent_task",
                    str(task.id), {"message": request.message, "action": retention_management_action},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:retention_action", "needs_parameters"],
                    sources=["database:retention_tasks"], trace_id=str(task.id),
                )

            reason = _retention_message_from_manager_request(request.message, None)
            try:
                if retention_management_action == "manual_followup":
                    result = await move_retention_task_to_manual_followup(
                        str(retention_task.id),
                        RetentionManualFollowupRequest(reason=reason or None),
                        current_user,
                        db,
                    )
                elif retention_management_action == "ignore":
                    result = await ignore_retention_task(
                        str(retention_task.id),
                        RetentionIgnoreRequest(
                            mode=_retention_ignore_mode_from_message(request.message),
                            reason=reason or None,
                        ),
                        current_user,
                        db,
                    )
                elif retention_management_action == "reply":
                    if not reason:
                        reply = "请在指令冒号后补充客户回复内容，例如“记录回复：客户下周有空”。"
                        task.status = AgentTaskStatus.COMPLETED
                        task.result_payload = json.dumps({"reply": reply, "intent": "retention_action"}, ensure_ascii=False)
                        db.commit()
                        return StaffAgentQueryResponse(
                            task_id=str(task.id), status=task.status.value, reply=reply,
                            actions=["intent:retention_action", "needs_reply_content"],
                            sources=["database:retention_tasks"], trace_id=str(task.id),
                        )
                    result = await record_retention_reply(
                        str(retention_task.id), RetentionReplyRequest(reply_content=reason), current_user, db
                    )
                else:
                    result = await close_retention_task(
                        str(retention_task.id), RetentionCloseRequest(reason=reason or None), current_user, db
                    )
            except HTTPException as exc:
                db.rollback()
                reply = f"留存任务处理失败：{exc.detail}"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "retention_action"}, ensure_ascii=False)
                FinanceService.create_audit(
                    db, current_user.id, "agent.retention_action_failed", "agent_task", str(task.id),
                    {"message": request.message, "action": retention_management_action, "reason": str(exc.detail)},
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id), status=task.status.value, reply=reply,
                    actions=["intent:retention_action", "tool:retention_task_action"],
                    sources=["database:retention_tasks"], trace_id=str(task.id),
                )

            reply = f"已将{retention_task.customer.name}的留存任务处理为“{result.status}”。"
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps(
                {"reply": reply, "intent": "retention_action", "action": retention_management_action, "retention_task": result.model_dump()},
                ensure_ascii=False,
            )
            FinanceService.create_audit(
                db, current_user.id, "agent.retention_action_completed", "retention_task",
                str(retention_task.id), {"agent_task_id": str(task.id), "action": retention_management_action},
            )
            db.commit()
            return StaffAgentQueryResponse(
                task_id=str(task.id), status=task.status.value, reply=reply,
                actions=["intent:retention_action", "tool:retention_task_action"],
                sources=["database:retention_tasks"], trace_id=str(task.id),
            )

        if retention_send_requested:
            trace = {
                "trace_id": str(task.id),
                "workflow": "manager_action_router",
                "steps": [{
                    "node": "semantic_intent_retrieval",
                    "status": "completed",
                    "intent": "retention_send",
                    "method": intent_match["method"],
                    "score": intent_match["score"],
                }],
            }

            if batch_birthday_requested:
                summary = _send_birthday_retention_tasks(db, current_user)
                failed_names = "、".join(item["customer_name"] for item in summary["failed"])
                reply = (
                    f"生日提醒批量发送完成：共 {summary['total']} 条，"
                    f"成功 {summary['success_count']} 条，失败 {summary['failed_count']} 条。"
                )
                if failed_names:
                    reply += f"失败客户：{failed_names}。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps(
                    {"reply": reply, "intent": "retention_send", "batch": summary, "trace": trace},
                    ensure_ascii=False,
                )
                FinanceService.create_audit(
                    db,
                    current_user.id,
                    "agent.retention_birthday_batch_send_reported",
                    "agent_task",
                    str(task.id),
                    summary,
                )
                db.commit()
                return StaffAgentQueryResponse(
                    task_id=str(task.id),
                    status=task.status.value,
                    reply=reply,
                    actions=["intent:retention_send", "tool:batch_send_birthday_retention"],
                    sources=["database:retention_tasks", "notification:customer"],
                    trace_id=str(task.id),
                    trace=trace,
                )

            retention_task, clarification = _find_sendable_retention_task_from_message(db, message)
            if not retention_task:
                reply = clarification or "没有找到可发送的留存任务。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "retention_send", "trace": trace}, ensure_ascii=False)
                FinanceService.create_audit(db, current_user.id, "agent.retention_send_needs_clarification", "agent_task", str(task.id), {"message": request.message})
                db.commit()
                return StaffAgentQueryResponse(task_id=str(task.id), status=task.status.value, reply=reply, actions=["intent:retention_send", "tool:lookup_retention_task"], sources=["database:retention_tasks"], trace_id=str(task.id), trace=trace)

            actual_message = _retention_message_from_manager_request(request.message, retention_task.suggested_message)
            if not actual_message:
                reply = "该留存任务没有可发送的话术，请在指令中用冒号补充要发送的内容。"
                task.status = AgentTaskStatus.COMPLETED
                task.result_payload = json.dumps({"reply": reply, "intent": "retention_send", "trace": trace}, ensure_ascii=False)
                db.commit()
                return StaffAgentQueryResponse(task_id=str(task.id), status=task.status.value, reply=reply, actions=["intent:retention_send", "needs_message"], sources=["database:retention_tasks"], trace_id=str(task.id), trace=trace)

            retry_only = retention_task.status == RetentionTaskStatus.SEND_FAILED
            proposal = {
                "retention_task_id": str(retention_task.id),
                "customer_name": retention_task.customer.name,
                "customer_phone": retention_task.customer.phone,
                "message": actual_message,
                "retry_only": retry_only,
                "risk_level": "external_contact",
            }
            send_task = AgentTaskState(
                id=uuid.uuid4(), requester_id=current_user.id,
                workflow_type="retention_retry" if retry_only else "retention_send",
                status=AgentTaskStatus.AWAITING_CONFIRMATION,
                input_payload=json.dumps({"retention_task_id": str(retention_task.id), "source_message": request.message}, ensure_ascii=False),
                result_payload=json.dumps(proposal, ensure_ascii=False), awaiting_confirmation=True,
            )
            db.add(send_task)
            task.status = AgentTaskStatus.COMPLETED
            task.result_payload = json.dumps({"intent": "retention_send", "retention_send_task_id": str(send_task.id), "trace": trace}, ensure_ascii=False)
            FinanceService.create_audit(db, current_user.id, "agent.retention_send_proposed", "agent_task", str(send_task.id), {"retention_task_id": str(retention_task.id), "retry_only": retry_only})
            db.commit()
            db.refresh(send_task)
            reply = f"将向{proposal['customer_name']}发送以下留存消息，请确认后发送：\n{actual_message}"
            return StaffAgentQueryResponse(task_id=str(send_task.id), status=send_task.status.value, reply=reply, actions=["intent:retention_send", "tool:propose_retention_send"], sources=["database:retention_tasks"], trace_id=str(task.id), trace=trace, agent_task=_agent_task_response(send_task).model_dump())

        result = langchain_agent.handle_message(
            message=message,
            phone=current_user.phone or "",
            name=current_user.name,
            role="staff",
        )
        # 模型可以决定怎样组织语言，但员工侧的动作、数据来源和 trace 必须来自
        # 受控只读 Graph，保证有模型和无模型两条路径使用同一份可审计协议。
        verified = run_staff_query(
            message,
            requester_id=str(current_user.id),
            allow_financial=current_user.role == UserRole.ADMIN,
        )
        model_markers = [
            action for action in result.get("actions", [])
            if action.startswith("langchain_agent:") or action == "rule_agent_fallback"
        ]
        result["actions"] = list(dict.fromkeys([*model_markers, *verified.get("actions", [])]))
        result["sources"] = verified.get("sources", []) or result.get("sources", [])
        result["intent"] = verified.get("intent", "unknown")
        result["trace_id"] = verified.get("trace_id")
        result["trace"] = verified.get("trace", {})

        # 预约编号是后续改约、核验等动作的真实关联键。模型若只写口语化总结，
        # 用已核验的日程结果补齐，避免员工看到了预约却无法继续操作。
        verified_reply = verified.get("reply", "")
        if "预约ID " in verified_reply and "预约ID " not in result.get("reply", ""):
            result["reply"] = verified_reply
        if verified.get("intent") == "schedule":
            model_dates = re.findall(r"20\d{2}-\d{2}-\d{2}", result.get("reply", ""))
            today = datetime.now().strftime("%Y-%m-%d")
            if model_dates and any(value != today for value in model_dates):
                result["reply"] = verified_reply
        # 会员余额、积分和等级属于结构化数字，统一采用受控 Graph 的格式，
        # 避免模型把 68.00 元改写成 68.0 或遗漏动态会员等级。
        if verified.get("intent") == "membership" and verified_reply:
            result["reply"] = verified_reply
        if result["intent"] == "knowledge":
            source_titles = [
                source.removeprefix("rag:")
                for source in result["sources"]
                if source.startswith("rag:") and source != "rag:none"
            ]
            missing_titles = [title for title in source_titles if title not in result.get("reply", "")]
            if missing_titles:
                result["reply"] = f"{result.get('reply', '')}\n\n检索依据：{'、'.join(missing_titles)}"
        result.setdefault("actions", [])
        result.setdefault("sources", [])
        result.setdefault("trace", {})
        result.setdefault("trace_id", None)
        if not result.get("trace_id"):
            result["trace_id"] = str(task.id)
            result["trace"] = {
                "trace_id": result["trace_id"],
                "workflow": "staff_llm_query",
                "steps": [{"node": "langchain_tool_call", "status": "completed"}],
            }
        task.status = AgentTaskStatus.COMPLETED
        task.result_payload = json.dumps(result, ensure_ascii=False)
        FinanceService.create_audit(
            db,
            current_user.id,
            "agent.staff_query_completed",
            "agent_task",
            str(task.id),
            {"intent": result.get("intent"), "actions": result.get("actions", []), "trace_id": result.get("trace_id")},
        )
        db.commit()
        return StaffAgentQueryResponse(
            task_id=str(task.id),
            status=task.status.value,
            reply=result["reply"],
            actions=result["actions"],
            sources=result["sources"],
            trace_id=result.get("trace_id"),
            trace=result.get("trace", {}),
        )
    except Exception as exc:
        db.rollback()
        task = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).first()
        if task:
            task.status = AgentTaskStatus.FAILED
            task.result_payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
            db.commit()
        logger.exception("Staff readonly agent failed")
        raise HTTPException(status_code=500, detail="员工查询助手暂时不可用")


def _agent_task_response(task: AgentTaskState) -> AgentTaskResponse:
    import json
    return AgentTaskResponse(
        task_id=str(task.id),
        workflow_type=task.workflow_type,
        status=task.status.value,
        awaiting_confirmation=task.awaiting_confirmation,
        input_payload=json.loads(task.input_payload) if task.input_payload else None,
        result_payload=json.loads(task.result_payload) if task.result_payload else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


@router.post("/staff/agent/appointment-change/propose", response_model=AgentTaskResponse)
async def propose_appointment_change(
    request: AppointmentChangeProposalRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import json
    try:
        workflow = run_appointment_change_workflow(
            request.model_dump(), str(current_user.id), db, confirmed=False
        )
    except AppointmentChangeError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    task = AgentTaskState(
        id=uuid.uuid4(),
        requester_id=current_user.id,
        workflow_type="appointment_change",
        status=AgentTaskStatus.AWAITING_CONFIRMATION,
        input_payload=json.dumps(request.model_dump(), ensure_ascii=False),
        result_payload=json.dumps({**workflow["proposal"], "_trace": {"trace_id": workflow.get("trace_id"), "trace": workflow.get("trace", {})}}, ensure_ascii=False),
        awaiting_confirmation=True,
    )
    db.add(task)
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.appointment_change_proposed",
        "agent_task",
        str(task.id),
        {"appointment_id": request.appointment_id, "new_slot_id": request.new_slot_id, "trace_id": workflow.get("trace_id")},
    )
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


def _appointment_approval_proposal(appointment: Appointment) -> dict:
    return {
        "appointment_id": str(appointment.id),
        "customer_id": str(appointment.customer_id),
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "stylist_name": appointment.stylist.user.name,
        "service": appointment.service,
        "appointment_datetime": appointment.appointment_datetime.isoformat(),
        "status": appointment.status.value,
    }


def _create_appointment_approval_task(
    db: Session,
    appointment: Appointment,
    current_user: User,
    source_message: str | None = None,
) -> AgentTaskState:
    proposal = _appointment_approval_proposal(appointment)
    task = AgentTaskState(
        id=uuid.uuid4(),
        requester_id=current_user.id,
        workflow_type="appointment_approval",
        status=AgentTaskStatus.AWAITING_CONFIRMATION,
        input_payload=json.dumps(
            {"appointment_id": str(appointment.id), "source_message": source_message},
            ensure_ascii=False,
        ),
        result_payload=json.dumps(proposal, ensure_ascii=False),
        awaiting_confirmation=True,
    )
    db.add(task)
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.appointment_approval_proposed",
        "agent_task",
        str(task.id),
        {
            "appointment_id": str(appointment.id),
            "customer_id": str(appointment.customer_id),
            "source_message": source_message,
        },
    )
    return task


@router.post("/staff/agent/appointment-approval/propose", response_model=AgentTaskResponse)
async def propose_appointment_approval(
    request: AppointmentApprovalProposalRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        appointment_id = uuid.UUID(request.appointment_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="预约 ID 格式不正确") from exc

    appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="预约不存在")
    if appointment.status != AppointmentStatus.PENDING:
        raise HTTPException(status_code=409, detail="只有待确认预约可以批复")

    task = _create_appointment_approval_task(db, appointment, current_user)
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


@router.post("/staff/appointments/{appointment_id}/approve", response_model=dict)
async def approve_staff_appointment(
    appointment_id: str,
    _: User = Depends(require_admin),
):
    raise HTTPException(
        status_code=410,
        detail="预约批复必须先生成 Agent 任务，再由店长确认",
    )


def _refund_decision_proposal(refund: RefundRequest, decision: str) -> dict:
    return {
        "refund_id": str(refund.id),
        "customer_id": str(refund.user_id),
        "customer_name": refund.user.name,
        "customer_phone": refund.user.phone,
        "amount": cents_to_amount(refund.amount_cents),
        "reason": refund.reason,
        "status": refund.status.value,
        "decision": decision,
        "risk_level": "high",
    }


def _create_refund_decision_task(
    db: Session,
    refund: RefundRequest,
    decision: str,
    current_user: User,
    source_message: str | None = None,
) -> AgentTaskState:
    proposal = _refund_decision_proposal(refund, decision)
    task = AgentTaskState(
        id=uuid.uuid4(),
        requester_id=current_user.id,
        workflow_type=f"refund_{decision}",
        status=AgentTaskStatus.AWAITING_CONFIRMATION,
        input_payload=json.dumps(
            {"refund_id": str(refund.id), "decision": decision, "source_message": source_message},
            ensure_ascii=False,
        ),
        result_payload=json.dumps(proposal, ensure_ascii=False),
        awaiting_confirmation=True,
    )
    db.add(task)
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.refund_decision_proposed",
        "agent_task",
        str(task.id),
        {"refund_id": str(refund.id), "decision": decision, "source_message": source_message},
    )
    return task


@router.post("/staff/agent/refund-decision/propose", response_model=AgentTaskResponse)
async def propose_refund_decision(
    request: RefundDecisionProposalRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        refund_id = uuid.UUID(request.refund_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="退款 ID 格式不正确") from exc
    refund = db.query(RefundRequest).filter(RefundRequest.id == refund_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="退款申请不存在")
    if refund.status != RefundStatus.PENDING:
        raise HTTPException(status_code=409, detail="退款申请已处理")
    task = _create_refund_decision_task(db, refund, request.decision, current_user)
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


@router.get("/staff/agent/tasks/{task_id}", response_model=AgentTaskResponse)
async def get_staff_agent_task(
    task_id: str,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    task = db.query(AgentTaskState).filter(
        AgentTaskState.id == task_uuid,
        AgentTaskState.requester_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent 任务不存在")
    if task.workflow_type != "staff_readonly_query" and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="没有执行该操作的权限")
    return _agent_task_response(task)


def _confirm_appointment_approval_task(
    task: AgentTaskState,
    confirmed: bool,
    current_user: User,
    db: Session,
) -> AgentTaskResponse:
    proposal = json.loads(task.result_payload or "{}")
    appointment_id = proposal.get("appointment_id")
    if not confirmed:
        task.status = AgentTaskStatus.COMPLETED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "confirmed": False,
            "message": "店长拒绝了预约批复",
            "proposal": proposal,
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db,
            current_user.id,
            "agent.appointment_approval_rejected",
            "appointment",
            appointment_id or str(task.id),
            {"task_id": str(task.id)},
        )
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)

    try:
        appointment_uuid = uuid.UUID(appointment_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="预约批复任务数据无效") from exc

    updated = db.query(Appointment).filter(
        Appointment.id == appointment_uuid,
        Appointment.status == AppointmentStatus.PENDING,
    ).update({Appointment.status: AppointmentStatus.CONFIRMED}, synchronize_session=False)
    if updated != 1:
        task.status = AgentTaskStatus.FAILED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "error": "预约状态已变化，不能重复批复",
            "proposal": proposal,
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db,
            current_user.id,
            "agent.appointment_approval_failed",
            "appointment",
            appointment_id,
            {"task_id": str(task.id), "reason": "appointment_not_pending"},
        )
        db.commit()
        raise HTTPException(status_code=409, detail="预约状态已变化，不能重复批复")

    appointment = db.query(Appointment).filter(Appointment.id == appointment_uuid).one()
    FinanceService.create_notification(
        db,
        appointment.customer_id,
        NotificationKind.APPOINTMENT,
        "预约已确认",
        f"您的{appointment.service}预约已确认：{appointment.appointment_datetime:%Y-%m-%d %H:%M}，"
        f"{appointment.stylist.user.name}老师。",
    )
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.appointment_approved",
        "appointment",
        str(appointment.id),
        {"task_id": str(task.id), "from_status": "pending", "to_status": "confirmed"},
    )
    task.status = AgentTaskStatus.COMPLETED
    task.awaiting_confirmation = False
    task.result_payload = json.dumps({
        "confirmed": True,
        "message": "预约已确认，并已通知客户",
        "appointment_id": str(appointment.id),
        "status": appointment.status.value,
        "proposal": proposal,
    }, ensure_ascii=False)
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


def _confirm_refund_decision_task(
    task: AgentTaskState,
    confirmed: bool,
    manager_password: str | None,
    current_user: User,
    db: Session,
) -> AgentTaskResponse:
    proposal = json.loads(task.result_payload or "{}")
    refund_id = proposal.get("refund_id")
    decision = proposal.get("decision")
    if not confirmed:
        task.status = AgentTaskStatus.COMPLETED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "confirmed": False,
            "message": "店长取消了退款处理",
            "proposal": proposal,
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db, current_user.id, "agent.refund_decision_rejected", "refund_request",
            refund_id or str(task.id), {"task_id": str(task.id), "decision": decision},
        )
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)

    if not manager_password or not verify_password(manager_password, current_user.password_hash):
        FinanceService.create_audit(
            db, current_user.id, "security.step_up_denied", "refund_request",
            refund_id or str(task.id), {"task_id": str(task.id), "decision": decision},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="店长密码验证失败")

    try:
        if decision == "approve":
            refund, wallet, _ = FinanceService.approve_refund(
                db, refund_id, current_user, commit=False
            )
            result = {"status": refund.status.value, "balance": cents_to_amount(wallet.balance_cents)}
        elif decision == "reject":
            refund = FinanceService.reject_refund(db, refund_id, current_user, commit=False)
            result = {"status": refund.status.value}
        else:
            raise FinanceError("退款任务决策无效")
    except FinanceError as exc:
        db.rollback()
        failed_task = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).first()
        if failed_task:
            failed_task.status = AgentTaskStatus.FAILED
            failed_task.awaiting_confirmation = False
            failed_task.result_payload = json.dumps({"error": str(exc), "proposal": proposal}, ensure_ascii=False)
            FinanceService.create_audit(
                db, current_user.id, "agent.refund_decision_failed", "refund_request",
                refund_id or str(task.id), {"task_id": str(task.id), "reason": str(exc)},
            )
            db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    FinanceService.create_audit(
        db, current_user.id, "agent.refund_decision_confirmed", "refund_request",
        refund_id, {"task_id": str(task.id), "decision": decision},
    )
    task.status = AgentTaskStatus.COMPLETED
    task.awaiting_confirmation = False
    task.result_payload = json.dumps({
        "confirmed": True,
        "message": "退款处理已完成，并已通知客户",
        "proposal": proposal,
        **result,
    }, ensure_ascii=False)
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


def _confirm_service_completion_task(
    task: AgentTaskState,
    confirmed: bool,
    current_user: User,
    db: Session,
) -> AgentTaskResponse:
    proposal = json.loads(task.result_payload or "{}")
    verification_id = proposal.get("verification_id")
    if not confirmed:
        task.status = AgentTaskStatus.COMPLETED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "confirmed": False,
            "message": "店长取消了服务完成操作",
            "proposal": proposal,
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db, current_user.id, "agent.service_completion_rejected", "service_verification",
            verification_id or str(task.id), {"task_id": str(task.id)},
        )
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)

    try:
        verification = _complete_service_verification(verification_id, current_user, db)
    except HTTPException as exc:
        db.rollback()
        failed_task = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).first()
        if failed_task:
            failed_task.status = AgentTaskStatus.FAILED
            failed_task.awaiting_confirmation = False
            failed_task.result_payload = json.dumps({"error": exc.detail, "proposal": proposal}, ensure_ascii=False)
            FinanceService.create_audit(
                db, current_user.id, "agent.service_completion_failed", "service_verification",
                verification_id or str(task.id), {"task_id": str(task.id), "reason": exc.detail},
            )
            db.commit()
        raise

    task.status = AgentTaskStatus.COMPLETED
    task.awaiting_confirmation = False
    task.result_payload = json.dumps({
        "confirmed": True,
        "message": "服务已完成，消费、积分和绩效已同步更新",
        "proposal": proposal,
        "status": verification.status.value,
    }, ensure_ascii=False)
    FinanceService.create_audit(
        db, current_user.id, "agent.service_completion_confirmed", "service_verification",
        str(verification.id), {"task_id": str(task.id)},
    )
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


def _confirm_retention_send_task(
    task: AgentTaskState,
    confirmed: bool,
    current_user: User,
    db: Session,
) -> AgentTaskResponse:
    proposal = json.loads(task.result_payload or "{}")
    retention_task_id = proposal.get("retention_task_id")
    if not confirmed:
        task.status = AgentTaskStatus.COMPLETED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "confirmed": False,
            "message": "店长取消了留存消息发送",
            "proposal": proposal,
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db, current_user.id, "agent.retention_send_rejected", "retention_task",
            retention_task_id or str(task.id), {"task_id": str(task.id)},
        )
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)

    try:
        result = _send_retention_task(
            db,
            retention_task_id,
            current_user,
            RetentionSendRequest(message=proposal.get("message", "")),
            retry_only=bool(proposal.get("retry_only")),
            commit=False,
        )
    except HTTPException as exc:
        db.rollback()
        failed_task = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).first()
        if failed_task:
            failed_task.status = AgentTaskStatus.FAILED
            failed_task.awaiting_confirmation = False
            failed_task.result_payload = json.dumps({"error": exc.detail, "proposal": proposal}, ensure_ascii=False)
            FinanceService.create_audit(
                db, current_user.id, "agent.retention_send_failed", "retention_task",
                retention_task_id or str(task.id), {"task_id": str(task.id), "reason": exc.detail},
            )
            db.commit()
        raise

    task.status = AgentTaskStatus.COMPLETED
    task.awaiting_confirmation = False
    task.result_payload = json.dumps({
        "confirmed": True,
        "message": "留存消息已发送并同步到客户通知",
        "proposal": proposal,
        "status": result.status,
        "next_contact_at": result.next_contact_at,
    }, ensure_ascii=False)
    FinanceService.create_audit(
        db, current_user.id, "agent.retention_send_confirmed", "retention_task",
        retention_task_id, {"task_id": str(task.id), "status": result.status},
    )
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


@router.post("/staff/agent/tasks/{task_id}/confirm", response_model=AgentTaskResponse)
async def confirm_staff_agent_task(
    task_id: str,
    request: AgentConfirmationRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import json
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent 任务不存在") from exc
    task = db.query(AgentTaskState).filter(
        AgentTaskState.id == task_uuid,
        AgentTaskState.requester_id == current_user.id,
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent 任务不存在")
    if not task.awaiting_confirmation or task.status != AgentTaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="该任务已经处理，不能重复确认")
    if task.workflow_type == "appointment_approval":
        return _confirm_appointment_approval_task(task, request.confirmed, current_user, db)
    if task.workflow_type in {"refund_approve", "refund_reject"}:
        return _confirm_refund_decision_task(
            task, request.confirmed, request.manager_password, current_user, db
        )
    if task.workflow_type == "service_completion":
        return _confirm_service_completion_task(
            task, request.confirmed, current_user, db
        )
    if task.workflow_type in {"retention_send", "retention_retry"}:
        return _confirm_retention_send_task(task, request.confirmed, current_user, db)
    if task.workflow_type != "appointment_change":
        raise HTTPException(status_code=404, detail="该 Agent 任务不支持确认")
    stored_payload = json.loads(task.result_payload or "{}")
    proposal = {key: value for key, value in stored_payload.items() if key != "_trace"}
    if not request.confirmed:
        task.status = AgentTaskStatus.COMPLETED
        task.awaiting_confirmation = False
        task.result_payload = json.dumps({
            "confirmed": False,
            "message": "员工拒绝了预约调整方案",
            "proposal": proposal,
            "_trace": stored_payload.get("_trace", {}),
        }, ensure_ascii=False)
        FinanceService.create_audit(
            db,
            current_user.id,
            "agent.appointment_change_rejected",
            "agent_task",
            str(task.id),
            {"appointment_id": proposal.get("appointment_id")},
        )
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)
    try:
        workflow = run_appointment_change_workflow(
            json.loads(task.input_payload or "{}"), str(current_user.id), db, confirmed=True, proposal=proposal
        )
    except AppointmentChangeError as exc:
        db.rollback()
        task = db.query(AgentTaskState).filter(AgentTaskState.id == task_uuid).first()
        if task:
            task.status = AgentTaskStatus.FAILED
            task.awaiting_confirmation = False
            task.result_payload = json.dumps({"error": str(exc), "proposal": proposal}, ensure_ascii=False)
            db.commit()
        raise HTTPException(status_code=409, detail=str(exc))
    task.status = AgentTaskStatus.COMPLETED
    task.awaiting_confirmation = False
    task.result_payload = json.dumps({
        **workflow["result"],
        "_trace": {
            "trace_id": workflow.get("trace_id"),
            "trace": workflow.get("trace", {}),
            "parent_trace": stored_payload.get("_trace", {}).get("trace", {}),
        },
    }, ensure_ascii=False)
    FinanceService.create_audit(
        db,
        current_user.id,
        "agent.appointment_change_confirmed",
        "agent_task",
        str(task.id),
        {"appointment_id": workflow["result"].get("appointment_id"), "trace_id": workflow.get("trace_id")},
    )
    db.commit()
    db.refresh(task)
    return _agent_task_response(task)


# ===== 发型师 =====

@router.get("/stylists", response_model=list[StylistResponse])
async def get_stylists(
    specialty: str = Query(None),
    db: Session = Depends(get_db),
):
    if specialty:
        stylists = StylistService.search_stylists_by_specialty(db, specialty)
    else:
        stylists = StylistService.get_all_stylists(db)
    return [
        StylistResponse(
            stylist_id=str(s.id),
            name=s.user.name,
            phone=s.user.phone,
            specialty=s.specialty,
            experience_years=s.experience_years,
            rating=s.rating,
            bio=s.bio,
            is_available=s.is_available,
        )
        for s in stylists
    ]


@router.get("/stylists/{stylist_id}/slots", response_model=list[TimeSlotResponse])
async def get_stylist_slots(
    stylist_id: str,
    days_ahead: int = Query(7),
    db: Session = Depends(get_db),
):
    slots = TimeSlotService.get_available_slots(db, stylist_id, days_ahead=days_ahead)
    return slots


# ===== 预约 =====

@router.post("/appointments", response_model=dict)
async def create_appointment(
    request: AppointmentCreate,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if not current_user.phone:
        raise HTTPException(status_code=409, detail="请先绑定手机号后再预约")
    if request.phone and request.phone != current_user.phone:
        raise HTTPException(status_code=400, detail="预约手机号必须与当前登录用户一致")
    result = client_appointment_service.book_appointment(
        customer_phone=current_user.phone,
        customer_name=current_user.name,
        stylist_id=request.stylist_id,
        slot_id=request.slot_id,
        service=request.service,
        notes=request.notes,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "预约失败"))
    return result


@router.post("/staff/appointments", response_model=StaffBookingResponse, status_code=201)
async def create_staff_appointment(
    request: StaffAppointmentCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """员工为已有客户代约；与客户端共用同一时间槽和预约写入逻辑。"""
    try:
        customer_id = uuid.UUID(request.customer_id)
        stylist_id = uuid.UUID(request.stylist_id)
        slot_id = uuid.UUID(request.slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="客户、发型师或时间槽 ID 格式不正确") from exc

    service = request.service.strip()
    if not service:
        raise HTTPException(status_code=422, detail="服务项目不能为空")

    customer = db.query(User).filter(
        User.id == customer_id,
        User.role == UserRole.CUSTOMER,
    ).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在，只能为已有客户代约")

    stylist = db.query(Stylist).filter(
        Stylist.id == stylist_id,
        Stylist.is_available.is_(True),
    ).first()
    if not stylist:
        raise HTTPException(status_code=404, detail="发型师不存在或当前不可预约")

    slot = db.query(StylistTimeSlot).filter(
        StylistTimeSlot.id == slot_id,
        StylistTimeSlot.stylist_id == stylist_id,
    ).first()
    if not slot:
        raise HTTPException(status_code=404, detail="时间槽不存在或不属于该发型师")
    if slot.is_booked:
        raise HTTPException(status_code=409, detail="该时间槽刚刚被其他预约占用，请重新选择")

    appointment = AppointmentService.create_appointment(
        db,
        customer_id=str(customer.id),
        stylist_id=str(stylist.id),
        slot_id=str(slot.id),
        service=service,
        notes=request.notes,
        status=AppointmentStatus.CONFIRMED,
        commit=False,
    )
    if not appointment:
        raise HTTPException(status_code=409, detail="该时间槽刚刚被其他预约占用，请重新选择")

    body = (
        f"门店已为您预约：{service}，{appointment.appointment_datetime:%Y-%m-%d %H:%M}，"
        f"{stylist.user.name}老师。"
    )
    FinanceService.create_notification(
        db,
        customer.id,
        NotificationKind.APPOINTMENT,
        "预约已创建",
        body,
    )
    FinanceService.create_audit(
        db,
        current_user.id,
        "appointment.staff_created",
        "appointment",
        str(appointment.id),
        {
            "customer_id": str(customer.id),
            "stylist_id": str(stylist.id),
            "slot_id": str(slot.id),
            "service": service,
        },
    )
    db.commit()
    return StaffBookingResponse(
        appointment_id=str(appointment.id),
        customer_id=str(customer.id),
        customer_name=customer.name,
        customer_phone=customer.phone,
        stylist_id=str(stylist.id),
        stylist_name=stylist.user.name,
        service=appointment.service,
        appointment_datetime=appointment.appointment_datetime.isoformat(),
        status=appointment.status.value,
        notes=appointment.notes,
    )


@router.get("/appointments", response_model=list[AppointmentResponse])
async def get_appointments(
    phone: str | None = Query(None),
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if phone and phone != current_user.phone:
        raise HTTPException(status_code=404, detail="预约不存在")
    appointments = client_appointment_service.get_customer_appointments(current_user.phone)
    return appointments


@router.delete("/appointments/{appointment_id}", response_model=dict)
async def cancel_appointment(
    appointment_id: str,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    try:
        appointment_uuid = uuid.UUID(appointment_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="预约不存在")

    owned_appointment = db.query(Appointment).filter(
        Appointment.id == appointment_uuid,
        Appointment.customer_id == current_user.id,
    ).first()
    if not owned_appointment:
        raise HTTPException(status_code=404, detail="预约不存在")

    success = AppointmentService.cancel_appointment(db, appointment_id)
    if not success:
        raise HTTPException(status_code=409, detail="当前预约状态不能取消")
    return {"success": True, "message": "预约已取消"}


# ===== 会员与营销 =====

@router.get("/customers", response_model=list[CustomerResponse])
async def get_customers(
    db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    can_view_finance = _.role == UserRole.ADMIN
    customers = UserService.get_all_customers(db)
    return [
        CustomerResponse(
            customer_id=str(customer.id),
            name=customer.name,
            phone=customer.phone,
            birthday=customer.birthday,
            total_spent=(customer.total_spent or 0) if can_view_finance else None,
            last_visit=customer.last_visit.isoformat() if customer.last_visit else None,
        )
        for customer in customers
    ]


def _staff_date_window(date_value: str | None):
    try:
        target_date = datetime.strptime(date_value, "%Y-%m-%d").date() if date_value else datetime.now().date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式必须是 YYYY-MM-DD") from exc
    start = datetime.combine(target_date, datetime.min.time())
    return target_date, start, start + timedelta(days=1)


def _staff_service_breakdown(transactions: list[Transaction]) -> list[StaffServiceBreakdownResponse]:
    grouped: dict[str, dict] = {}
    for transaction in transactions:
        service = transaction.service or "未命名服务"
        item = grouped.setdefault(service, {"customers": set(), "orders": 0, "amount_cents": 0})
        item["customers"].add(str(transaction.user_id))
        item["orders"] += 1
        item["amount_cents"] += amount_to_cents(transaction.amount)

    return [
        StaffServiceBreakdownResponse(
            service=service,
            customer_count=len(item["customers"]),
            order_count=item["orders"],
            amount_cents=item["amount_cents"],
            amount=cents_to_amount(item["amount_cents"]),
        )
        for service, item in sorted(
            grouped.items(), key=lambda entry: (-entry[1]["amount_cents"], entry[0])
        )
    ]


def _staff_performance(
    transactions: list[Transaction], stylists: list[Stylist] | None = None
) -> list[StaffPerformanceResponse]:
    grouped: dict[str, dict] = {}
    for stylist in stylists or []:
        grouped[str(stylist.id)] = {
            "stylist_id": str(stylist.id),
            "stylist_name": stylist.user.name,
            "stylist_phone": stylist.user.phone,
            "customers": set(),
            "orders": 0,
            "amount_cents": 0,
            "services": {},
            "records": [],
        }
    for transaction in transactions:
        appointment = transaction.appointment
        stylist = appointment.stylist if appointment else None
        stylist_id = str(stylist.id) if stylist else None
        group_key = stylist_id or "unassigned"
        item = grouped.setdefault(
            group_key,
            {
                "stylist_id": stylist_id,
                "stylist_name": stylist.user.name if stylist else "未关联发型师",
                "stylist_phone": stylist.user.phone if stylist else None,
                "customers": set(),
                "orders": 0,
                "amount_cents": 0,
                "services": {},
                "records": [],
            },
        )
        amount_cents = amount_to_cents(transaction.amount)
        item["customers"].add(str(transaction.user_id))
        item["orders"] += 1
        item["amount_cents"] += amount_cents

        service = transaction.service or "未命名服务"
        service_item = item["services"].setdefault(service, {"customers": set(), "orders": 0, "amount_cents": 0})
        service_item["customers"].add(str(transaction.user_id))
        service_item["orders"] += 1
        service_item["amount_cents"] += amount_cents

        item["records"].append(
            StaffPerformanceCustomerResponse(
                appointment_id=str(appointment.id) if appointment else None,
                customer_name=transaction.user.name,
                customer_phone=transaction.user.phone,
                service=transaction.service or "未命名服务",
                amount_cents=amount_cents,
                amount=cents_to_amount(amount_cents),
                status=appointment.status.value if appointment else "unlinked",
                created_at=transaction.created_at.isoformat(),
            )
        )

    result = []
    for item in grouped.values():
        services = [
            StaffServiceBreakdownResponse(
                service=service,
                customer_count=len(service_item["customers"]),
                order_count=service_item["orders"],
                amount_cents=service_item["amount_cents"],
                amount=cents_to_amount(service_item["amount_cents"]),
            )
            for service, service_item in sorted(
                item["services"].items(),
                key=lambda entry: (-entry[1]["amount_cents"], entry[0]),
            )
        ]
        item["records"].sort(key=lambda record: record.created_at, reverse=True)
        result.append(
            StaffPerformanceResponse(
                stylist_id=item["stylist_id"],
                stylist_name=item["stylist_name"],
                stylist_phone=item["stylist_phone"],
                customer_count=len(item["customers"]),
                order_count=item["orders"],
                amount_cents=item["amount_cents"],
                amount=cents_to_amount(item["amount_cents"]),
                services=services,
                customers=item["records"],
            )
        )
    return sorted(result, key=lambda item: (-item.amount_cents, item.stylist_name))


@router.get("/staff/customer-wallets", response_model=list[StaffCustomerWalletResponse])
async def get_staff_customer_wallets(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    customers = UserService.get_all_customers(db)
    result = []
    for customer in customers:
        wallet = db.query(WalletAccount).filter(WalletAccount.user_id == customer.id).first()
        wallet_transactions = []
        if wallet:
            wallet_transactions = db.query(WalletTransaction).filter(
                WalletTransaction.wallet_id == wallet.id
            ).order_by(WalletTransaction.created_at.desc()).limit(50).all()

        recharge_transactions = db.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.direction == WalletDirection.CREDIT,
            WalletTransaction.transaction_type == WalletTransactionType.RECHARGE,
        ).order_by(WalletTransaction.created_at.desc()).all() if wallet else []
        recharge_total_cents = sum(item.amount_cents for item in recharge_transactions)
        last_recharge_at = max(
            (item.created_at for item in recharge_transactions), default=None
        )
        balance_cents = wallet.balance_cents if wallet else 0
        result.append(
            StaffCustomerWalletResponse(
                customer_id=str(customer.id),
                name=customer.name,
                phone=customer.phone,
                balance_cents=balance_cents,
                balance=cents_to_amount(balance_cents),
                recharge_total_cents=recharge_total_cents,
                recharge_total=cents_to_amount(recharge_total_cents),
                recharge_count=len(recharge_transactions),
                last_recharge_at=last_recharge_at.isoformat() if last_recharge_at else None,
                transactions=[_wallet_transaction_response(item) for item in wallet_transactions],
            )
        )
    return result


def _package_status(package: CustomerPackage, now: datetime | None = None) -> CustomerPackageStatus:
    now = now or datetime.now()
    if package.status == CustomerPackageStatus.CANCELLED:
        return package.status
    if package.remaining_uses <= 0:
        return CustomerPackageStatus.EXHAUSTED
    if package.expires_at <= now:
        return CustomerPackageStatus.EXPIRED
    return CustomerPackageStatus.ACTIVE


def _customer_package_response(package: CustomerPackage) -> CustomerPackageResponse:
    return CustomerPackageResponse(
        customer_package_id=str(package.id),
        customer_id=str(package.customer_id),
        customer_name=package.customer.name,
        customer_phone=package.customer.phone,
        package_id=str(package.package_id),
        package_name=package.package.name,
        service=package.package.service,
        purchase_price=package.purchase_price,
        total_uses=package.total_uses,
        remaining_uses=package.remaining_uses,
        status=_package_status(package).value,
        purchased_at=package.purchased_at.isoformat(),
        expires_at=package.expires_at.isoformat(),
    )


def _service_verification_response(verification: ServiceVerification) -> ServiceVerificationResponse:
    return ServiceVerificationResponse(
        verification_id=str(verification.id),
        appointment_id=str(verification.appointment_id),
        customer_id=str(verification.customer_id),
        customer_name=verification.customer.name,
        customer_phone=verification.customer.phone,
        stylist_id=str(verification.stylist_id),
        stylist_name=verification.stylist.user.name,
        service=verification.service,
        amount=verification.amount,
        status=verification.status.value,
        customer_package_id=str(verification.customer_package_id) if verification.customer_package_id else None,
        package_name=verification.customer_package.package.name if verification.customer_package else None,
        remaining_uses=verification.customer_package.remaining_uses if verification.customer_package else None,
        verified_at=verification.verified_at.isoformat(),
        completed_at=verification.completed_at.isoformat() if verification.completed_at else None,
    )


def _parse_uuid(value: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail=message) from exc


@router.get("/staff/service-packages", response_model=list[ServicePackageResponse])
async def get_staff_service_packages(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    packages = db.query(ServicePackage).filter(ServicePackage.is_active.is_(True)).order_by(ServicePackage.name).all()
    return [
        ServicePackageResponse(
            package_id=str(package.id),
            name=package.name,
            service=package.service,
            price=package.price,
            total_uses=package.total_uses,
            validity_days=package.validity_days,
            is_active=package.is_active,
        )
        for package in packages
    ]


@router.post("/staff/service-packages", response_model=ServicePackageResponse, status_code=201)
async def create_staff_service_package(
    request: ServicePackageCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    package = ServicePackage(
        id=uuid.uuid4(),
        name=request.name,
        service=request.service,
        price=request.price,
        total_uses=request.total_uses,
        validity_days=request.validity_days,
        is_active=True,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return ServicePackageResponse(
        package_id=str(package.id),
        name=package.name,
        service=package.service,
        price=package.price,
        total_uses=package.total_uses,
        validity_days=package.validity_days,
        is_active=package.is_active,
    )


@router.get("/staff/customer-packages", response_model=list[CustomerPackageResponse])
async def get_staff_customer_packages(
    customer_id: str | None = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(CustomerPackage).order_by(CustomerPackage.expires_at.asc())
    if customer_id:
        query = query.filter(CustomerPackage.customer_id == _parse_uuid(customer_id, "客户 ID 格式不正确"))
    return [_customer_package_response(package) for package in query.all()]


@router.post("/staff/customer-packages", response_model=CustomerPackageResponse, status_code=201)
async def assign_staff_customer_package(
    request: CustomerPackageAssignRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    customer_id = _parse_uuid(request.customer_id, "客户 ID 格式不正确")
    package_id = _parse_uuid(request.package_id, "套餐 ID 格式不正确")
    customer = db.query(User).filter(User.id == customer_id, User.role == UserRole.CUSTOMER).first()
    package = db.query(ServicePackage).filter(ServicePackage.id == package_id, ServicePackage.is_active.is_(True)).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在")
    if not package:
        raise HTTPException(status_code=404, detail="套餐不存在或已停用")

    purchased_at = datetime.now()
    customer_package = CustomerPackage(
        id=uuid.uuid4(),
        customer_id=customer.id,
        package_id=package.id,
        purchase_price=package.price,
        total_uses=package.total_uses,
        remaining_uses=package.total_uses,
        status=CustomerPackageStatus.ACTIVE,
        purchased_at=purchased_at,
        expires_at=purchased_at + timedelta(days=package.validity_days),
    )
    db.add(customer_package)
    FinanceService.create_audit(
        db, current_user.id, "service_package.assign", "customer_package", str(customer_package.id),
        {"customer_id": str(customer.id), "package_id": str(package.id)},
    )
    db.commit()
    db.refresh(customer_package)
    return _customer_package_response(customer_package)


def _appointment_for_verification(appointment_id: str, db: Session) -> Appointment:
    appointment = db.query(Appointment).filter(
        Appointment.id == _parse_uuid(appointment_id, "预约 ID 格式不正确")
    ).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="预约不存在")
    return appointment


def _eligible_customer_packages(appointment: Appointment, db: Session) -> list[CustomerPackage]:
    packages = db.query(CustomerPackage).join(ServicePackage).filter(
        CustomerPackage.customer_id == appointment.customer_id,
        ServicePackage.is_active.is_(True),
    ).order_by(CustomerPackage.expires_at.asc()).all()
    return [
        package for package in packages
        if _package_status(package) == CustomerPackageStatus.ACTIVE
        and package.package.service in {appointment.service, "通用服务"}
    ]


@router.get(
    "/staff/appointments/{appointment_id}/verification",
    response_model=ServiceVerificationOptionsResponse,
)
async def get_service_verification_options(
    appointment_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    appointment = _appointment_for_verification(appointment_id, db)
    verification = db.query(ServiceVerification).filter(
        ServiceVerification.appointment_id == appointment.id
    ).first()
    return ServiceVerificationOptionsResponse(
        appointment_id=str(appointment.id),
        customer_id=str(appointment.customer_id),
        customer_name=appointment.customer.name,
        customer_phone=appointment.customer.phone,
        stylist_id=str(appointment.stylist_id),
        stylist_name=appointment.stylist.user.name,
        service=appointment.service,
        appointment_datetime=appointment.appointment_datetime.isoformat(),
        appointment_status=appointment.status.value,
        packages=[_customer_package_response(package) for package in _eligible_customer_packages(appointment, db)],
        verification=_service_verification_response(verification) if verification else None,
    )


@router.post(
    "/staff/appointments/{appointment_id}/verify",
    response_model=ServiceVerificationResponse,
    status_code=201,
)
async def verify_appointment_service(
    appointment_id: str,
    request: ServiceVerificationCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    appointment = _appointment_for_verification(appointment_id, db)
    if appointment.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="已取消的预约不能核验服务")
    existing = db.query(ServiceVerification).filter(ServiceVerification.appointment_id == appointment.id).first()
    if existing:
        return _service_verification_response(existing)

    customer_package = None
    if request.customer_package_id:
        package_id = _parse_uuid(request.customer_package_id, "客户套餐 ID 格式不正确")
        customer_package = db.query(CustomerPackage).join(ServicePackage).filter(
            CustomerPackage.id == package_id,
            CustomerPackage.customer_id == appointment.customer_id,
            ServicePackage.is_active.is_(True),
        ).first()
        if not customer_package:
            raise HTTPException(status_code=404, detail="客户套餐不存在")
        status = _package_status(customer_package)
        if status != CustomerPackageStatus.ACTIVE:
            raise HTTPException(status_code=409, detail=f"套餐当前状态为 {status.value}，不能核验")
        if customer_package.package.service not in {appointment.service, "通用服务"}:
            raise HTTPException(status_code=409, detail="套餐服务项目与预约项目不匹配")
        amount = round(customer_package.purchase_price / customer_package.total_uses, 2)
    else:
        if request.amount is None or request.amount <= 0:
            raise HTTPException(status_code=422, detail="非套餐服务必须填写大于 0 的消费金额")
        amount = round(request.amount, 2)

    verification = ServiceVerification(
        id=uuid.uuid4(),
        appointment_id=appointment.id,
        customer_id=appointment.customer_id,
        stylist_id=appointment.stylist_id,
        customer_package_id=customer_package.id if customer_package else None,
        service=appointment.service,
        amount=amount,
        status=ServiceVerificationStatus.VERIFIED,
        verified_by=current_user.id,
        verified_at=datetime.now(),
    )
    db.add(verification)
    db.commit()
    db.refresh(verification)
    return _service_verification_response(verification)


def _complete_service_verification(
    verification_id: str,
    current_user: User,
    db: Session,
) -> ServiceVerification:
    verification = db.query(ServiceVerification).filter(
        ServiceVerification.id == _parse_uuid(verification_id, "核验记录 ID 格式不正确")
    ).with_for_update().first()
    if not verification:
        raise HTTPException(status_code=404, detail="核验记录不存在")
    if verification.status == ServiceVerificationStatus.COMPLETED:
        return verification
    if verification.status != ServiceVerificationStatus.VERIFIED:
        raise HTTPException(status_code=409, detail="当前核验记录不能完成服务")
    if verification.appointment.transaction:
        raise HTTPException(status_code=409, detail="该预约已经存在消费记录，不能重复完成")

    if verification.customer_package:
        package = verification.customer_package
        status = _package_status(package)
        if status != CustomerPackageStatus.ACTIVE:
            raise HTTPException(status_code=409, detail=f"套餐当前状态为 {status.value}，不能扣次")
        package.remaining_uses -= 1
        package.status = _package_status(package)
    else:
        try:
            FinanceService.purchase(
                db,
                verification.customer,
                verification.amount,
                note=f"{verification.service} 服务消费",
                reference_type="service_verification",
                reference_id=str(verification.id),
                commit=False,
            )
        except FinanceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    verification.status = ServiceVerificationStatus.COMPLETED
    verification.completed_at = datetime.now()
    appointment = verification.appointment
    appointment.status = AppointmentStatus.COMPLETED
    customer = verification.customer
    customer.total_spent = (customer.total_spent or 0) + verification.amount
    customer.last_visit = datetime.now()

    transaction = Transaction(
        id=uuid.uuid4(),
        user_id=customer.id,
        appointment_id=appointment.id,
        amount=verification.amount,
        service=verification.service,
        created_at=datetime.now(),
    )
    db.add(transaction)

    member = db.query(Member).filter(Member.user_id == customer.id).first()
    points_added = int(verification.amount)
    if member:
        member.points += points_added
        db.add(PointTransaction(
            id=uuid.uuid4(),
            user_id=customer.id,
            amount=points_added,
            balance_after=member.points,
            reason=f"{verification.service}服务核销积分",
            source_type="service_verification",
            source_id=str(verification.id),
        ))
    FinanceService.create_audit(
        db, current_user.id, "service_verification.complete", "service_verification", str(verification.id),
        {
            "appointment_id": str(appointment.id),
            "stylist_id": str(verification.stylist_id),
            "customer_package_id": str(verification.customer_package_id) if verification.customer_package_id else None,
            "amount": verification.amount,
        },
    )
    return verification


@router.post(
    "/staff/service-verifications/{verification_id}/complete",
    response_model=ServiceVerificationResponse,
)
async def complete_service_verification(
    verification_id: str,
    request: ServiceCompletionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        verification = _complete_service_verification(verification_id, current_user, db)
    except HTTPException:
        db.rollback()
        raise
    db.commit()
    db.refresh(verification)
    return _service_verification_response(verification)


@router.get("/staff/overview", response_model=StaffOverviewResponse)
async def get_staff_overview(
    date: str | None = Query(None),
    _: User = Depends(require_admin), db: Session = Depends(get_db),
):
    target_date, start, end = _staff_date_window(date)
    consumption_transactions = db.query(Transaction).filter(
        Transaction.created_at >= start,
        Transaction.created_at < end,
    ).order_by(Transaction.created_at.desc()).all()
    wallet_transactions = db.query(WalletTransaction).filter(
        WalletTransaction.created_at >= start,
        WalletTransaction.created_at < end,
    ).all()
    pending_refund_cents = db.query(RefundRequest).filter(
        RefundRequest.created_at >= start,
        RefundRequest.created_at < end,
        RefundRequest.status == RefundStatus.PENDING,
    ).all()
    verified_services = db.query(ServiceVerification).filter(
        ServiceVerification.verified_at >= start,
        ServiceVerification.verified_at < end,
    ).order_by(ServiceVerification.verified_at.desc()).all()

    recharge_cents = sum(
        item.amount_cents for item in wallet_transactions
        if item.direction == WalletDirection.CREDIT
        and item.transaction_type == WalletTransactionType.RECHARGE
    )
    refund_cents = sum(
        item.amount_cents for item in wallet_transactions
        if item.direction == WalletDirection.DEBIT
        and item.transaction_type == WalletTransactionType.REFUND
    )
    pending_cents = sum(item.amount_cents for item in pending_refund_cents)
    staff_stylists = db.query(Stylist).join(User).filter(User.is_active.is_(True)).all()

    return StaffOverviewResponse(
        date=target_date.isoformat(),
        customer_count=len({str(item.user_id) for item in consumption_transactions}),
        order_count=len(consumption_transactions),
        consumption_cents=sum(amount_to_cents(item.amount) for item in consumption_transactions),
        consumption=cents_to_amount(sum(amount_to_cents(item.amount) for item in consumption_transactions)),
        recharge_cents=recharge_cents,
        recharge=cents_to_amount(recharge_cents),
        refund_cents=refund_cents,
        refund=cents_to_amount(refund_cents),
        pending_refund_cents=pending_cents,
        pending_refund=cents_to_amount(pending_cents),
        services=_staff_service_breakdown(consumption_transactions),
        performances=_staff_performance(consumption_transactions, staff_stylists),
        verified_services=[
            StaffVerifiedServiceResponse(
                verification_id=str(item.id),
                appointment_id=str(item.appointment_id),
                customer_name=item.customer.name,
                customer_phone=item.customer.phone,
                stylist_id=str(item.stylist_id),
                stylist_name=item.stylist.user.name,
                service=item.service,
                amount=item.amount,
                status=item.status.value,
                verified_at=item.verified_at.isoformat(),
                completed_at=item.completed_at.isoformat() if item.completed_at else None,
            )
            for item in verified_services
        ],
    )


@router.post("/members", response_model=MemberResponse)
async def create_member(
    request: MemberCreate,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if request.phone and request.phone != current_user.phone:
        raise HTTPException(status_code=400, detail="只能为当前登录用户创建会员资料")
    customer = UserService.create_or_get_customer(
        db,
        phone=current_user.phone,
        name=current_user.name,
    )
    if request.birthday is not None:
        _validate_birthday(request.birthday)
        customer.birthday = request.birthday
        db.commit()
        db.refresh(customer)

    member = db.query(Member).filter(Member.user_id == customer.id).first()
    if not member:
        # Customer creation always starts at the backend-controlled base level.
        member = MemberService.create_member(db, str(customer.id), level="silver")
    db.refresh(member)

    return MemberResponse(
        member_id=str(member.id),
        customer_id=str(customer.id),
        name=customer.name,
        phone=customer.phone,
        level=_member_display_level(member),
        balance=cents_to_amount(_member_balance_cents(member)),
        points=member.points,
        birthday=customer.birthday,
        birthday_bonus_claimed=member.birthday_bonus_claimed,
        expires_at=member.expires_at.isoformat() if member.expires_at else None,
    )


@router.get("/members", response_model=list[MemberResponse])
async def get_members(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    query = db.query(Member).join(User)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Member.user_id == current_user.id)
    members = query.all()
    return [
        MemberResponse(
            member_id=str(member.id),
            customer_id=str(member.user.id),
            name=member.user.name,
            phone=member.user.phone,
            level=_member_display_level(member),
            balance=(
                cents_to_amount(_member_balance_cents(member))
                if current_user.role != UserRole.STYLIST
                else None
            ),
            points=member.points,
            birthday=member.user.birthday,
            birthday_bonus_claimed=member.birthday_bonus_claimed,
            expires_at=member.expires_at.isoformat() if member.expires_at else None,
        )
        for member in members
    ]


@router.post("/transactions", response_model=TransactionResponse)
async def create_transaction(
    request: TransactionCreate,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=410,
        detail="Customer consumption must be recorded by staff service verification",
    )
def _wallet_transaction_response(transaction: WalletTransaction) -> WalletTransactionResponse:
    return WalletTransactionResponse(
        transaction_id=str(transaction.id),
        amount_cents=transaction.amount_cents,
        direction=transaction.direction.value,
        transaction_type=transaction.transaction_type.value,
        balance_after_cents=transaction.balance_after_cents,
        note=transaction.note,
        created_at=transaction.created_at.isoformat(),
    )


def _wallet_response(db: Session, user: User) -> WalletResponse:
    wallet = db.query(WalletAccount).filter(WalletAccount.user_id == user.id).first()
    if not wallet:
        wallet = FinanceService.get_or_create_wallet(db, user)
        db.commit()
        db.refresh(wallet)
    transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet.id
    ).order_by(WalletTransaction.created_at.desc()).limit(50).all()
    return WalletResponse(
        wallet_id=str(wallet.id),
        balance_cents=wallet.balance_cents,
        balance=cents_to_amount(wallet.balance_cents),
        transactions=[_wallet_transaction_response(item) for item in transactions],
    )


def _refund_response(refund: RefundRequest) -> RefundResponse:
    return RefundResponse(
        refund_id=str(refund.id),
        amount_cents=refund.amount_cents,
        amount=cents_to_amount(refund.amount_cents),
        status=refund.status.value,
        reason=refund.reason,
        created_at=refund.created_at.isoformat(),
        processed_at=refund.processed_at.isoformat() if refund.processed_at else None,
    )


def _notification_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        notification_id=str(notification.id),
        kind=notification.kind.value,
        title=notification.title,
        body=notification.body,
        is_read=notification.is_read,
        created_at=notification.created_at.isoformat(),
        read_at=notification.read_at.isoformat() if notification.read_at else None,
    )


# ===== 钱包、退款、通知与审计 =====

@router.get("/wallet", response_model=WalletResponse)
async def get_wallet(
    current_user: User = Depends(require_customer), db: Session = Depends(get_db)
):
    return _wallet_response(db, current_user)


@router.post("/wallet/recharge", response_model=WalletResponse)
async def recharge_wallet(
    request: RechargeRequest,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=410, detail="充值演示接口已关闭，生产环境必须接入真实支付回调")
    try:
        FinanceService.recharge(db, current_user, request.amount, request.note)
    except FinanceError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return _wallet_response(db, current_user)


@router.post("/refunds", response_model=RefundResponse, status_code=201)
async def create_refund_request(
    request: RefundCreate,
    current_user: User = Depends(require_customer),
    db: Session = Depends(get_db),
):
    try:
        refund = FinanceService.request_refund(db, current_user, request.amount, request.reason)
    except FinanceError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return _refund_response(refund)


@router.get("/refunds", response_model=list[RefundResponse])
async def get_refunds(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(RefundRequest).order_by(RefundRequest.created_at.desc())
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(RefundRequest.user_id == current_user.id)
    elif current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="只有店长账号可以查看全店退款")
    return [_refund_response(item) for item in query.all()]


@router.post("/refunds/{refund_id}/approve", response_model=RefundResponse)
async def approve_refund(
    refund_id: str,
    request: RefundDecisionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(request.manager_password, current_user.password_hash):
        FinanceService.create_audit(
            db, current_user.id, "security.step_up_denied", "refund_request", refund_id,
            {"action": "approve_refund"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="店长密码验证失败")
    try:
        refund, _, _ = FinanceService.approve_refund(db, refund_id, current_user)
    except FinanceError as exc:
        db.rollback()
        status_code = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))
    return _refund_response(refund)


@router.post("/refunds/{refund_id}/reject", response_model=RefundResponse)
async def reject_refund(
    refund_id: str,
    request: RefundDecisionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not verify_password(request.manager_password, current_user.password_hash):
        FinanceService.create_audit(
            db, current_user.id, "security.step_up_denied", "refund_request", refund_id,
            {"action": "reject_refund"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="店长密码验证失败")
    try:
        refund = FinanceService.reject_refund(db, refund_id, current_user)
    except FinanceError as exc:
        db.rollback()
        status_code = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))
    return _refund_response(refund)


@router.get("/notifications", response_model=list[NotificationResponse])
async def get_notifications(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    notifications = db.query(Notification).filter(
        Notification.user_id == current_user.id
    ).order_by(Notification.created_at.desc()).limit(100).all()
    return [_notification_response(item) for item in notifications]


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def read_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = FinanceService.mark_notification_read(db, notification_id, current_user)
    if not notification:
        raise HTTPException(status_code=404, detail="通知不存在")
    return _notification_response(notification)


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def get_audit_logs(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [
        AuditLogResponse(
            audit_id=str(item.id),
            actor_user_id=str(item.actor_user_id) if item.actor_user_id else None,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            details=item.details,
            created_at=item.created_at.isoformat(),
        )
        for item in logs
    ]


@router.get("/points/transactions", response_model=list[PointTransactionResponse])
async def get_point_transactions(
    current_user: User = Depends(require_customer), db: Session = Depends(get_db)
):
    records = db.query(PointTransaction).filter(
        PointTransaction.user_id == current_user.id
    ).order_by(PointTransaction.created_at.desc()).all()
    return [
        PointTransactionResponse(
            point_transaction_id=str(item.id),
            amount=item.amount,
            balance_after=item.balance_after,
            reason=item.reason,
            created_at=item.created_at.isoformat(),
        )
        for item in records
    ]


@router.get("/marketing/birthdays", response_model=list[BirthdayCampaignResponse])
async def get_birthday_campaigns(
    db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    members = MemberService.get_birthday_members_today(db)
    return [
        BirthdayCampaignResponse(
            member_id=str(member.id),
            name=member.user.name,
            phone=member.user.phone,
            level=_member_display_level(member),
            balance=cents_to_amount(_member_balance_cents(member)),
            points=member.points,
            message=f"{member.user.name} 今天生日，可发送生日护理券或积分礼包。",
        )
        for member in members
    ]


# ===== 客户维护 / 留存工作台 =====

def _reminder_evidence(r: ReminderLog, db: Session) -> str | None:
    customer = r.customer
    if not customer:
        return None

    if r.reminder_type.value == "birthday" and customer.birthday:
        days_until = RetentionService._days_until_birthday(customer.birthday, datetime.now())
        if days_until is not None:
            return f"生日 {customer.birthday}，还有 {days_until} 天（提前 {BIRTHDAY_LOOKAHEAD_DAYS} 天提醒）"
        return f"生日 {customer.birthday}，已进入生日提醒窗口"

    if r.reminder_type.value in {"repurchase", "churn_risk"} and r.reference_date:
        days_since = max(0, (datetime.now() - r.reference_date).days)
        cycle, basis = RetentionService.compute_cycle_days(db, customer)
        if r.reminder_type.value == "churn_risk":
            return f"{basis}；当前距上次到店 {days_since} 天，流失阈值 {CHURN_THRESHOLD_DAYS} 天"
        threshold = round(cycle * REPURCHASE_BUFFER)
        return f"{basis}；当前距上次到店 {days_since} 天，复购提醒阈值 {threshold} 天"

    return None


def _reminder_to_response(r: ReminderLog, db: Session) -> ReminderResponse:
    return ReminderResponse(
        reminder_id=str(r.id),
        customer_id=str(r.customer_id),
        customer_name=r.customer.name if r.customer else "未知",
        customer_phone=r.customer.phone if r.customer else "",
        stylist_id=str(r.stylist_id) if r.stylist_id else None,
        stylist_name=r.stylist.user.name if r.stylist else None,
        reminder_type=r.reminder_type.value,
        status=r.status.value,
        priority=r.priority,
        reason=r.reason or "",
        evidence=_reminder_evidence(r, db),
        suggested_message=r.suggested_message or "",
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@router.post("/retention/scan", response_model=ScanResultResponse)
async def scan_retention(
    _: None = Depends(verify_admin_token),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """手动触发一次全店扫描，生成待办。定时任务每天也会自动跑。"""
    result = RetentionService.scan_and_generate(db)
    FinanceService.create_audit(
        db,
        current_user.id,
        "retention.scan_completed",
        "retention_scan",
        str(current_user.id),
        result,
    )
    db.commit()
    return ScanResultResponse(**result)


@router.get("/retention/reminders", response_model=list[ReminderResponse])
async def get_reminders(
    stylist_id: str = Query(None, description="按发型师筛选，不传则看全店"),
    status: str = Query("pending", description="pending / contacted / dismissed"),
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """发型师工作台清单：该联系谁、为什么、话术，按优先级排序。"""
    reminders = RetentionService.list_reminders(db, stylist_id=stylist_id, status=status)
    return [_reminder_to_response(r, db) for r in reminders]


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _retention_contact_to_response(contact: RetentionContact) -> RetentionContactResponse:
    return RetentionContactResponse(
        contact_id=str(contact.id),
        channel=contact.channel,
        status=contact.status.value,
        actual_message=contact.actual_message,
        coupon_id=contact.coupon_id,
        reviewer_id=str(contact.reviewer_id),
        sender_id=str(contact.sender_id),
        attempted_at=_iso(contact.attempted_at) or "",
        sent_at=_iso(contact.sent_at),
        failed_at=_iso(contact.failed_at),
        provider_message_id=contact.provider_message_id,
        failure_reason=contact.failure_reason,
        reply_content=contact.reply_content,
        replied_at=_iso(contact.replied_at),
        followup_status=contact.followup_status,
    )


def _retention_task_to_response(task: RetentionTask) -> RetentionTaskResponse:
    contacts = task.contacts or []
    latest_contact = max(contacts, key=lambda item: item.attempted_at or item.created_at) if contacts else None
    return RetentionTaskResponse(
        task_id=str(task.id),
        customer_id=str(task.customer_id),
        customer_name=task.customer.name if task.customer else "未知",
        customer_phone=task.customer.phone if task.customer else None,
        stylist_id=str(task.stylist_id) if task.stylist_id else None,
        stylist_name=task.stylist.user.name if task.stylist and task.stylist.user else None,
        business_date=task.business_date.isoformat(),
        primary_type=task.primary_type.value,
        strategy_tags=task.strategy_tags or [],
        trigger_reasons=task.trigger_reasons or [],
        evidence=task.evidence or {},
        priority=task.priority,
        status=task.status.value,
        suggested_message=task.suggested_message,
        suggested_coupon_id=task.suggested_coupon_id,
        suggestion_reason=task.suggestion_reason,
        last_contact_at=_iso(latest_contact.sent_at or latest_contact.attempted_at) if latest_contact else None,
        last_contact_status=latest_contact.status.value if latest_contact else None,
        next_contact_at=_iso(task.next_contact_at),
        created_at=_iso(task.created_at) or "",
        updated_at=_iso(task.updated_at) or "",
    )


def _get_retention_task_or_404(db: Session, task_id: str) -> RetentionTask:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="留存任务不存在") from exc
    task = db.query(RetentionTask).filter(RetentionTask.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="留存任务不存在")
    return task


def _create_manual_followup_suppression(
    db: Session, task: RetentionTask, actor: User, reason: str | None,
) -> None:
    existing = db.query(RetentionSuppression).filter(
        RetentionSuppression.customer_id == task.customer_id,
        RetentionSuppression.suppression_type == RetentionSuppressionType.MANUAL_FOLLOWUP,
        RetentionSuppression.released_at.is_(None),
    ).first()
    if not existing:
        db.add(RetentionSuppression(
            customer_id=task.customer_id,
            suppression_type=RetentionSuppressionType.MANUAL_FOLLOWUP,
            reason=reason,
            created_by=actor.id,
        ))


def _send_retention_task(
    db: Session,
    task_id: str,
    current_user: User,
    request: RetentionSendRequest,
    *,
    retry_only: bool = False,
    commit: bool = True,
) -> RetentionTaskResponse:
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=410, detail="留存消息 Mock 发送器仅允许在演示环境使用")
    task = _get_retention_task_or_404(db, task_id)
    allowed_statuses = (RetentionTaskStatus.SEND_FAILED,) if retry_only else (
        RetentionTaskStatus.PENDING_REVIEW,
        RetentionTaskStatus.SEND_FAILED,
    )
    if task.status not in allowed_statuses:
        raise HTTPException(status_code=409, detail="当前任务状态不允许发送")
    if request.coupon_id:
        # 项目当前没有优惠券主数据表，拒绝接收任意券号，防止前端或 Agent 虚构权益。
        raise HTTPException(status_code=422, detail="优惠券功能尚未配置，当前不能使用优惠券")
    if not RetentionService.is_contact_eligible(db, task.customer_id):
        raise HTTPException(status_code=409, detail="客户当前处于退订、忽略、人工跟进或冷却状态，不能发送")

    now = datetime.now()
    # 条件更新使重复点击只有第一个请求能够把状态推进到 sending。
    updated = db.query(RetentionTask).filter(
        RetentionTask.id == task.id,
        RetentionTask.status.in_(allowed_statuses),
    ).update({RetentionTask.status: RetentionTaskStatus.SENDING, RetentionTask.updated_at: now})
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="任务正在被其他员工处理，请刷新后重试")
    db.flush()
    db.refresh(task)

    sender = MockMessageSender()
    contact = RetentionContact(
        task_id=task.id,
        customer_id=task.customer_id,
        reviewer_id=current_user.id,
        sender_id=current_user.id,
        channel=sender.channel,
        status=RetentionContactStatus.ATTEMPTING,
        actual_message=request.message.strip(),
        coupon_id=None,
        attempted_at=now,
    )
    db.add(contact)
    db.flush()
    result = sender.send(str(task.customer_id), contact.actual_message, simulate_failure=request.simulate_failure)

    if result.success:
        contact.status = RetentionContactStatus.SENT
        contact.sent_at = now
        contact.provider_message_id = result.provider_message_id
        task.suggested_message = contact.actual_message
        task.status = RetentionTaskStatus.COOLING
        task.next_contact_at = now + timedelta(days=RetentionService._cooldown_days_for_task(task))
        FinanceService.create_notification(
            db,
            task.customer_id,
            NotificationKind.MARKETING,
            "留存提醒",
            contact.actual_message,
        )
        FinanceService.create_audit(
            db,
            current_user.id,
            "retention.task_sent",
            "retention_task",
            str(task.id),
            {"contact_id": str(contact.id), "channel": sender.channel, "next_contact_at": task.next_contact_at.isoformat()},
        )
    else:
        contact.status = RetentionContactStatus.FAILED
        contact.failed_at = now
        contact.failure_reason = result.failure_reason or "消息渠道发送失败"
        task.status = RetentionTaskStatus.SEND_FAILED
        FinanceService.create_audit(
            db,
            current_user.id,
            "retention.task_send_failed",
            "retention_task",
            str(task.id),
            {"contact_id": str(contact.id), "reason": contact.failure_reason},
        )

    if commit:
        db.commit()
        db.refresh(task)
    return _retention_task_to_response(task)


@router.get("/retention/tasks", response_model=list[RetentionTaskResponse])
async def get_retention_tasks(
    view: str = Query("today", description="today / records"),
    status: str | None = Query(None),
    stylist_id: str | None = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if view not in {"today", "records"}:
        raise HTTPException(status_code=422, detail="view 只能是 today 或 records")
    task_status = None
    if status:
        try:
            task_status = RetentionTaskStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="未知的留存任务状态") from exc
    tasks = RetentionService.list_tasks(
        db,
        status=task_status,
        stylist_id=stylist_id,
        today_only=view == "today",
        records_only=view == "records",
    )
    return [_retention_task_to_response(task) for task in tasks]


@router.get("/retention/tasks/{task_id}", response_model=RetentionTaskDetailResponse)
async def get_retention_task(
    task_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = _get_retention_task_or_404(db, task_id)
    payload = _retention_task_to_response(task).model_dump()
    contacts = db.query(RetentionContact).filter(
        RetentionContact.task_id == task.id,
    ).order_by(RetentionContact.created_at.desc()).all()
    return RetentionTaskDetailResponse(
        **payload,
        contacts=[_retention_contact_to_response(contact) for contact in contacts],
    )


@router.post("/retention/tasks/{task_id}/send", response_model=RetentionTaskResponse)
async def send_retention_task(
    task_id: str,
    request: RetentionSendRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _send_retention_task(db, task_id, current_user, request)


@router.post("/retention/tasks/{task_id}/retry", response_model=RetentionTaskResponse)
async def retry_retention_task(
    task_id: str,
    request: RetentionSendRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _send_retention_task(db, task_id, current_user, request, retry_only=True)


@router.post("/retention/tasks/{task_id}/manual-followup", response_model=RetentionTaskResponse)
async def move_retention_task_to_manual_followup(
    task_id: str,
    request: RetentionManualFollowupRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = _get_retention_task_or_404(db, task_id)
    if task.status in {RetentionTaskStatus.COOLING, RetentionTaskStatus.CLOSED, RetentionTaskStatus.IGNORED}:
        raise HTTPException(status_code=409, detail="当前任务状态不能转人工跟进")
    task.status = RetentionTaskStatus.MANUAL_FOLLOWUP
    _create_manual_followup_suppression(db, task, current_user, request.reason)
    FinanceService.create_audit(db, current_user.id, "retention.task_manual_followup", "retention_task", str(task.id), {"reason": request.reason})
    db.commit()
    db.refresh(task)
    return _retention_task_to_response(task)


@router.post("/retention/tasks/{task_id}/ignore", response_model=RetentionTaskResponse)
async def ignore_retention_task(
    task_id: str,
    request: RetentionIgnoreRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = _get_retention_task_or_404(db, task_id)
    if task.status in {RetentionTaskStatus.COOLING, RetentionTaskStatus.CLOSED, RetentionTaskStatus.IGNORED}:
        raise HTTPException(status_code=409, detail="当前任务状态不能设置忽略")
    now = datetime.now()
    mode_mapping = {
        "30_days": (RetentionSuppressionType.TEMPORARY_IGNORE, now + timedelta(days=30)),
        "90_days": (RetentionSuppressionType.TEMPORARY_IGNORE, now + timedelta(days=90)),
        "permanent": (RetentionSuppressionType.PERMANENT_IGNORE, None),
        "unsubscribe": (RetentionSuppressionType.UNSUBSCRIBED, None),
    }
    suppression_type, ends_at = mode_mapping[request.mode]
    task.status = RetentionTaskStatus.IGNORED
    db.add(RetentionSuppression(
        customer_id=task.customer_id,
        suppression_type=suppression_type,
        starts_at=now,
        ends_at=ends_at,
        reason=request.reason,
        created_by=current_user.id,
    ))
    FinanceService.create_audit(
        db, current_user.id, "retention.task_ignored", "retention_task", str(task.id),
        {"mode": request.mode, "reason": request.reason},
    )
    db.commit()
    db.refresh(task)
    return _retention_task_to_response(task)


@router.post("/retention/tasks/{task_id}/reply", response_model=RetentionTaskResponse)
async def record_retention_reply(
    task_id: str,
    request: RetentionReplyRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = _get_retention_task_or_404(db, task_id)
    contact = db.query(RetentionContact).filter(
        RetentionContact.task_id == task.id,
        RetentionContact.status == RetentionContactStatus.SENT,
    ).order_by(RetentionContact.sent_at.desc()).first()
    if not contact:
        raise HTTPException(status_code=409, detail="任务没有成功发送记录，不能录入客户回复")
    now = datetime.now()
    contact.reply_content = request.reply_content.strip()
    contact.replied_at = now
    contact.followup_status = "pending"
    task.status = RetentionTaskStatus.REPLIED
    _create_manual_followup_suppression(db, task, current_user, "客户已回复，等待人工跟进")
    FinanceService.create_audit(db, current_user.id, "retention.customer_reply_recorded", "retention_task", str(task.id), {"contact_id": str(contact.id)})
    db.commit()
    db.refresh(task)
    return _retention_task_to_response(task)


@router.post("/retention/tasks/{task_id}/close", response_model=RetentionTaskResponse)
async def close_retention_task(
    task_id: str,
    request: RetentionCloseRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = _get_retention_task_or_404(db, task_id)
    if task.status in {RetentionTaskStatus.CLOSED, RetentionTaskStatus.IGNORED}:
        raise HTTPException(status_code=409, detail="当前任务已经结束")
    task.status = RetentionTaskStatus.CLOSED
    active_manual_suppressions = db.query(RetentionSuppression).filter(
        RetentionSuppression.customer_id == task.customer_id,
        RetentionSuppression.suppression_type == RetentionSuppressionType.MANUAL_FOLLOWUP,
        RetentionSuppression.released_at.is_(None),
    ).all()
    for suppression in active_manual_suppressions:
        suppression.released_at = datetime.now()
        suppression.released_by = current_user.id
        suppression.release_reason = request.reason or "人工跟进完成"
    FinanceService.create_audit(db, current_user.id, "retention.task_closed", "retention_task", str(task.id), {"reason": request.reason})
    db.commit()
    db.refresh(task)
    return _retention_task_to_response(task)


@router.post("/retention/agent/run", response_model=RetentionAgentResponse)
async def run_retention_agent(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import json
    task = AgentTaskState(
        id=uuid.uuid4(),
        requester_id=current_user.id,
        workflow_type="retention_segmentation",
        status=AgentTaskStatus.RUNNING,
        input_payload=json.dumps({"requested_by": str(current_user.id)}, ensure_ascii=False),
        awaiting_confirmation=False,
    )
    db.add(task)
    db.commit()
    try:
        result = run_retention_graph(str(current_user.id))
        task.status = AgentTaskStatus.COMPLETED
        task.result_payload = json.dumps(result, ensure_ascii=False)
        FinanceService.create_audit(
            db,
            current_user.id,
            "agent.retention_completed",
            "agent_task",
            str(task.id),
            {"trace_id": result.get("trace_id"), "recommendation_count": len(result.get("recommendations", []))},
        )
        db.commit()
        return RetentionAgentResponse(
            task_id=str(task.id),
            status=task.status.value,
            summary=result["summary"],
            recommendations=result["recommendations"],
            analysis_basis=result.get("analysis_basis", {}),
            trace_id=result.get("trace_id"),
            trace=result.get("trace", {}),
        )
    except Exception as exc:
        db.rollback()
        task = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).first()
        if task:
            task.status = AgentTaskStatus.FAILED
            task.result_payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
            db.commit()
        raise HTTPException(status_code=500, detail="留存运营分析暂时不可用")


@router.post("/retention/reminders/{reminder_id}/contacted", response_model=dict)
async def mark_reminder_contacted(
    reminder_id: str, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """发型师联系完客户后点「已联系」。"""
    ok = RetentionService.mark_contacted(db, reminder_id, actor=current_user)
    if not ok:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return {"success": True, "message": "已标记为已联系"}


@router.post("/retention/reminders/{reminder_id}/dismiss", response_model=dict)
async def dismiss_reminder(
    reminder_id: str, current_user: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """忽略某条提醒（不需要联系）。"""
    ok = RetentionService.dismiss(db, reminder_id, actor=current_user)
    if not ok:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return {"success": True, "message": "已忽略"}


# ===== 员工日程 =====

@router.get("/staff/schedule", response_model=list[StaffScheduleResponse])
async def get_staff_schedule(
    stylist_id: str = Query(None),
    date: str = Query(None),
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    if stylist_id:
        appointments = staff_schedule_service.get_stylist_schedule(stylist_id, date=date)
        stylist = StylistService.get_stylist_by_id(db, stylist_id)
        name = stylist.user.name if stylist else "Unknown"
        return [StaffScheduleResponse(stylist_name=name, appointments=appointments)]
    else:
        schedule = staff_schedule_service.get_salon_schedule(date=date)
        return [
            StaffScheduleResponse(stylist_name=name, appointments=apts)
            for name, apts in schedule.items()
        ]


# ===== 数据库初始化 =====

@router.post("/init-db", response_model=InitDBResponse)
async def reset_database(
    _: None = Depends(verify_admin_token), __: User = Depends(require_admin)
):
    try:
        init_database()
        seed_sample_data()
        logger.info("Database initialized with sample data")
        return InitDBResponse(success=True, message="数据库已初始化，已填充示例数据")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        return InitDBResponse(success=False, message=str(e))
