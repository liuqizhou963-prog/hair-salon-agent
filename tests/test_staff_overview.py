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


def _headers(phone: str):
    login = client.post("/api/auth/login", json={"phone": phone, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _staff_headers():
    phone = "13929999998"
    db = SessionLocal()
    try:
        db.add(User(
            id=uuid.uuid4(),
            name="统计员工",
            phone=phone,
            role=UserRole.STYLIST,
            password_hash=hash_password(PASSWORD),
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    return _headers(phone)


def _customer_headers(phone: str = "13930000008"):
    response = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": "统计客户", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return _headers(phone)


def _add_consumption(customer_phone: str):
    db = SessionLocal()
    try:
        customer = db.query(User).filter(User.phone == customer_phone).one()
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
        ).first()
        appointment = Appointment(
            id=uuid.uuid4(),
            customer_id=customer.id,
            stylist_id=stylist.id,
            time_slot_id=slot.id,
            service="剪发套餐",
            status=AppointmentStatus.COMPLETED,
            appointment_datetime=datetime.now(),
        )
        db.add(appointment)
        db.flush()
        db.add(Transaction(
            id=uuid.uuid4(),
            user_id=customer.id,
            appointment_id=appointment.id,
            amount=88,
            service="剪发套餐",
            created_at=datetime.now(),
        ))
        db.commit()
        return str(stylist.id), stylist.user.name
    finally:
        db.close()


def test_staff_can_see_customer_balance_and_recharge_records():
    customer_headers = _customer_headers()
    client.post("/api/wallet/recharge", headers=customer_headers, json={"amount": 120})
    staff_headers = _staff_headers()

    response = client.get("/api/staff/customer-wallets", headers=staff_headers)

    assert response.status_code == 200, response.text
    customer = next(item for item in response.json() if item["phone"] == "13930000008")
    assert customer["balance"] == 120
    assert customer["recharge_total"] == 120
    assert customer["recharge_count"] == 1
    assert customer["transactions"][0]["transaction_type"] == "recharge"


def test_customer_cannot_access_staff_finance_endpoints():
    customer_headers = _customer_headers("13930000010")

    wallets = client.get("/api/staff/customer-wallets", headers=customer_headers)
    overview = client.get("/api/staff/overview", headers=customer_headers)

    assert wallets.status_code == 403
    assert overview.status_code == 403


def test_staff_overview_groups_today_revenue_and_stylist_performance():
    customer_headers = _customer_headers("13930000009")
    client.post("/api/wallet/recharge", headers=customer_headers, json={"amount": 120})
    stylist_id, stylist_name = _add_consumption("13930000009")
    pending = client.post(
        "/api/refunds",
        headers=customer_headers,
        json={"amount": 20, "reason": "测试退款"},
    )
    assert pending.status_code == 201, pending.text
    staff_headers = _staff_headers()

    response = client.get("/api/staff/overview", headers=staff_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customer_count"] == 1
    assert body["order_count"] == 1
    assert body["consumption"] == 88
    assert body["recharge"] == 120
    assert body["pending_refund"] == 20
    assert body["services"][0]["service"] == "剪发套餐"
    performance = next(item for item in body["performances"] if item["stylist_id"] == stylist_id)
    assert performance["stylist_name"] == stylist_name
    assert performance["stylist_phone"] == "13800001111"
    assert performance["amount"] == 88


def test_staff_can_verify_package_service_and_complete_it_once():
    customer_headers = _customer_headers("13930000011")
    staff_headers = _staff_headers()

    package = client.post(
        "/api/staff/service-packages",
        headers=staff_headers,
        json={"name": "洗剪吹 5 次卡", "service": "洗剪吹", "price": 400, "total_uses": 5},
    )
    assert package.status_code == 201, package.text

    db = SessionLocal()
    try:
        customer = db.query(User).filter(User.phone == "13930000011").one()
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
        ).first()
        appointment = Appointment(
            id=uuid.uuid4(),
            customer_id=customer.id,
            stylist_id=stylist.id,
            time_slot_id=slot.id,
            service="洗剪吹",
            status=AppointmentStatus.CONFIRMED,
            appointment_datetime=datetime.now(),
        )
        db.add(appointment)
        db.commit()
        appointment_id = str(appointment.id)
        customer_id = str(customer.id)
    finally:
        db.close()

    assigned = client.post(
        "/api/staff/customer-packages",
        headers=staff_headers,
        json={"customer_id": customer_id, "package_id": package.json()["package_id"]},
    )
    assert assigned.status_code == 201, assigned.text
    customer_package_id = assigned.json()["customer_package_id"]

    options = client.get(f"/api/staff/appointments/{appointment_id}/verification", headers=staff_headers)
    assert options.status_code == 200, options.text
    assert options.json()["packages"][0]["remaining_uses"] == 5

    verified = client.post(
        f"/api/staff/appointments/{appointment_id}/verify",
        headers=staff_headers,
        json={"customer_package_id": customer_package_id},
    )
    assert verified.status_code == 201, verified.text
    assert verified.json()["status"] == "verified"
    assert verified.json()["amount"] == 80

    verification_id = verified.json()["verification_id"]
    completed = client.post(
        f"/api/staff/service-verifications/{verification_id}/complete",
        headers=staff_headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"

    repeated = client.post(
        f"/api/staff/service-verifications/{verification_id}/complete",
        headers=staff_headers,
    )
    assert repeated.status_code == 200, repeated.text

    packages = client.get(
        "/api/staff/customer-packages",
        params={"customer_id": customer_id},
        headers=staff_headers,
    )
    assert packages.status_code == 200, packages.text
    assert packages.json()[0]["remaining_uses"] == 4

    overview = client.get("/api/staff/overview", headers=staff_headers)
    assert overview.status_code == 200, overview.text
    assert any(item["amount"] == 80 for item in overview.json()["performances"])

    assert client.get(
        f"/api/staff/appointments/{appointment_id}/verification", headers=customer_headers
    ).status_code == 403
