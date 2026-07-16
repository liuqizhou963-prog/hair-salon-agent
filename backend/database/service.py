"""数据库业务服务层"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from typing import List, Optional
from loguru import logger
import uuid

from backend.database.models import (
    User, Stylist, StylistTimeSlot, Appointment, Member, Transaction,
    UserRole, AppointmentStatus, MemberLevel
)

class UserService:
    """\u7528\u6237\u670d\u52a1"""
    
    @staticmethod
    def create_or_get_customer(db: Session, phone: str, name: str, email: str = None) -> User:
        """\u4f1a\u5458\u67e5\u8be2\u6216\u521b\u5efa"""
        user = db.query(User).filter(User.phone == phone).first()
        
        if not user:
            logger.info(f"\ud83c\udc61 \u521b\u5efa\u65b0\u7528\u6237: {phone}")
            user = User(
                id=uuid.uuid4(),
                phone=phone,
                name=name,
                email=email,
                role=UserRole.CUSTOMER
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            logger.info(f"\ud83d\udcc4 \u627e\u5230\u5df2\u6709\u7528\u6237: {phone}")
        
        return user
    
    @staticmethod
    def get_all_customers(db: Session) -> List[User]:
        """\u83b7\u53d6\u6240\u6709\u5ba2\u6237"""
        return db.query(User).filter(User.role == UserRole.CUSTOMER).all()
    
    @staticmethod
    def get_customer_by_id(db: Session, user_id: str) -> Optional[User]:
        """\u6839\u636eID\u83b7\u53d6\u5ba2\u6237"""
        return db.query(User).filter(User.id == uuid.UUID(user_id)).first()

class StylistService:
    """\u53d1\u578b\u5e08\u670d\u52a1"""
    
    @staticmethod
    def create_stylist(db: Session, name: str, phone: str, specialty: str, experience_years: int = 0) -> Stylist:
        """\u521b\u5efa\u53d1\u578b\u5e08"""
        logger.info(f"\ud83d\udc87 \u521b\u5efa\u53d1\u578b\u5e08: {name}")
        
        # \u5148\u521b\u5efa\u7528\u6237
        user = User(
            id=uuid.uuid4(),
            phone=phone,
            name=name,
            role=UserRole.STYLIST
        )
        db.add(user)
        db.flush()
        
        # \u7136\u540e\u521b\u5efa\u53d1\u578b\u5e08\u8bb0\u5f55
        stylist = Stylist(
            id=uuid.uuid4(),
            user_id=user.id,
            specialty=specialty,
            experience_years=experience_years
        )
        db.add(stylist)
        db.commit()
        db.refresh(stylist)
        
        return stylist
    
    @staticmethod
    def get_all_stylists(db: Session) -> List[Stylist]:
        """\u83b7\u53d6\u6240\u6709\u53d1\u578b\u5e08"""
        return db.query(Stylist).filter(Stylist.is_available == True).all()
    
    @staticmethod
    def get_stylist_by_id(db: Session, stylist_id: str) -> Optional[Stylist]:
        """\u6839\u636eID\u83b7\u53d6\u53d1\u578b\u5e08"""
        return db.query(Stylist).filter(Stylist.id == uuid.UUID(stylist_id)).first()
    
    @staticmethod
    def search_stylists_by_specialty(db: Session, specialty: str) -> List[Stylist]:
        """\u6839\u636e\u64cd\u957f\u53d1\u578b\u641c\u7d22\u53d1\u578b\u5e08"""
        logger.info(f"\ud83d\udd0d \u6839\u636e\u64cd\u957f\u7684\u53d1\u578b\u641c\u7d22: {specialty}")
        return db.query(Stylist).filter(
            Stylist.is_available == True,
            Stylist.specialty.contains(specialty)
        ).all()

class TimeSlotService:
    """\u65f6\u95f4\u69fd\u670d\u52a1"""
    
    @staticmethod
    def generate_time_slots(db: Session, stylist_id: str, days_ahead: int = 7, slot_duration: int = 60):
        """\u4e3a\u53d1\u578b\u5e08\u751f\u6210\u65f6\u95f4\u69fd"""
        logger.info(f"\ud83d\udcc5 \u4e3a\u53d1\u578b\u5e08 {stylist_id} \u751f\u6210 {days_ahead} \u5929\u7684\u65f6\u95f4\u69fd")
        
        stylist_uuid = uuid.UUID(stylist_id)
        start_time = 9  # 9:00 AM
        end_time = 18   # 6:00 PM
        
        today = datetime.now().date()
        
        for day_offset in range(days_ahead):
            date = today + timedelta(days=day_offset)
            
            # \u53ea\u5728\u5de5\u4f5c\u65e5\u521b\u5efa\u65f6\u95f4\u69fd
            if date.weekday() < 5:  # Monday to Friday
                current_hour = start_time
                while current_hour < end_time:
                    time_str = f"{current_hour:02d}:00"
                    
                    # \u68c0\u67e5\u662f\u5426\u5df2\u5b58\u5728
                    existing = db.query(StylistTimeSlot).filter(
                        StylistTimeSlot.stylist_id == stylist_uuid,
                        StylistTimeSlot.date == date.strftime("%Y-%m-%d"),
                        StylistTimeSlot.time == time_str
                    ).first()
                    
                    if not existing:
                        slot = StylistTimeSlot(
                            id=uuid.uuid4(),
                            stylist_id=stylist_uuid,
                            date=date.strftime("%Y-%m-%d"),
                            time=time_str,
                            is_booked=False
                        )
                        db.add(slot)
                    
                    current_hour += 1
        
        try:
            db.commit()
        except IntegrityError:
            # Concurrent initializers may race on the database uniqueness guard.
            # The winning transaction already created the same slots, so retrying
            # the read path is sufficient and avoids surfacing a duplicate error.
            db.rollback()
        logger.info("\u2705 \u65f6\u95f4\u69fd\u751f\u6210\u5b8c\u6210")
    
    @staticmethod
    def get_available_slots(db: Session, stylist_id: str, days_ahead: int = 7) -> List[dict]:
        """\u83b7\u53d6\u53d1\u578b\u5e08\u7684\u53ef\u7528\u65f6\u95f4\u69fd"""
        logger.info(f"\ud83d\udd0d \u83b7\u53d6 {stylist_id} \u7684\u53ef\u7528\u65f6\u95f4\u69fd")
        
        stylist_uuid = uuid.UUID(stylist_id)
        today = datetime.now().date()
        cutoff_date = today + timedelta(days=days_ahead)
        
        slots = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist_uuid,
            StylistTimeSlot.is_booked == False,
            StylistTimeSlot.date >= today.strftime("%Y-%m-%d"),
            StylistTimeSlot.date < cutoff_date.strftime("%Y-%m-%d")
        ).all()
        
        result = [
            {
                "slot_id": str(slot.id),
                "date": slot.date,
                "time": slot.time,
                "datetime_str": f"{slot.date} {slot.time}",
                "is_booked": slot.is_booked
            }
            for slot in slots
        ]
        
        logger.info(f"\u2705 \u627e\u5230 {len(result)} \u4e2a\u53ef\u7528\u65f6\u95f4\u69fd")
        return result
    
    @staticmethod
    def book_time_slot(db: Session, slot_id: str, appointment_id: str) -> bool:
        """Atomically claim an available slot for an existing appointment."""
        logger.info(f"Book time slot: {slot_id}")
        slot_uuid = uuid.UUID(slot_id)
        appointment_uuid = uuid.UUID(appointment_id)
        updated = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.id == slot_uuid,
            StylistTimeSlot.is_booked.is_(False),
        ).update(
            {
                StylistTimeSlot.is_booked: True,
                StylistTimeSlot.booked_by_appointment_id: appointment_uuid,
            },
            synchronize_session=False,
        )
        if updated == 1:
            db.commit()
            logger.info("Time slot booked successfully")
            return True

        db.rollback()
        logger.warning("Time slot was already booked or does not exist")
        return False

class AppointmentService:
    """\u9884\u7ea6\u670d\u52a1"""
    
    @staticmethod
    def create_appointment(db: Session, customer_id: str, stylist_id: str,
                          slot_id: str, service: str, notes: str = None,
                          status: AppointmentStatus = AppointmentStatus.PENDING,
                          commit: bool = True) -> Optional[Appointment]:
        """Create an appointment with an atomic slot claim."""
        logger.info(f"Create appointment: {customer_id} -> {stylist_id}")

        slot_uuid = uuid.UUID(slot_id)
        stylist_uuid = uuid.UUID(stylist_id)
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.id == slot_uuid,
            StylistTimeSlot.stylist_id == stylist_uuid,
        ).first()
        if not slot or slot.is_booked:
            logger.error("Slot is not available")
            return None

        slot_date, slot_time = slot.date, slot.time
        appointment_id = uuid.uuid4()
        claimed = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.id == slot_uuid,
            StylistTimeSlot.stylist_id == stylist_uuid,
            StylistTimeSlot.is_booked.is_(False),
        ).update(
            {StylistTimeSlot.is_booked: True},
            synchronize_session=False,
        )
        if claimed != 1:
            db.rollback()
            logger.warning("Slot was claimed by another request")
            return None

        appointment = Appointment(
            id=appointment_id,
            customer_id=uuid.UUID(customer_id),
            stylist_id=stylist_uuid,
            time_slot_id=slot_uuid,
            service=service,
            notes=notes,
            status=status,
            appointment_datetime=datetime.strptime(f"{slot_date} {slot_time}", "%Y-%m-%d %H:%M"),
        )
        db.add(appointment)
        db.flush()

        # The appointment now exists, so the foreign-key reference is safe.
        slot.is_booked = True
        slot.booked_by_appointment_id = appointment.id

        if commit:
            db.commit()
            db.refresh(appointment)
        else:
            db.flush()
        logger.info(f"Appointment created successfully: {appointment.id}")
        return appointment
    @staticmethod
    def get_appointments_by_customer(db: Session, customer_id: str) -> List[Appointment]:
        """\u83b7\u53d6\u5ba2\u6237\u7684\u9884\u7ea6"""
        return db.query(Appointment).filter(
            Appointment.customer_id == uuid.UUID(customer_id)
        ).all()
    
    @staticmethod
    def get_appointments_by_stylist(db: Session, stylist_id: str, date: str = None) -> List[Appointment]:
        """\u83b7\u53d6\u53d1\u578b\u5e08\u7684\u9884\u7ea6\u65e5\u7a0b"""
        query = db.query(Appointment).filter(
            Appointment.stylist_id == uuid.UUID(stylist_id)
        )
        
        if date:
            query = query.filter(Appointment.appointment_datetime >= datetime.strptime(date, "%Y-%m-%d"))
            query = query.filter(Appointment.appointment_datetime < datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1))
        
        return query.all()
    
    @staticmethod
    def cancel_appointment(db: Session, appointment_id: str) -> bool:
        """\u53d6\u6d88\u9884\u7ea6"""
        logger.info(f"\u274c \u53d6\u6d88\u9884\u7ea6: {appointment_id}")
        
        appointment = db.query(Appointment).filter(
            Appointment.id == uuid.UUID(appointment_id),
            Appointment.status.in_([
                AppointmentStatus.PENDING,
                AppointmentStatus.CONFIRMED,
            ])
        ).first()
        
        if appointment:
            appointment.status = AppointmentStatus.CANCELLED
            
            # \u91ca\u653e\u65f6\u95f4\u69fd
            if appointment.time_slot:
                appointment.time_slot.is_booked = False
                appointment.time_slot.booked_by_appointment_id = None
            
            db.commit()
            logger.info("\u2705 \u9884\u7ea6\u5df2\u53d6\u6d88")
            return True
        
        return False

class MemberService:
    """\u4f1a\u5458\u670d\u52a1"""
    
    @staticmethod
    def create_member(db: Session, user_id: str, level: str = "silver") -> Member:
        """\u521b\u5efa\u4f1a\u5458"""
        logger.info(f"\ud83c\udf89 \u521b\u5efa\u4f1a\u5458: {user_id}")
        
        member = Member(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            level=MemberLevel[level.upper()]
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        
        return member
    
    @staticmethod
    def get_birthday_members_today(db: Session) -> List[Member]:
        """\u83b7\u53d6\u4eca\u5929\u751f\u65e5\u7684\u4f1a\u5458"""
        today = datetime.now().strftime("%m-%d")
        
        return db.query(Member).join(User).filter(
            User.birthday == today
        ).all()
    
    @staticmethod
    def add_points(db: Session, member_id: str, points: int) -> Optional[Member]:
        """\u589e\u52a0\u4f1a\u5458\u79ef\u5206"""
        logger.info(f"\u2795 \u4e3a\u4f1a\u5458 {member_id} \u589e\u52a0 {points} \u79ef\u5206")
        
        member = db.query(Member).filter(Member.id == uuid.UUID(member_id)).first()
        
        if member:
            member.points += points
            db.commit()
            db.refresh(member)
            logger.info(f"\u2705 \u79ef\u5206\u589e\u52a0\u6210\u529f, \u603b\u79ef\u5206: {member.points}")
        
        return member
