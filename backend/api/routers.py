"""API 路由 — 所有 REST 接口"""

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from loguru import logger
from datetime import datetime, timedelta
import uuid
import json

from backend.database.connection import get_db
from backend.config import settings
from backend.database.service import (
    UserService, StylistService, TimeSlotService, AppointmentService, MemberService,
)
from backend.database.retention import RetentionService
from backend.database.finance import FinanceError, FinanceService, amount_to_cents, cents_to_amount
from backend.database.appointment_change import AppointmentChangeError
from backend.database.init_db import init_database, seed_sample_data
from backend.database.models import (
    AuditLog, Member, Notification, NotificationKind, PointTransaction,
    RefundRequest, Transaction, User, ReminderLog, WalletAccount,
    WalletTransaction, Appointment, Stylist, UserRole, AgentTaskState, AgentTaskStatus,
    RefundStatus, WalletDirection, WalletTransactionType, AppointmentStatus,
    ServicePackage, CustomerPackage, CustomerPackageStatus,
    ServiceVerification, ServiceVerificationStatus,
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
    AppointmentCreate, AppointmentResponse,
    CustomerResponse, MemberCreate, MemberResponse,
    TransactionCreate, TransactionResponse, BirthdayCampaignResponse,
    StaffScheduleResponse, InitDBResponse,
    ReminderResponse, ScanResultResponse,
    AuthRegisterRequest, AuthLoginRequest, WechatLoginRequest, TokenResponse, CurrentUserResponse,
    ProfileUpdate,
    RechargeRequest, WalletResponse, WalletTransactionResponse,
    RefundCreate, RefundResponse, NotificationResponse, AuditLogResponse,
    PointTransactionResponse,
    StaffCustomerWalletResponse, StaffServiceBreakdownResponse,
    StaffPerformanceCustomerResponse, StaffPerformanceResponse, StaffOverviewResponse,
    ServicePackageCreate, ServicePackageResponse,
    CustomerPackageAssignRequest, CustomerPackageResponse,
    ServiceVerificationCreate, ServiceVerificationResponse,
    ServiceVerificationOptionsResponse,
    StaffAgentQueryRequest, StaffAgentQueryResponse,
    AppointmentChangeProposalRequest, AgentTaskResponse, AgentConfirmationRequest,
    RetentionAgentResponse,
)
from backend.agents.staff_graph import run_staff_query
from backend.agents.appointment_change_graph import run_appointment_change_workflow
from backend.agents.retention_graph import run_retention_graph

router = APIRouter(prefix="/api", tags=["API"])


def verify_admin_token(x_admin_token: str | None = Header(None)):
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")


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
async def login(request: AuthLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.phone == request.phone).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="手机号或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=create_access_token(user),
        expires_in=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/auth/wechat", response_model=TokenResponse)
async def wechat_login(request: WechatLoginRequest, db: Session = Depends(get_db)):
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

    return TokenResponse(
        access_token=create_access_token(user),
        expires_in=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


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
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user)):
    logger.info(f"Chat: {current_user.phone} -> {request.message[:50]}")
    result = chat_agent.handle_message(
        message=request.message,
        phone=current_user.phone,
        name=current_user.name,
    )
    return ChatResponse(**result)


