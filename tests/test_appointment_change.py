import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import (
    Appointment,
    AppointmentStatus,
    AuditLog,
    Notification,
    User,
    UserRole,
    StylistTimeSlot,
)
from backend.auth.security import hash_password
from backend.agents.appointment_change_graph import build_appointment_change_graph


client = TestClient(app)


def _staff_headers():
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.STYLIST).first()
        staff.password_hash = hash_password("StaffPass123!")
        db.commit()
        phone = staff.phone
    finally:
        db.close()
    token = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_appointment():
    db = SessionLocal()
    try:
        appointment = db.query(Appointment).first()
        if appointment:
            return appointment.id, appointment.time_slot_id, appointment.customer_id
        customer = User(name="预约客户", phone="13970000002", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        stylist = db.query(User).filter(User.role == UserRole.STYLIST).first().stylist_info
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.stylist_id == stylist.id, StylistTimeSlot.is_booked == False).first()
        appointment = Appointment(
            id=uuid.uuid4(), customer_id=customer.id, stylist_id=stylist.id, time_slot_id=slot.id,
            service="护理", appointment_datetime=datetime.now(), status=AppointmentStatus.CONFIRMED,
        )
        slot.is_booked = True
        slot.booked_by_appointment_id = appointment.id
        db.add(appointment)
        db.commit()
        return appointment.id, appointment.time_slot_id, appointment.customer_id
    finally:
        db.close()


def _propose_without_confirmation():
    assert build_appointment_change_graph() is not None
    appointment_id, old_slot_id, _ = _create_appointment()
    db = SessionLocal()
    try:
        new_slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.is_booked == False, StylistTimeSlot.id != old_slot_id).first()
        new_slot_id = new_slot.id
    finally:
        db.close()

    headers = _staff_headers()
    proposal = client.post(
        "/api/staff/agent/appointment-change/propose",
        headers=headers,
        json={"appointment_id": str(appointment_id), "new_slot_id": str(new_slot_id)},
    )
    assert proposal.status_code == 200, proposal.text
    task_id = proposal.json()["task_id"]

    db = SessionLocal()
    try:
        stored = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert stored.time_slot_id == old_slot_id
    finally:
        db.close()
    return headers, task_id, appointment_id, new_slot_id


def test_proposal_does_not_write_until_confirmation():
    _, _, appointment_id, _ = _propose_without_confirmation()
    db = SessionLocal()
    try:
        assert db.query(Appointment).filter(Appointment.id == appointment_id).one().status == AppointmentStatus.CONFIRMED
    finally:
        db.close()


def test_confirmed_change_updates_appointment_and_customer_notification():
    headers, task_id, appointment_id, new_slot_id = _propose_without_confirmation()
    confirmed = client.post(
        f"/api/staff/agent/tasks/{task_id}/confirm",
        headers=headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed"

    db = SessionLocal()
    try:
        stored = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert stored.time_slot_id == new_slot_id
        assert db.query(Notification).filter(Notification.user_id == stored.customer_id).count() == 1
        old_slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.booked_by_appointment_id == appointment_id,
            StylistTimeSlot.id != new_slot_id,
        ).first()
        assert old_slot is None
        assert db.query(AuditLog).filter(
            AuditLog.action == "appointment.agent_change_confirmed",
            AuditLog.entity_id == str(appointment_id),
        ).count() == 1
    finally:
        db.close()


def test_rejecting_proposal_does_not_change_appointment_or_slots():
    headers, task_id, appointment_id, new_slot_id = _propose_without_confirmation()
    rejected = client.post(
        f"/api/staff/agent/tasks/{task_id}/confirm",
        headers=headers,
        json={"confirmed": False},
    )

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "completed"
    assert rejected.json()["awaiting_confirmation"] is False

    db = SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert appointment.time_slot_id != new_slot_id
        assert db.query(StylistTimeSlot).filter(
            StylistTimeSlot.id == new_slot_id,
            StylistTimeSlot.is_booked.is_(True),
        ).count() == 0
        assert db.query(Notification).filter(Notification.user_id == appointment.customer_id).count() == 0
    finally:
        db.close()


def test_repeated_confirmation_is_rejected():
    headers, task_id, appointment_id, _ = _propose_without_confirmation()
    confirmed = client.post(
        f"/api/staff/agent/tasks/{task_id}/confirm",
        headers=headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text

    repeated = client.post(
        f"/api/staff/agent/tasks/{task_id}/confirm",
        headers=headers,
        json={"confirmed": True},
    )
    assert repeated.status_code == 409


def test_confirmation_rechecks_new_slot_and_rolls_back_when_it_is_taken():
    headers, task_id, appointment_id, new_slot_id = _propose_without_confirmation()
    db = SessionLocal()
    try:
        original = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.id == new_slot_id).one()
        other_customer = User(name="并发客户", phone="13970000007", role=UserRole.CUSTOMER)
        db.add(other_customer)
        db.flush()
        other_appointment = Appointment(
            id=uuid.uuid4(),
            customer_id=other_customer.id,
            stylist_id=slot.stylist_id,
            time_slot_id=slot.id,
            service="护理",
            appointment_datetime=datetime.strptime(
                f"{slot.date} {slot.time}", "%Y-%m-%d %H:%M"
            ),
            status=AppointmentStatus.CONFIRMED,
        )
        db.add(other_appointment)
        slot.is_booked = True
        slot.booked_by_appointment_id = other_appointment.id
        db.commit()
        old_slot_id = original.time_slot_id
    finally:
        db.close()

    conflict = client.post(
        f"/api/staff/agent/tasks/{task_id}/confirm",
        headers=headers,
        json={"confirmed": True},
    )
    assert conflict.status_code == 409, conflict.text

    db = SessionLocal()
    try:
        stored = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert stored.time_slot_id == old_slot_id
        assert db.query(Notification).filter(Notification.user_id == stored.customer_id).count() == 0
    finally:
        db.close()
