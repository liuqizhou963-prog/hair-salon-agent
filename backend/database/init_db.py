"""数据库\u521d\u59cb\u5316\u811a\u672c"""

from loguru import logger
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid

from backend.database.connection import init_db, drop_all_tables, SessionLocal
from backend.database.models import (
    User, Stylist, StylistTimeSlot, Appointment,
    UserRole, AppointmentStatus,
)
from backend.database.service import (
    StylistService, TimeSlotService, UserService, MemberService
)
from backend.auth.security import hash_password
from backend.config import settings

def init_database():
    """\u521b\u59cb\u5316\u6570\u636e\u5e93\u8868\u7ed3\u6784"""
    logger.info("\ud83d\udd28 \u521b\u5efa\u6570\u636e\u5e93\u8868...")
    init_db()
    logger.info("\u2705 \u6570\u636e\u5e93\u521d\u59cb\u5316\u5b8c\u6210")

def _ensure_stylist(db: Session, data: dict, password: str = "") -> Stylist:
    """按手机号创建或更新示例发型师，避免重复运行初始化脚本产生重复员工。"""
    user = db.query(User).filter(User.phone == data["phone"]).first()
    if user:
        user.name = data["name"]
        user.role = UserRole.STYLIST
        user.is_active = True
        if password:
            user.password_hash = hash_password(password)
        stylist = db.query(Stylist).filter(Stylist.user_id == user.id).first()
        if stylist:
            stylist.specialty = data["specialty"]
            stylist.experience_years = data["years"]
            stylist.is_available = True
            return stylist
    else:
        user = User(
            id=uuid.uuid4(),
            name=data["name"],
            phone=data["phone"],
            role=UserRole.STYLIST,
            password_hash=hash_password(password) if password else None,
            is_active=True,
        )
        db.add(user)
        db.flush()

    stylist = Stylist(
        id=uuid.uuid4(),
        user_id=user.id,
        specialty=data["specialty"],
        experience_years=data["years"],
        is_available=True,
    )
    db.add(stylist)
    db.flush()
    return stylist


def seed_sample_data(days_ahead: int = 30):
    """\u586b\u5145\u793a\u4f8b\u6570\u636e"""
    logger.info("\ud83c\udfe8 \u586b\u5145\u793a\u4f8b\u6570\u636e...")
    
    db = SessionLocal()
    
    try:
        # \u521b\u5efa\u793a\u4f8b\u53d1\u578b\u5e08
        stylists_data = [
            {"name": "张三", "phone": "13800001111", "specialty": "烫、染、护理", "years": 5},
            {"name": "李四", "phone": "13800002222", "specialty": "护理、造型", "years": 8},
            {"name": "王五", "phone": "13800003333", "specialty": "烫、护理、头皮", "years": 3},
            {"name": "赵六", "phone": "13800004444", "specialty": "造型、染", "years": 6},
        ]
        
        stylists = []
        for data in stylists_data:
            stylist = _ensure_stylist(db, data, settings.DEMO_STAFF_PASSWORD)
            stylists.append(stylist)
            logger.info(f"\u2705 \u521b\u5efa\u53d1\u578b\u5e08: {data['name']}")
        
        # \u4e3a\u6bcf\u4e2a\u53d1\u578b\u5e08\u751f\u6210\u65f6\u95f4\u69fd
        for stylist in stylists:
            TimeSlotService.generate_time_slots(db, str(stylist.id), days_ahead=days_ahead)
            logger.info(f"\u2705 \u4e3a {stylist.user.name} \u751f\u6210\u65f6\u95f4\u69fd")

        if settings.DEMO_ADMIN_PHONE and settings.DEMO_ADMIN_PASSWORD:
            admin = db.query(User).filter(User.phone == settings.DEMO_ADMIN_PHONE).first()
            if not admin:
                admin = User(
                    id=uuid.uuid4(),
                    name=settings.DEMO_ADMIN_NAME,
                    phone=settings.DEMO_ADMIN_PHONE,
                    role=UserRole.ADMIN,
                    password_hash=hash_password(settings.DEMO_ADMIN_PASSWORD),
                    is_active=True,
                )
                db.add(admin)
            else:
                admin.name = settings.DEMO_ADMIN_NAME
                admin.role = UserRole.ADMIN
                admin.password_hash = hash_password(settings.DEMO_ADMIN_PASSWORD)
                admin.is_active = True
            db.commit()
            logger.info(f"\u2705 \u6f14\u793a\u7ba1\u7406\u5458\u5df2\u5c31\u7eea: {settings.DEMO_ADMIN_PHONE}")
        
        logger.info("\u2705 \u793a\u4f8b\u6570\u636e\u586b\u5145\u5b8c\u6210")
        
    except Exception as e:
        logger.error(f"\u274c \u586b\u5145\u793a\u4f8b\u6570\u636e\u5931\u8d25: {str(e)}")
        db.rollback()
    finally:
        db.close()

def _make_past_appointment(db, customer, stylist, days_ago, service):
    """\u9020\u4e00\u6761\u5df2\u53d1\u751f\u7684\u5386\u53f2\u9884\u7ea6\uff08\u8fde\u5e26\u4e00\u4e2a\u5df2\u5360\u7528\u7684\u8fc7\u53bb\u65f6\u95f4\u69fd\uff09"""
    dt = datetime.now() - timedelta(days=days_ago)
    slot = StylistTimeSlot(
        id=uuid.uuid4(),
        stylist_id=stylist.id,
        date=dt.strftime("%Y-%m-%d"),
        time=dt.strftime("%H:00"),
        is_booked=True,
    )
    db.add(slot)
    db.flush()
    appt = Appointment(
        id=uuid.uuid4(),
        customer_id=customer.id,
        stylist_id=stylist.id,
        time_slot_id=slot.id,
        service=service,
        status=AppointmentStatus.COMPLETED,
        appointment_datetime=dt,
    )
    db.add(appt)
    db.flush()
    slot.booked_by_appointment_id = appt.id
    return appt


