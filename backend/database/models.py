"""数据库模型定义"""

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Enum as SQLEnum, Table, Text
from sqlalchemy.orm import relationship
from backend.database.connection import UniversalUUID as UUID
from datetime import datetime, timedelta
import uuid
import enum

from backend.database.connection import Base

class UserRole(enum.Enum):
    """\u7528\u6237\u89d2\u8272"""
    CUSTOMER = "customer"
    STYLIST = "stylist"
    ADMIN = "admin"

class AppointmentStatus(enum.Enum):
    """\u9884\u7ea6\u72b6\u6001"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class MemberLevel(enum.Enum):
    """\u4f1a\u5458\u7b49\u7ea7"""
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"

class ReminderType(enum.Enum):
    """\u5ba2\u6237\u7ef4\u62a4\u63d0\u9192\u7c7b\u578b"""
    REPURCHASE = "repurchase"      # \u590d\u8d2d\u63d0\u9192\uff1a\u6309\u4e2a\u4eba\u8282\u594f\u8be5\u56de\u5e97\u4e86
    BIRTHDAY = "birthday"          # \u751f\u65e5\u63d0\u9192
    CHURN_RISK = "churn_risk"      # \u6d41\u5931\u9884\u8b66\uff1a\u8fdc\u8d85\u8282\u594f\u672a\u5230\u5e97

class ReminderStatus(enum.Enum):
    """\u63d0\u9192\u5904\u7406\u72b6\u6001"""
    PENDING = "pending"            # \u5f85\u53d1\u578b\u5e08\u8054\u7cfb
    CONTACTED = "contacted"        # \u5df2\u8054\u7cfb
    DISMISSED = "dismissed"        # \u5df2\u5ffd\u7565

class WalletDirection(enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class WalletTransactionType(enum.Enum):
    RECHARGE = "recharge"
    PURCHASE = "purchase"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class RefundStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class NotificationKind(enum.Enum):
    APPOINTMENT = "appointment"
    WALLET = "wallet"
    REFUND = "refund"
    MARKETING = "marketing"
    SYSTEM = "system"


class AgentTaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    """\u7528\u6237\u8868"""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    email = Column(String(100), unique=True)
    role = Column(SQLEnum(UserRole), default=UserRole.CUSTOMER)
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)
    
    # \u5ba2\u6237\u4fe1\u606f
    birthday = Column(String(10))  # MM-DD\u683c\u5f0f
    total_spent = Column(Float, default=0)
    last_visit = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # \u5173\u7cfb
    appointments = relationship("Appointment", back_populates="customer")
    member = relationship("Member", back_populates="user", uselist=False)
    transactions = relationship("Transaction", back_populates="user")
    wallet_account = relationship("WalletAccount", back_populates="user", uselist=False)
    wallet_transactions = relationship("WalletTransaction", back_populates="user")
    refund_requests = relationship(
        "RefundRequest",
        back_populates="user",
        foreign_keys="RefundRequest.user_id",
    )
    point_transactions = relationship("PointTransaction", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="actor")
    agent_task_states = relationship("AgentTaskState", back_populates="requester")
    
    # \u5f2f\u5e08\u4fe1\u606f
    stylist_info = relationship("Stylist", back_populates="user", uselist=False)

class Stylist(Base):
    """\u53d1\u578b\u5e08\u8868"""
    __tablename__ = "stylists"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    specialty = Column(String(500))  # \u64cd\u957f\u53d1\u578b\uff0c\u903b\u8f91\u53c2\u8003\uff1a"\u70eb\u3001\u67d3\u3001\u62a4\u7406"
    experience_years = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    bio = Column(Text)  # \u4e2a\u4eba\u4ecb\u7ecd
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # \u5173\u7cfb
    user = relationship("User", back_populates="stylist_info")
    appointments = relationship("Appointment", back_populates="stylist")
    time_slots = relationship("StylistTimeSlot", back_populates="stylist", cascade="all, delete-orphan")

class StylistTimeSlot(Base):
    """\u53d1\u578b\u5e08\u65f6\u95f4\u69fd\u8868"""
    __tablename__ = "stylist_time_slots"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stylist_id = Column(UUID(as_uuid=True), ForeignKey("stylists.id"), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD\u683c\u5f0f
    time = Column(String(5), nullable=False)  # HH:MM\u683c\u5f0f
    is_booked = Column(Boolean, default=False)
    booked_by_appointment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", use_alter=True),
    )
    created_at = Column(DateTime, default=datetime.now)
    
    # \u5173\u7cfb
    stylist = relationship("Stylist", back_populates="time_slots")
    appointment = relationship("Appointment", foreign_keys="[StylistTimeSlot.booked_by_appointment_id]", uselist=False)

class Appointment(Base):
    """\u9884\u7ea6\u8868"""
    __tablename__ = "appointments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    stylist_id = Column(UUID(as_uuid=True), ForeignKey("stylists.id"), nullable=False)
    time_slot_id = Column(UUID(as_uuid=True), ForeignKey("stylist_time_slots.id"), nullable=False)
    
    service = Column(String(100), nullable=False)  # \u670d\u52a1\u7c7b\u578b\uff08\u70eb\u3001\u67d3\u7b49\uff09
    notes = Column(Text)  # \u7279\u6b8a\u8bf7\u6c42
    status = Column(SQLEnum(AppointmentStatus), default=AppointmentStatus.PENDING)
    
    appointment_datetime = Column(DateTime, nullable=False)  # \u8ba1\u7b97\u5b57\u6bb5\uff1adate + time
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # \u5173\u7cfb
    customer = relationship("User", back_populates="appointments", foreign_keys=[customer_id])
    stylist = relationship("Stylist", back_populates="appointments")
    time_slot = relationship("StylistTimeSlot", foreign_keys="[Appointment.time_slot_id]")
    transaction = relationship("Transaction", uselist=False, back_populates="appointment")

class Member(Base):
    """\u4f1a\u5458\u8868"""
    __tablename__ = "members"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    level = Column(SQLEnum(MemberLevel), default=MemberLevel.SILVER)
    points = Column(Integer, default=0)
    birthday_bonus_claimed = Column(Boolean, default=False)
    joined_date = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, default=lambda: datetime.now() + timedelta(days=365))
    
    # \u5173\u7cfb
    user = relationship("User", back_populates="member")

class Transaction(Base):
    """\u4ea4\u6613\u8d26\u5355\u8868"""
    __tablename__ = "transactions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id"))
    
    amount = Column(Float, nullable=False)
    service = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)
    
    # \u5173\u7cfb
    user = relationship("User", back_populates="transactions")
    appointment = relationship("Appointment", back_populates="transaction")

class ReminderLog(Base):
    """\u5ba2\u6237\u7ef4\u62a4\u63d0\u9192\u8bb0\u5f55

    \u7559\u5b58 Agent \u6bcf\u65e5\u626b\u63cf\u540e\u5199\u5165\u5f85\u529e\uff1b\u53d1\u578b\u5e08\u5728\u5de5\u4f5c\u53f0\u770b\u5230\u540e\u7528\u81ea\u5df1\u5fae\u4fe1\u8054\u7cfb\u5ba2\u6237\uff0c
    \u8054\u7cfb\u5b8c\u70b9\u300c\u5df2\u8054\u7cfb\u300d\u3002\u8fd9\u5f20\u8868\u540c\u65f6\u662f\u65e5\u540e\u8ba1\u7b97\u53ec\u56de\u7387\u7684\u6570\u636e\u6e90\u3002
    """
    __tablename__ = "reminder_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    stylist_id = Column(UUID(as_uuid=True), ForeignKey("stylists.id"))  # \u5f52\u5c5e\u53d1\u578b\u5e08\uff0c\u53ef\u80fd\u4e3a\u7a7a\uff08\u65b0\u5ba2\u6237\u8fd8\u6ca1\u56fa\u5b9a\u53d1\u578b\u5e08\uff09

    reminder_type = Column(SQLEnum(ReminderType), nullable=False)
    status = Column(SQLEnum(ReminderStatus), default=ReminderStatus.PENDING)
    priority = Column(Integer, default=0)  # \u6570\u5b57\u8d8a\u5927\u8d8a\u4f18\u5148\uff0c\u6d41\u5931\u9884\u8b66\u6700\u9ad8

    reason = Column(String(255))       # \u547d\u4e2d\u539f\u56e0\uff0c\u7ed9\u53d1\u578b\u5e08\u770b\uff1a\u5982\u300c\u8ddd\u4e0a\u6b21\u5230\u5e97 42 \u5929\uff0c\u4e2a\u4eba\u8282\u594f\u7ea6 25 \u5929\u300d
    suggested_message = Column(Text)   # \u5efa\u8bae\u8bdd\u672f\uff0c\u53d1\u578b\u5e08\u53ef\u76f4\u63a5\u590d\u5236\u6216\u6539\u5199

    reference_date = Column(DateTime)  # \u89e6\u53d1\u4f9d\u636e\u7684\u65f6\u95f4\uff1a\u590d\u8d2d=\u4e0a\u6b21\u5230\u5e97\uff0c\u751f\u65e5=\u4eca\u5e74\u751f\u65e5\u5f53\u5929
    created_at = Column(DateTime, default=datetime.now)
    contacted_at = Column(DateTime)

    # \u5173\u7cfb
    customer = relationship("User", foreign_keys=[customer_id])
    stylist = relationship("Stylist", foreign_keys=[stylist_id])


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    balance_cents = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    user = relationship("User", back_populates="wallet_account")
    transactions = relationship("WalletTransaction", back_populates="wallet")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("wallet_accounts.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    direction = Column(SQLEnum(WalletDirection), nullable=False)
    transaction_type = Column(SQLEnum(WalletTransactionType), nullable=False)
    balance_after_cents = Column(Integer, nullable=False)
    reference_type = Column(String(50))
    reference_id = Column(String(36))
    note = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)

    wallet = relationship("WalletAccount", back_populates="transactions")
    user = relationship("User", back_populates="wallet_transactions")


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    status = Column(SQLEnum(RefundStatus), default=RefundStatus.PENDING, nullable=False)
    reason = Column(String(255))
    processed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.now)
    processed_at = Column(DateTime)

    user = relationship("User", back_populates="refund_requests", foreign_keys=[user_id])
    processor = relationship("User", foreign_keys=[processed_by])


class PointTransaction(Base):
    __tablename__ = "point_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=False)
    source_type = Column(String(50))
    source_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", back_populates="point_transactions")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    kind = Column(SQLEnum(NotificationKind), nullable=False)
    title = Column(String(100), nullable=False)
    body = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    read_at = Column(DateTime)

    user = relationship("User", back_populates="notifications")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    actor = relationship("User", back_populates="audit_logs")


class AgentTaskState(Base):
    """Persisted state for future LangGraph tool workflows and approvals."""

    __tablename__ = "agent_task_states"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    workflow_type = Column(String(100), nullable=False)
    status = Column(SQLEnum(AgentTaskStatus), default=AgentTaskStatus.PENDING, nullable=False)
    input_payload = Column(Text)
    result_payload = Column(Text)
    awaiting_confirmation = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    requester = relationship("User", back_populates="agent_task_states")
