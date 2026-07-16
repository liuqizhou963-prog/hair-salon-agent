from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.main import app


client = TestClient(app)


def _staff_headers() -> dict[str, str]:
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.ADMIN).first()
        staff.password_hash = hash_password("StaffPass123!")
        phone = staff.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _employee_headers() -> dict[str, str]:
    db = SessionLocal()
    try:
        employee = db.query(User).filter(User.role == UserRole.STYLIST).first()
        employee.password_hash = hash_password("EmployeePass123!")
        phone = employee.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": phone, "password": "EmployeePass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_staff_booking_is_visible_to_customer_and_stylist_schedule():
    customer_phone = "13970000991"
    customer_password = "StrongPass123!"
    registered = client.post(
        "/api/auth/register",
        json={"phone": customer_phone, "name": "员工代约客户", "password": customer_password},
    )
    assert registered.status_code == 201, registered.text

    manager_headers = _staff_headers()
    employee_headers = _employee_headers()
    customers = client.get("/api/customers", headers=employee_headers)
    assert customers.status_code == 200, customers.text
    customer = next(item for item in customers.json() if item["phone"] == customer_phone)

    stylists = client.get("/api/stylists", headers=employee_headers)
    assert stylists.status_code == 200, stylists.text
    stylist = stylists.json()[0]
    slots = client.get(f"/api/stylists/{stylist['stylist_id']}/slots").json()
    available = next(item for item in slots if not item["is_booked"])

    denied = client.post(
        "/api/staff/appointments",
        headers=employee_headers,
        json={
            "customer_id": customer["customer_id"],
            "stylist_id": stylist["stylist_id"],
            "slot_id": available["slot_id"],
            "service": "剪发",
            "notes": "员工为客户代约",
        },
    )
    assert denied.status_code == 403, denied.text
    audits = client.get("/api/audit-logs", headers=manager_headers)
    assert audits.status_code == 200, audits.text
    assert any(
        item["action"] == "security.permission_denied"
        and "/api/staff/appointments" in (item["details"] or "")
        for item in audits.json()
    )

    booking = client.post(
        "/api/staff/appointments",
        headers=manager_headers,
        json={
            "customer_id": customer["customer_id"],
            "stylist_id": stylist["stylist_id"],
            "slot_id": available["slot_id"],
            "service": "剪发",
            "notes": "店长为客户代约",
        },
    )
    assert booking.status_code == 201, booking.text
    body = booking.json()
    assert body["status"] == "confirmed"
    assert body["customer_phone"] == customer_phone
    assert body["stylist_name"] == stylist["name"]
    appointment_id = body["appointment_id"]

    schedule = client.get(
        "/api/staff/schedule",
        params={"date": available["date"]},
        headers=employee_headers,
    )
    assert schedule.status_code == 200, schedule.text
    scheduled_group, scheduled = next(
        (group, item)
        for group in schedule.json()
        for item in group["appointments"]
        if item["appointment_id"] == appointment_id
    )
    assert scheduled["customer_name"] == "员工代约客户"
    assert scheduled_group["stylist_name"] == stylist["name"]

    customer_login = client.post(
        "/api/auth/login",
        json={"phone": customer_phone, "password": customer_password},
    )
    assert customer_login.status_code == 200, customer_login.text
    customer_headers = {"Authorization": f"Bearer {customer_login.json()['access_token']}"}
    appointments = client.get("/api/appointments", headers=customer_headers)
    assert appointments.status_code == 200, appointments.text
    assert any(item["appointment_id"] == appointment_id for item in appointments.json())

    notifications = client.get("/api/notifications", headers=customer_headers)
    assert notifications.status_code == 200, notifications.text
    assert any(
        item["kind"] == "appointment"
        and "剪发" in item["body"]
        and stylist["name"] in item["body"]
        for item in notifications.json()
    )

    conflict = client.post(
        "/api/staff/appointments",
        headers=manager_headers,
        json={
            "customer_id": customer["customer_id"],
            "stylist_id": stylist["stylist_id"],
            "slot_id": available["slot_id"],
            "service": "剪发",
        },
    )
    assert conflict.status_code == 409, conflict.text
