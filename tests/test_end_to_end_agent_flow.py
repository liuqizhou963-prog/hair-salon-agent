from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.auth.security import hash_password


client = TestClient(app)


def test_customer_booking_to_staff_confirmation_to_notification():
    staff_db = SessionLocal()
    try:
        staff = staff_db.query(User).filter(User.role == UserRole.STYLIST).first()
        staff.password_hash = hash_password("StaffPass123!")
        manager = staff_db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password("ManagerPass123!")
        staff_db.commit()
        staff_phone = staff.phone
        manager_phone = manager.phone
    finally:
        staff_db.close()
    staff_token = client.post("/api/auth/login", json={"phone": staff_phone, "password": "StaffPass123!"}).json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}
    manager_token = client.post("/api/auth/login", json={"phone": manager_phone, "password": "ManagerPass123!"}).json()["access_token"]
    manager_headers = {"Authorization": f"Bearer {manager_token}"}

    customer_phone = "13970000005"
    assert client.post(
        "/api/auth/register",
        json={"phone": customer_phone, "name": "全链路客户", "password": "StrongPass123!"},
    ).status_code == 201
    customer_token = client.post(
        "/api/auth/login",
        json={"phone": customer_phone, "password": "StrongPass123!"},
    ).json()["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    stylist = client.get("/api/stylists", params={"specialty": "护理"}).json()[0]
    slots = client.get(f"/api/stylists/{stylist['stylist_id']}/slots").json()
    available = [item for item in slots if not item["is_booked"]]
    assert len(available) >= 2
    booking = client.post(
        "/api/appointments",
        headers=customer_headers,
        json={"stylist_id": stylist["stylist_id"], "slot_id": available[0]["slot_id"], "service": "护理"},
    )
    assert booking.status_code == 200, booking.text
    appointment_id = booking.json()["appointment_id"]
    booking_date = available[0]["date"]

    direct_schedule = client.get("/api/staff/schedule", params={"date": booking_date}, headers=staff_headers)
    assert direct_schedule.status_code == 200, direct_schedule.text
    assert any(
        item["appointment_id"] == appointment_id
        for group in direct_schedule.json()
        for item in group["appointments"]
    ), direct_schedule.text

    query = client.post(
        "/api/staff/agent/query",
        headers=manager_headers,
        json={"message": f"{booking_date}有哪些预约？"},
    )
    assert query.status_code == 200
    assert appointment_id in query.json()["reply"]

    proposal = client.post(
        "/api/staff/agent/appointment-change/propose",
        headers=manager_headers,
        json={"appointment_id": appointment_id, "new_slot_id": available[1]["slot_id"]},
    )
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["awaiting_confirmation"] is True

    confirmed = client.post(
        f"/api/staff/agent/tasks/{proposal.json()['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed"

    notifications = client.get("/api/notifications", headers=customer_headers)
    assert notifications.status_code == 200
    assert any(item["kind"] == "appointment" for item in notifications.json())