@router.post("/chat/langchain", response_model=ChatResponse)
async def chat_with_langchain_adapter(
    request: ChatRequest, current_user: User = Depends(get_current_user)
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
    try:
        result = run_staff_query(request.message, str(current_user.id))
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
    current_user: User = Depends(require_staff),
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
    return _agent_task_response(task)


@router.post("/staff/agent/tasks/{task_id}/confirm", response_model=AgentTaskResponse)
async def confirm_staff_agent_task(
    task_id: str,
    request: AgentConfirmationRequest,
    current_user: User = Depends(require_staff),
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
        AgentTaskState.workflow_type == "appointment_change",
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent 任务不存在")
    if not task.awaiting_confirmation or task.status != AgentTaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="该任务已经处理，不能重复确认")
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
        raise HTTPException(status_code=404, detail="预约不存在")
    return {"success": True, "message": "预约已取消"}


# ===== 会员与营销 =====

@router.get("/customers", response_model=list[CustomerResponse])
async def get_customers(
    db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    customers = UserService.get_all_customers(db)
    return [
        CustomerResponse(
            customer_id=str(customer.id),
            name=customer.name,
            phone=customer.phone,
            birthday=customer.birthday,
            total_spent=customer.total_spent or 0,
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
    _: User = Depends(require_staff), db: Session = Depends(get_db)
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
    _: User = Depends(require_staff), db: Session = Depends(get_db)
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
    _: User = Depends(require_staff),
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
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = db.query(CustomerPackage).order_by(CustomerPackage.expires_at.asc())
    if customer_id:
        query = query.filter(CustomerPackage.customer_id == _parse_uuid(customer_id, "客户 ID 格式不正确"))
    return [_customer_package_response(package) for package in query.all()]


@router.post("/staff/customer-packages", response_model=CustomerPackageResponse, status_code=201)
async def assign_staff_customer_package(
    request: CustomerPackageAssignRequest,
    current_user: User = Depends(require_staff),
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
    _: User = Depends(require_staff),
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
    current_user: User = Depends(require_staff),
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


@router.post(
    "/staff/service-verifications/{verification_id}/complete",
    response_model=ServiceVerificationResponse,
)
async def complete_service_verification(
    verification_id: str,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    verification = db.query(ServiceVerification).filter(
        ServiceVerification.id == _parse_uuid(verification_id, "核验记录 ID 格式不正确")
    ).first()
    if not verification:
        raise HTTPException(status_code=404, detail="核验记录不存在")
    if verification.status == ServiceVerificationStatus.COMPLETED:
        return _service_verification_response(verification)
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
    db.commit()
    db.refresh(verification)
    return _service_verification_response(verification)


@router.get("/staff/overview", response_model=StaffOverviewResponse)
async def get_staff_overview(
    date: str | None = Query(None),
    _: User = Depends(require_staff), db: Session = Depends(get_db),
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
    if request.birthday:
        customer.birthday = request.birthday
        db.commit()
        db.refresh(customer)

    member = db.query(Member).filter(Member.user_id == customer.id).first()
    if not member:
        member = MemberService.create_member(db, str(customer.id), level=request.level)
    db.refresh(member)

    return MemberResponse(
        member_id=str(member.id),
        customer_id=str(customer.id),
        name=customer.name,
        phone=customer.phone,
        level=member.level.value,
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
            level=member.level.value,
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
    if request.phone and request.phone != current_user.phone:
        raise HTTPException(status_code=400, detail="只能记录当前登录用户的消费")
    customer = db.query(User).filter(User.id == current_user.id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="客户不存在，请先创建会员或预约")
    if request.appointment_id:
        raise HTTPException(status_code=403, detail="预约服务必须由员工核验后完成")

    transaction = Transaction(
        id=uuid.uuid4(),
        user_id=customer.id,
        appointment_id=uuid.UUID(request.appointment_id) if request.appointment_id else None,
        amount=request.amount,
        service=request.service,
    )
    db.add(transaction)

    customer.total_spent = (customer.total_spent or 0) + request.amount
    customer.last_visit = datetime.now()

    points_added = int(request.amount)
    member = db.query(Member).filter(Member.user_id == customer.id).first()
    if member:
        member.points += points_added
        db.add(PointTransaction(
            id=uuid.uuid4(),
            user_id=customer.id,
            amount=points_added,
            balance_after=member.points,
            reason=f"{request.service}消费积分",
            source_type="transaction",
            source_id=str(transaction.id),
        ))
        FinanceService.create_notification(
            db, customer.id, NotificationKind.WALLET, "积分到账",
            f"本次消费获得 {points_added} 积分，当前积分 {member.points}。",
        )
    FinanceService.create_audit(
        db, current_user.id, "transaction.create", "transaction", str(transaction.id),
        {"amount": request.amount, "points_added": points_added if member else 0},
    )

    db.commit()
    db.refresh(transaction)
    db.refresh(customer)

    return TransactionResponse(
        transaction_id=str(transaction.id),
        customer_name=customer.name,
        phone=customer.phone,
        amount=transaction.amount,
        service=transaction.service,
        created_at=transaction.created_at.isoformat(),
        points_added=points_added if member else 0,
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
    return [_refund_response(item) for item in query.all()]


@router.post("/refunds/{refund_id}/approve", response_model=RefundResponse)
async def approve_refund(
    refund_id: str,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
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
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
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
    _: User = Depends(require_staff), db: Session = Depends(get_db)
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
    db: Session = Depends(get_db), _: User = Depends(require_staff)
):
    members = MemberService.get_birthday_members_today(db)
    return [
        BirthdayCampaignResponse(
            member_id=str(member.id),
            name=member.user.name,
            phone=member.user.phone,
            level=member.level.value,
            points=member.points,
            message=f"{member.user.name} 今天生日，可发送生日护理券或积分礼包。",
        )
        for member in members
    ]


# ===== 客户维护 / 留存工作台 =====

def _reminder_to_response(r: ReminderLog) -> ReminderResponse:
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
        suggested_message=r.suggested_message or "",
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


@router.post("/retention/scan", response_model=ScanResultResponse)
async def scan_retention(
    _: None = Depends(verify_admin_token),
    current_user: User = Depends(require_staff),
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
    return [_reminder_to_response(r) for r in reminders]


@router.post("/retention/agent/run", response_model=RetentionAgentResponse)
async def run_retention_agent(
    current_user: User = Depends(require_staff),
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
    reminder_id: str, current_user: User = Depends(require_staff), db: Session = Depends(get_db)
):
    """发型师联系完客户后点「已联系」。"""
    ok = RetentionService.mark_contacted(db, reminder_id, actor=current_user)
    if not ok:
        raise HTTPException(status_code=404, detail="提醒不存在")
    return {"success": True, "message": "已标记为已联系"}


@router.post("/retention/reminders/{reminder_id}/dismiss", response_model=dict)
async def dismiss_reminder(
    reminder_id: str, current_user: User = Depends(require_staff), db: Session = Depends(get_db)
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
