"""API Pydantic 模型 — 请求/响应校验"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Optional, List, Literal


# ===== 健康检查 =====

class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


# ===== AI 对话 =====

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户消息")
    phone: str = Field(..., description="客户手机号，用于识别身份")
    name: Optional[str] = Field(None, description="客户姓名，新客户时需要")
    role: str = Field("customer", description="对话身份：customer(顾客顾问) / staff(店员助手)")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="AI 回复")
    actions: List[str] = Field(default_factory=list, description="Agent 执行了哪些工具")


class StaffAgentReplyContext(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=120, description="被引用消息在当前对话中的编号")
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000, description="被引用消息内容")


class StaffAgentQueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="员工查询问题")
    reply_to: Optional[StaffAgentReplyContext] = Field(
        None,
        description="可选的被引用历史消息，帮助 Agent 理解当前回复对象",
    )


class StaffAgentQueryResponse(BaseModel):
    task_id: str
    status: str
    reply: str
    actions: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    trace_id: Optional[str] = None
    trace: dict[str, Any] = Field(default_factory=dict)
    agent_task: Optional[dict[str, Any]] = None


class AppointmentChangeProposalRequest(BaseModel):
    appointment_id: str = Field(..., description="待调整预约 ID")
    new_slot_id: str = Field(..., description="新的时间槽 ID")
    new_stylist_id: Optional[str] = Field(None, description="新的发型师 ID，不传则沿用原发型师")
    service: Optional[str] = Field(None, min_length=1, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


class AppointmentApprovalProposalRequest(BaseModel):
    appointment_id: str = Field(..., description="待批复预约 ID")


class RefundDecisionProposalRequest(BaseModel):
    refund_id: str = Field(..., description="待处理退款 ID")
    decision: str = Field(..., pattern="^(approve|reject)$")


class AgentTaskResponse(BaseModel):
    task_id: str
    workflow_type: str
    status: str
    awaiting_confirmation: bool
    input_payload: Optional[dict[str, Any]] = None
    result_payload: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class AgentConfirmationRequest(BaseModel):
    confirmed: bool
    manager_password: Optional[str] = Field(None, min_length=1, max_length=128)


class RetentionAgentResponse(BaseModel):
    task_id: str
    status: str
    summary: dict[str, int]
    recommendations: List[dict[str, Any]] = Field(default_factory=list)
    analysis_basis: dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    trace: dict[str, Any] = Field(default_factory=dict)


# ===== 登录与身份 =====

class AuthRegisterRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


class AuthLoginRequest(BaseModel):
    phone: str = Field(..., min_length=6, max_length=20)
    password: str = Field(..., min_length=1, max_length=128)


class WechatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    user_id: str
    name: str
    phone: Optional[str] = None
    role: str
    birthday: Optional[str] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    birthday: Optional[str] = Field(
        None,
        pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$",
        description="生日，MM-DD 格式",
    )


# ===== 发型师 =====

class StylistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stylist_id: str
    name: str
    phone: str
    specialty: str
    experience_years: int
    rating: float
    bio: Optional[str] = None
    is_available: bool


# ===== 时间槽 =====

class TimeSlotResponse(BaseModel):
    slot_id: str
    date: str
    time: str
    datetime_str: str
    is_booked: bool


# ===== 预约 =====

class AppointmentCreate(BaseModel):
    phone: Optional[str] = Field(None, description="兼容旧客户端，后端以登录身份为准")
    name: Optional[str] = Field(None, description="兼容旧客户端，后端以登录身份为准")
    stylist_id: str = Field(..., description="发型师ID")
    slot_id: str = Field(..., description="时间槽ID")
    service: str = Field(..., description="服务类型，如烫、染、护理")
    notes: Optional[str] = Field(None, description="备注")


class StaffAppointmentCreate(BaseModel):
    customer_id: str = Field(..., description="已有客户 ID")
    stylist_id: str = Field(..., description="发型师 ID")
    slot_id: str = Field(..., description="可用时间槽 ID")
    service: str = Field(..., min_length=1, max_length=100, description="服务项目")
    notes: Optional[str] = Field(None, max_length=500, description="预约备注")


class StaffBookingResponse(BaseModel):
    appointment_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: str
    stylist_name: str
    service: str
    appointment_datetime: str
    status: str
    notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    appointment_id: str
    customer_name: str
    stylist_name: str
    service: str
    appointment_datetime: str
    status: str
    notes: Optional[str] = None


# ===== 会员与营销 =====

class CustomerResponse(BaseModel):
    customer_id: str
    name: str
    phone: Optional[str] = None
    birthday: Optional[str] = None
    total_spent: Optional[float] = None
    last_visit: Optional[str] = None


class StaffCustomerWalletResponse(BaseModel):
    customer_id: str
    name: str
    phone: Optional[str] = None
    balance_cents: int = 0
    balance: float = 0
    recharge_total_cents: int = 0
    recharge_total: float = 0
    recharge_count: int = 0
    last_recharge_at: Optional[str] = None
    transactions: List["WalletTransactionResponse"] = Field(default_factory=list)


class MemberCreate(BaseModel):
    phone: str = Field(..., description="客户手机号")
    name: str = Field(..., description="客户姓名")
    birthday: Optional[str] = Field(None, description="生日，MM-DD 格式")
    level: str = Field("silver", description="历史会员等级；当前展示等级按账户余额动态计算")


class MemberResponse(BaseModel):
    member_id: str
    customer_id: str
    name: str
    phone: Optional[str] = None
    level: str
    balance: Optional[float] = None
    points: int
    birthday: Optional[str] = None
    birthday_bonus_claimed: bool
    expires_at: Optional[str] = None


class TransactionCreate(BaseModel):
    phone: str = Field(..., description="客户手机号")
    amount: float = Field(..., gt=0, description="消费金额")
    service: str = Field(..., description="消费项目")
    appointment_id: Optional[str] = Field(None, description="关联预约ID")


class TransactionResponse(BaseModel):
    transaction_id: str
    customer_name: str
    phone: Optional[str] = None
    amount: float
    service: str
    created_at: str
    points_added: int


class ServicePackageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    service: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0)
    total_uses: int = Field(..., gt=0, le=1000)
    validity_days: int = Field(365, gt=0, le=3650)


class ServicePackageResponse(BaseModel):
    package_id: str
    name: str
    service: str
    price: float
    total_uses: int
    validity_days: int
    is_active: bool


class CustomerPackageAssignRequest(BaseModel):
    customer_id: str
    package_id: str


class CustomerPackageResponse(BaseModel):
    customer_package_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    package_id: str
    package_name: str
    service: str
    purchase_price: float
    total_uses: int
    remaining_uses: int
    status: str
    purchased_at: str
    expires_at: str


class ServiceVerificationCreate(BaseModel):
    customer_package_id: Optional[str] = None
    amount: Optional[float] = Field(None, ge=0)


class ServiceCompletionRequest(BaseModel):
    pass


class ServiceVerificationResponse(BaseModel):
    verification_id: str
    appointment_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: str
    stylist_name: str
    service: str
    amount: float
    status: str
    customer_package_id: Optional[str] = None
    package_name: Optional[str] = None
    remaining_uses: Optional[int] = None
    verified_at: str
    completed_at: Optional[str] = None


class ServiceVerificationOptionsResponse(BaseModel):
    appointment_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: str
    stylist_name: str
    service: str
    appointment_datetime: str
    appointment_status: str
    packages: List[CustomerPackageResponse] = Field(default_factory=list)
    verification: Optional[ServiceVerificationResponse] = None


# ===== 钱包、退款、通知 =====

class RechargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="充值金额，单位元")
    note: Optional[str] = Field(None, max_length=255)


class WalletTransactionResponse(BaseModel):
    transaction_id: str
    amount_cents: int
    direction: str
    transaction_type: str
    balance_after_cents: int
    note: Optional[str] = None
    created_at: str


class WalletResponse(BaseModel):
    wallet_id: str
    balance_cents: int
    balance: float
    transactions: List[WalletTransactionResponse] = Field(default_factory=list)


class StaffServiceBreakdownResponse(BaseModel):
    service: str
    customer_count: int = 0
    order_count: int = 0
    amount_cents: int = 0
    amount: float = 0


class StaffPerformanceCustomerResponse(BaseModel):
    appointment_id: Optional[str] = None
    customer_name: str
    customer_phone: Optional[str] = None
    service: str
    amount_cents: int = 0
    amount: float = 0
    status: str
    created_at: str


class StaffPerformanceResponse(BaseModel):
    stylist_id: Optional[str] = None
    stylist_name: str
    stylist_phone: Optional[str] = None
    customer_count: int = 0
    order_count: int = 0
    amount_cents: int = 0
    amount: float = 0
    services: List[StaffServiceBreakdownResponse] = Field(default_factory=list)
    customers: List[StaffPerformanceCustomerResponse] = Field(default_factory=list)


class StaffVerifiedServiceResponse(BaseModel):
    verification_id: str
    appointment_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: str
    stylist_name: str
    service: str
    amount: float
    status: str
    verified_at: str
    completed_at: Optional[str] = None


class StaffOverviewResponse(BaseModel):
    date: str
    customer_count: int = 0
    order_count: int = 0
    consumption_cents: int = 0
    consumption: float = 0
    recharge_cents: int = 0
    recharge: float = 0
    refund_cents: int = 0
    refund: float = 0
    pending_refund_cents: int = 0
    pending_refund: float = 0
    services: List[StaffServiceBreakdownResponse] = Field(default_factory=list)
    performances: List[StaffPerformanceResponse] = Field(default_factory=list)
    verified_services: List[StaffVerifiedServiceResponse] = Field(default_factory=list)


class RefundCreate(BaseModel):
    amount: float = Field(..., gt=0, description="退款金额，单位元")
    reason: Optional[str] = Field(None, max_length=255)


class RefundDecisionRequest(BaseModel):
    manager_password: str = Field(..., min_length=1, max_length=128)


class RefundResponse(BaseModel):
    refund_id: str
    amount_cents: int
    amount: float
    status: str
    reason: Optional[str] = None
    created_at: str
    processed_at: Optional[str] = None


class NotificationResponse(BaseModel):
    notification_id: str
    kind: str
    title: str
    body: str
    is_read: bool
    created_at: str
    read_at: Optional[str] = None


class AuditLogResponse(BaseModel):
    audit_id: str
    actor_user_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    details: Optional[str] = None
    created_at: str


class PointTransactionResponse(BaseModel):
    point_transaction_id: str
    amount: int
    balance_after: int
    reason: str
    created_at: str


class BirthdayCampaignResponse(BaseModel):
    member_id: str
    name: str
    phone: Optional[str] = None
    level: str
    balance: float = 0
    points: int
    message: str


# ===== 员工日程 =====

class StaffAppointmentResponse(BaseModel):
    appointment_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    service: str
    appointment_datetime: str
    status: str
    notes: Optional[str] = None

class StaffScheduleResponse(BaseModel):
    stylist_name: str
    appointments: List[StaffAppointmentResponse]


# ===== 客户维护 / 留存工作台 =====

class ReminderResponse(BaseModel):
    reminder_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: Optional[str] = None
    stylist_name: Optional[str] = None
    reminder_type: str          # repurchase / birthday / churn_risk
    status: str
    priority: int
    reason: str
    evidence: Optional[str] = None
    suggested_message: str
    created_at: str


class ScanResultResponse(BaseModel):
    total: int
    repurchase: int
    birthday: int
    churn_risk: int


class RetentionTaskResponse(BaseModel):
    task_id: str
    customer_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    stylist_id: Optional[str] = None
    stylist_name: Optional[str] = None
    business_date: str
    primary_type: str
    strategy_tags: List[str] = Field(default_factory=list)
    trigger_reasons: List[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    priority: int
    status: str
    suggested_message: Optional[str] = None
    suggested_coupon_id: Optional[str] = None
    suggestion_reason: Optional[str] = None
    last_contact_at: Optional[str] = None
    last_contact_status: Optional[str] = None
    next_contact_at: Optional[str] = None
    created_at: str
    updated_at: str


class RetentionContactResponse(BaseModel):
    contact_id: str
    channel: str
    status: str
    actual_message: str
    coupon_id: Optional[str] = None
    reviewer_id: str
    sender_id: str
    attempted_at: str
    sent_at: Optional[str] = None
    failed_at: Optional[str] = None
    provider_message_id: Optional[str] = None
    failure_reason: Optional[str] = None
    reply_content: Optional[str] = None
    replied_at: Optional[str] = None
    followup_status: Optional[str] = None


class RetentionTaskDetailResponse(RetentionTaskResponse):
    contacts: List[RetentionContactResponse] = Field(default_factory=list)


class RetentionSendRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    coupon_id: Optional[str] = Field(None, max_length=64)
    simulate_failure: bool = False


class RetentionIgnoreRequest(BaseModel):
    mode: str = Field(..., pattern="^(30_days|90_days|permanent|unsubscribe)$")
    reason: Optional[str] = Field(None, max_length=500)


class RetentionManualFollowupRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class RetentionReplyRequest(BaseModel):
    reply_content: str = Field(..., min_length=1, max_length=2000)


class RetentionCloseRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


# ===== 初始化数据库 =====

class InitDBResponse(BaseModel):
    success: bool
    message: str