def seed_retention_demo():
    """\u586b\u5145\u7528\u4e8e\u9a8c\u8bc1\u300c\u5ba2\u6237\u7ef4\u62a4 agent\u300d\u7684\u793a\u4f8b\u5ba2\u6237\u3002

    \u6545\u610f\u9020\u51fa\u51e0\u79cd\u60c5\u51b5\uff0c\u626b\u63cf\u540e\u5e94\u5404\u547d\u4e2d\u4e00\u6761\uff1a
      - \u738b\u590d\u8d2d\uff1a\u67d3\u53d1\u5ba2\uff0c\u4e2a\u4eba\u8282\u594f ~25 \u5929\uff0c\u5df2 35 \u5929\u6ca1\u6765 \u2192 \u590d\u8d2d\u63d0\u9192
      - \u674e\u751f\u65e5\uff1a\u751f\u65e5\u5c31\u5728\u6700\u8fd1\u51e0\u5929 \u2192 \u751f\u65e5\u63d0\u9192
      - \u5f20\u6d41\u5931\uff1a\u70eb\u53d1\u5ba2\uff0c\u4e2a\u4eba\u8282\u594f ~50 \u5929\uff0c\u5df2 140 \u5929\u6ca1\u6765 \u2192 \u6d41\u5931\u9884\u8b66
      - \u9648\u6b63\u5e38\uff1a\u521a\u6765\u8fc7\uff0c\u4e0d\u8be5\u88ab\u6253\u6270 \u2192 \u4e0d\u547d\u4e2d\uff08\u9a8c\u8bc1\u4e0d\u8bef\u62a5\uff09
    """
    logger.info("\ud83e\uddea \u586b\u5145\u7559\u5b58\u9a8c\u8bc1\u793a\u4f8b\u5ba2\u6237...")
    db = SessionLocal()
    try:
        stylists = db.query(Stylist).all()
        if not stylists:
            logger.warning("\u26a0\ufe0f \u6ca1\u6709\u53d1\u578b\u5e08\uff0c\u8bf7\u5148\u8dd1 seed_sample_data")
            return
        s = stylists[0]

        today = datetime.now()
        soon = (today + timedelta(days=3)).strftime("%m-%d")  # 3 \u5929\u540e\u751f\u65e5

        demo = [
            {"name": "\u738b\u590d\u8d2d", "phone": "13900000001", "birthday": "01-01",
             "gaps": [25, 26, 24], "last": 35, "service": "\u67d3\u53d1"},
            {"name": "\u674e\u751f\u65e5", "phone": "13900000002", "birthday": soon,
             "gaps": [30, 28], "last": 20, "service": "\u62a4\u7406"},
            {"name": "\u5f20\u6d41\u5931", "phone": "13900000003", "birthday": "06-15",
             "gaps": [52, 48, 50], "last": 140, "service": "\u70eb\u53d1"},
            {"name": "\u9648\u6b63\u5e38", "phone": "13900000004", "birthday": "12-31",
             "gaps": [30, 30], "last": 5, "service": "\u526a\u53d1"},
        ]

        for d in demo:
            user = db.query(User).filter(User.phone == d["phone"]).first()
            if not user:
                user = User(
                    id=uuid.uuid4(), name=d["name"], phone=d["phone"],
                    role=UserRole.CUSTOMER, birthday=d["birthday"],
                )
                db.add(user)
                db.flush()

            # gaps \u662f\u5386\u6b21\u5230\u5e97\u7684\u95f4\u9694\uff08\u5929\uff09\uff0c\u6362\u7b97\u6210\u6bcf\u6b21\u5230\u5e97\u8ddd\u4eca\u591a\u5c11\u5929
            offsets = [d["last"]]
            acc = d["last"]
            for g in d["gaps"]:
                acc += g
                offsets.append(acc)
            for days_ago in sorted(offsets, reverse=True):
                _make_past_appointment(db, user, s, days_ago, d["service"])

            user.last_visit = today - timedelta(days=d["last"])
            logger.info(f"\u2705 \u9020\u793a\u4f8b\u5ba2\u6237: {d['name']}\uff08\u4e0a\u6b21\u5230\u5e97 {d['last']} \u5929\u524d\uff09")

        db.commit()
        logger.info("\u2705 \u7559\u5b58\u9a8c\u8bc1\u793a\u4f8b\u5ba2\u6237\u586b\u5145\u5b8c\u6210")
    except Exception as e:
        db.rollback()
        logger.error(f"\u274c \u586b\u5145\u7559\u5b58\u793a\u4f8b\u5931\u8d25: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # \u9700\u8981\u7684\u65f6\u5019\u4e0d\u6ce8\u91ca\u8fd9\u4e00\u884c
    # drop_all_tables()

    init_database()
    seed_sample_data()
    seed_retention_demo()

    logger.info("\ud83d\udce3 \u6570\u636e\u5e93\u521d\u59cb\u5316\u5b8c\u6210\uff01")
