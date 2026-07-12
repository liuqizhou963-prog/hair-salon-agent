import uuid

from backend.database.connection import SessionLocal
from backend.database.models import Appointment, Stylist, StylistTimeSlot, User, UserRole
from backend.database.service import AppointmentService


def test_same_slot_can_only_be_claimed_once():
    db = SessionLocal()
    try:
        customer = User(id=uuid.uuid4(), name="并发测试客户", phone="13980000001", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.is_booked.is_(False)).first()
        assert customer is not None
        assert stylist is not None
        assert slot is not None

        first = AppointmentService.create_appointment(
            db, str(customer.id), str(stylist.id), str(slot.id), "剪发"
        )
        second = AppointmentService.create_appointment(
            db, str(customer.id), str(stylist.id), str(slot.id), "染发"
        )

        assert first is not None
        assert second is None
        assert db.query(Appointment).filter(Appointment.time_slot_id == slot.id).count() == 1
        db.refresh(slot)
        assert slot.is_booked is True
    finally:
        db.close()


def test_booking_rejects_a_slot_belonging_to_another_stylist():
    db = SessionLocal()
    try:
        customer = User(id=uuid.uuid4(), name="并发测试客户", phone="13980000001", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        stylists = db.query(Stylist).all()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.is_booked.is_(False)).first()
        assert customer is not None and len(stylists) >= 2 and slot is not None
        other_stylist = next(item for item in stylists if item.id != slot.stylist_id)

        appointment = AppointmentService.create_appointment(
            db, str(customer.id), str(other_stylist.id), str(slot.id), "剪发"
        )

        assert appointment is None
        assert db.query(Appointment).filter(Appointment.time_slot_id == slot.id).count() == 0
    finally:
        db.close()