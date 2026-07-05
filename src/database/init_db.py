"""数据库\u521d\u59cb\u5316\u811a\u672c"""

from loguru import logger
from sqlalchemy.orm import Session
import uuid

from src.database.connection import init_db, drop_all_tables, SessionLocal
from src.database.models import (
    User, Stylist, StylistTimeSlot, UserRole
)
from src.database.service import (
    StylistService, TimeSlotService, UserService, MemberService
)

def init_database():
    """\u521b\u59cb\u5316\u6570\u636e\u5e93\u8868\u7ed3\u6784"""
    logger.info("\ud83d\udd28 \u521b\u5efa\u6570\u636e\u5e93\u8868...")
    init_db()
    logger.info("\u2705 \u6570\u636e\u5e93\u521d\u59cb\u5316\u5b8c\u6210")

def seed_sample_data():
    """\u586b\u5145\u793a\u4f8b\u6570\u636e"""
    logger.info("\ud83c\udfe8 \u586b\u5145\u793a\u4f8b\u6570\u636e...")
    
    db = SessionLocal()
    
    try:
        # \u521b\u5efa\u793a\u4f8b\u53d1\u578b\u5e08
        stylists_data = [
            {"name": "\u5f20\u4e5f", "phone": "13800001111", "specialty": "\u70eb\u3001\u67d3\u3001\u62a4\u7406", "years": 5},
            {"name": "\u674e\u4e19", "phone": "13800002222", "specialty": "\u70eb\u3001\u9020\u578b", "years": 3},
            {"name": "\u738b\u4e94", "phone": "13800003333", "specialty": "\u62a4\u7406\u3001\u67d3\u3001\u9020\u578b", "years": 4},
        ]
        
        stylists = []
        for data in stylists_data:
            stylist = StylistService.create_stylist(
                db,
                name=data["name"],
                phone=data["phone"],
                specialty=data["specialty"],
                experience_years=data["years"]
            )
            stylists.append(stylist)
            logger.info(f"\u2705 \u521b\u5efa\u53d1\u578b\u5e08: {data['name']}")
        
        # \u4e3a\u6bcf\u4e2a\u53d1\u578b\u5e08\u751f\u6210\u65f6\u95f4\u69fd
        for stylist in stylists:
            TimeSlotService.generate_time_slots(db, str(stylist.id), days_ahead=30)
            logger.info(f"\u2705 \u4e3a {stylist.user.name} \u751f\u6210\u65f6\u95f4\u69fd")
        
        logger.info("\u2705 \u793a\u4f8b\u6570\u636e\u586b\u5145\u5b8c\u6210")
        
    except Exception as e:
        logger.error(f"\u274c \u586b\u5145\u793a\u4f8b\u6570\u636e\u5931\u8d25: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # \u9700\u8981\u7684\u65f6\u5019\u4e0d\u6ce8\u91ca\u8fd9\u4e00\u884c
    # drop_all_tables()
    
    init_database()
    seed_sample_data()
    
    logger.info("\ud83c\udce3 \u6570\u636e\u5e93\u521d\u59cb\u5316\u5b8c\u6210\uff01")
