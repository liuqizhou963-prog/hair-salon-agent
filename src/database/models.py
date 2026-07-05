"""数据库模型定义"""

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Enum as SQLEnum, Table, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
import enum

from src.database.connection import Base

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

class User(Base):
    """\u7528\u6237\u8868"""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)
    email = Column(String(100), unique=True)
    role = Column(SQLEnum(UserRole), default=UserRole.CUSTOMER)
    
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
    booked_by_appointment_id = Column(UUID(as_uuid=True), ForeignKey("appointments.id"))
    created_at = Column(DateTime, default=datetime.now)
    
    # \u5173\u7cfb
    stylist = relationship("Stylist", back_populates="time_slots")
    appointment = relationship("Appointment", back_populates="time_slot")

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
    time_slot = relationship("StylistTimeSlot", back_populates="appointment")
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
