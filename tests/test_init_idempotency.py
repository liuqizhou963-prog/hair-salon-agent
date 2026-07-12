from backend.database.connection import SessionLocal
from backend.database.init_db import seed_sample_data
from backend.database.models import Stylist, User


def test_sample_staff_seed_is_idempotent():
    seed_sample_data(days_ahead=7)
    db = SessionLocal()
    try:
        first_stylist_count = db.query(Stylist).count()
        first_staff_phones = {
            user.phone for user in db.query(User).filter(User.phone.like("1380000%"))
        }
    finally:
        db.close()

    seed_sample_data(days_ahead=7)
    db = SessionLocal()
    try:
        assert db.query(Stylist).count() == first_stylist_count
        assert {
            user.phone for user in db.query(User).filter(User.phone.like("1380000%"))
        } == first_staff_phones
    finally:
        db.close()

