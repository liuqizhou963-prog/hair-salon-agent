"""员\u5de5\u65e5\u7a0b\u7ba1\u7406"""

from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.database.connection import SessionLocal
from backend.database.service import AppointmentService, StylistService

class StaffScheduleService:
    """\u5458\u5de5\u65e5\u7a0b\u670d\u52a1"""
    
    @staticmethod
    def get_stylist_schedule(stylist_id: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        \u83b7\u53d6\u53d1\u578b\u5e08\u7684\u65e5\u7a0b
        \n        \u53d1\u578b\u5e08\u53ef\u4ee5\u5e73\u5b9e\u65f6\u67e5\u770b\u4eca\u5929/\u6307\u5b9a\u65e5\u671f\u7684\u6240\u6709\u9884\u7ea6
        """
        logger.info(f"\ud83d\udcc5 \u83b7\u53d6\u53d1\u578b\u5e08 {stylist_id} \u7684\u65e5\u7a0b...")
        
        db = SessionLocal()
        try:
            appointments = AppointmentService.get_appointments_by_stylist(
                db, stylist_id, date=date or datetime.now().strftime("%Y-%m-%d")
            )
            
            result = [
                {
                    "appointment_id": str(apt.id),
                    "customer_name": apt.customer.name,
                    "customer_phone": apt.customer.phone,
                    "stylist_name": apt.stylist.user.name,
                    "service": apt.service,
                    "appointment_datetime": apt.appointment_datetime.isoformat(),
                    "status": apt.service_verification.status.value if apt.service_verification else apt.status.value,
                    "notes": apt.notes
                }
                for apt in appointments
            ]
            
            logger.info(f"\u2705 \u63a5\u4e0b\u6765 {len(result)} \u6761\u9884\u7ea6")
            return result
        finally:
            db.close()
    
    @staticmethod
    def get_salon_schedule(date: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        \u83b7\u53d6\u6574\u4e2a\u9999\u6d1b\u65e5\u7a0b\uff08\u6240\u6709\u53d1\u578b\u5e08\uff09
        """
        logger.info(f"\ud83d\udcc5 \u83b7\u53d6\u9999\u6d1b\u7684\u5168\u91cf\u65e5\u7a0b...")
        
        db = SessionLocal()
        try:
            stylists = StylistService.get_all_stylists(db)
            
            schedule = {}
            for stylist in stylists:
                appointments = AppointmentService.get_appointments_by_stylist(
                    db, str(stylist.id), date=date or datetime.now().strftime("%Y-%m-%d")
                )
                
                schedule[stylist.user.name] = [
                    {
                        "appointment_id": str(apt.id),
                        "customer_name": apt.customer.name,
                        "customer_phone": apt.customer.phone,
                        "service": apt.service,
                        "appointment_datetime": apt.appointment_datetime.isoformat(),
                        "status": apt.service_verification.status.value if apt.service_verification else apt.status.value,
                        "notes": apt.notes,
                    }
                    for apt in appointments
                ]
            
            logger.info(f"\u2705 \u83b7\u53d6\u4e86 {len(stylists)} \u4e2a\u53d1\u578b\u5e08\u7684\u65e5\u7a0b")
            return schedule
        finally:
            db.close()

# \u5168\u5c40\u5458\u5de5\u65e5\u7a0b\u670d\u52a1\u5b9e\u4f8b
staff_schedule_service = StaffScheduleService()
