"""客户预约管理\u670d\u52a1\uff08\u5df2与 PostgreSQL 集成\uff09"""

from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

from src.database.connection import SessionLocal
from src.database.service import (
    UserService, StylistService, TimeSlotService, 
    AppointmentService, MemberService
)

class ClientAppointmentService:
    """\u5ba2\u6237\u9884\u7ea6\u670d\u52a1"""
    
    @staticmethod
    def search_stylists_by_service(service_type: str) -> List[Dict[str, Any]]:
        """
        \u6839\u636e\u670d\u52a1\u7c7b\u578b\u641c\u7d22\u53d1\u578b\u5e08
        \u6574\u5408 RAG \u77e5\u8bc6\u5e93\u4e0e PostgreSQL \u6570\u636e
        """
        logger.info(f"\ud83d\udd0d \u641c\u7d22\u64cd\u957f '{service_type}' \u7684\u53d1\u578b\u5e08...")
        
        db = SessionLocal()
        try:
            stylists = StylistService.search_stylists_by_specialty(db, service_type)
            
            result = []
            for stylist in stylists:
                result.append({
                    "stylist_id": str(stylist.id),
                    "name": stylist.user.name,
                    "phone": stylist.user.phone,
                    "specialty": stylist.specialty,
                    "experience_years": stylist.experience_years,
                    "rating": stylist.rating,
                    "bio": stylist.bio or "\u5f8a\u4e1a\u53d1\u578b\u5e08"
                })
            
            logger.info(f"\u2705 \u627e\u5230 {len(result)} \u4e2a\u53d1\u578b\u5e08")
            return result
        finally:
            db.close()
    
    @staticmethod
    def get_stylist_available_slots(stylist_id: str, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """
        \u83b7\u53d6\u53d1\u578b\u5e08\u7684\u53ef\u7528\u65f6\u95f4\u69fd
        \u8fd9\u4e9b\u65f6\u95f4\u69fd\u662f\u5b9e\u65f6\u4ece PostgreSQL \u9884\u8ba2\u7684
        """
        logger.info(f"\ud83d\udcc5 \u83b7\u53d6\u53d1\u578b\u5e08 {stylist_id} \u7684\u53ef\u7528\u65f6\u95f4\u69fd...")
        
        db = SessionLocal()
        try:
            slots = TimeSlotService.get_available_slots(db, stylist_id, days_ahead=days_ahead)
            logger.info(f"\u2705 \u627e\u5230 {len(slots)} \u4e2a\u53ef\u7528\u65f6\u95f4\u69fd")
            return slots
        finally:
            db.close()
    
    @staticmethod
    def book_appointment(customer_phone: str, customer_name: str, stylist_id: str, 
                        slot_id: str, service: str, notes: str = None) -> Dict[str, Any]:
        """
        \u9884\u8ba2\u9884\u7ea6\uff08\u5b9e\u65f6\u540c\u6b65 PostgreSQL\uff09
        \n        \u6574\u4e2a\u6d41\u7a0b\uff1a
        1. \u9a8c\u8bc1/\u521b\u5efa\u5ba2\u6237
        2. \u68c0\u67e5\u65f6\u95f4\u69fd\u662f\u5426\u4eea\u53ef\u7528
        3. \u521b\u5efa\u9884\u7ea6\u8bb0\u5f55
        4. \u9884\u8ba2\u65f6\u95f4\u69fd\uff08\u6807\u8bb0\u4e3a\u5df2\u9884\u7ea6\uff09
        5. \u7a0b\u5e8f\u5ba2\u6237/\u53d1\u578b\u5e08\u90fd\u80fd\u5373\u65f6\u770b\u5230\u65e5\u7a0b
        """
        logger.info(f"\ud83d\udcc5 \u9884\u8ba2: {customer_name} -> {stylist_id}")
        
        db = SessionLocal()
        try:
            # \u6b65\u9aa41\uff1a\u9a8c\u8bc1/\u521b\u5efa\u5ba2\u6237
            customer = UserService.create_or_get_customer(
                db, phone=customer_phone, name=customer_name
            )
            logger.info(f"\ud83c\udc61 \u5ba2\u6237: {customer.name} ({customer.id})")
            
            # \u6b65\u9aa42\uff1a\u68c0\u67e5\u65f6\u95f4\u69fd
            from src.database.models import StylistTimeSlot
            slot = db.query(StylistTimeSlot).filter(
                StylistTimeSlot.id == uuid.UUID(slot_id)
            ).first()
            
            if not slot or slot.is_booked:
                logger.warning("\u26a0\ufe0f \u65f6\u95f4\u69fd\u5df2\u88ab\u9884\u8ba2")
                return {
                    "success": False,
                    "error": "\u65f6\u95f4\u69fd\u5df2\u88ab\u9884\u8ba2",
                    "code": "SLOT_BOOKED"
                }
            
            # \u6b65\u9aa43+4\uff1a\u521b\u5efa\u9884\u7ea6 + \u9884\u8ba2\u65f6\u95f4\u69fd
            appointment = AppointmentService.create_appointment(
                db,
                customer_id=str(customer.id),
                stylist_id=stylist_id,
                slot_id=slot_id,
                service=service,
                notes=notes
            )
            
            if not appointment:
                return {
                    "success": False,
                    "error": "\u9884\u8ba2\u5931\u8d25",
                    "code": "APPOINTMENT_FAILED"
                }
            
            logger.info(f"\u2705 \u9884\u8ba2\u6210\u529f: {appointment.id}")
            
            return {
                "success": True,
                "appointment_id": str(appointment.id),
                "customer_id": str(customer.id),
                "stylist_id": stylist_id,
                "service": service,
                "appointment_datetime": appointment.appointment_datetime.isoformat(),
                "status": appointment.status.value,
                "created_at": appointment.created_at.isoformat()
            }
        
        except Exception as e:
            logger.error(f"\u274c \u9884\u8ba2\u5931\u8d25: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "code": "INTERNAL_ERROR"
            }
        finally:
            db.close()
    
    @staticmethod
    def get_customer_appointments(customer_phone: str) -> List[Dict[str, Any]]:
        """
        \u83b7\u53d6\u5ba2\u6237\u7684\u6240\u6709\u9884\u7ea6
        """
        logger.info(f"\ud83d\udcc5 \u83b7\u53d6\u5ba2\u6237 {customer_phone} \u7684\u6240\u6709\u9884\u7ea6...")
        
        db = SessionLocal()
        try:
            from src.database.models import User
            customer = db.query(User).filter(
                User.phone == customer_phone
            ).first()
            
            if not customer:
                return []
            
            appointments = AppointmentService.get_appointments_by_customer(db, str(customer.id))
            
            result = [
                {
                    "appointment_id": str(apt.id),
                    "stylist_name": apt.stylist.user.name,
                    "service": apt.service,
                    "appointment_datetime": apt.appointment_datetime.isoformat(),
                    "status": apt.status.value
                }
                for apt in appointments
            ]
            
            logger.info(f"\u2705 \u627e\u5230 {len(result)} \u6761\u9884\u7ea6")
            return result
        finally:
            db.close()

# \u5168\u5c40\u5ba2\u6237\u9884\u7ea6\u670d\u52a1\u5b9e\u4f8b
client_appointment_service = ClientAppointmentService()
