import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import (
    Appointment,
    AppointmentStatus,
    Stylist,
    StylistTimeSlot,
    Transaction,
    User,
    UserRole,
)
from backend.main import app


client = TestClient(app)
PASSWORD = "StrongPass123!"


def _register(phone: str):
    registered = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": "安全回归客户", "password": PASSWORD},
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_customer_cannot_self_record_consumption_or_points():
    phone = "13990000001"
    headers = _register(phone)

    response = client.post(
        "/api/transactions",
        headers=headers,
        json={"phone": phone, "amount": 9999, "service": "未核验服务"},
    )

    assert response.status_code == 410
    db = SessionLocal()
    try:
        customer = db.query(User).filter(User.phone == phone).one()
        assert db.query(Transaction).filter(Transaction.user_id == customer.id).count() == 0
        assert customer.total_spent in (None, 0)
    finally:
        db.close()


def test_customer_cannot_choose_member_level_or_invalid_real_birthday():
    phone = "13990000002"
    headers = _register(phone)

    invalid_birthday = client.post(
        "/api/members",
        headers=headers,
        json={"phone": phone, "birthday": "02-31", "level": "platinum"},
    )
    assert invalid_birthday.status_code == 422

    valid = client.post(
        "/api/members",
        headers=headers,
        json={"phone": phone, "name": "安全回归客户", "birthday": "02-28", "level": "platinum"},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["level"] == "silver"


def test_customer_cannot_cancel_completed_appointment():
    phone = "13990000003"
    db = SessionLocal()
    try:
        customer = User(
            id=uuid.uuid4(),
            name="已完成预约客户",
            phone=phone,
            role=UserRole.CUSTOMER,
            password_hash=hash_password(PASSWORD),
            is_active=True,
        )
        db.add(customer)
        db.flush()
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.is_booked.is_(False)).first()
        appointment = Appointment(
            id=uuid.uuid4(),
            customer_id=customer.id,
            stylist_id=stylist.id,
            time_slot_id=slot.id,
            service="护理",
            appointment_datetime=datetime.now(),
            status=AppointmentStatus.COMPLETED,
        )
        db.add(appointment)
        db.commit()
        appointment_id = str(appointment.id)
    finally:
        db.close()

    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.delete(f"/api/appointments/{appointment_id}", headers=headers)

    assert response.status_code == 409


def test_inactive_customer_cannot_login():
    phone = "13990000004"
    db = SessionLocal()
    try:
        db.add(User(
            id=uuid.uuid4(),
            name="停用客户",
            phone=phone,
            role=UserRole.CUSTOMER,
            password_hash=hash_password(PASSWORD),
            is_active=False,
        ))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": PASSWORD},
    )

    assert response.status_code == 401
