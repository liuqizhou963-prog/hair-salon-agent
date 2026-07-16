import uuid

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import ReminderLog, ReminderStatus, ReminderType, User, UserRole
from backend.main import app


client = TestClient(app)


def _staff_headers():
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.ADMIN).first()
        staff.password_hash = hash_password("StaffPass123!")
        staff_id = str(staff.id)
        phone = staff.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, staff_id


def test_staff_agent_query_is_audited_with_actor_and_trace():
    headers, staff_id = _staff_headers()
    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "你好"},
    )
    assert response.status_code == 200, response.text

    logs = client.get("/api/audit-logs", headers=headers)
    assert logs.status_code == 200
    record = next(item for item in logs.json() if item["action"] == "agent.staff_query_completed")
    assert record["actor_user_id"] == staff_id
    assert record["entity_id"] == response.json()["task_id"]
    assert response.json()["trace_id"] in record["details"]


def test_dismissing_a_reminder_is_audited():
    headers, staff_id = _staff_headers()
    db = SessionLocal()
    try:
        customer = User(
            id=uuid.uuid4(), name="审计测试客户", phone="13990000001", role=UserRole.CUSTOMER
        )
        db.add(customer)
        db.flush()
        reminder = ReminderLog(
            id=uuid.uuid4(),
            customer_id=customer.id,
            reminder_type=ReminderType.REPURCHASE,
            status=ReminderStatus.PENDING,
            priority=10,
            reason="测试提醒",
            suggested_message="欢迎回来",
        )
        db.add(reminder)
        db.commit()
        reminder_id = str(reminder.id)
    finally:
        db.close()

    response = client.post(f"/api/retention/reminders/{reminder_id}/dismiss", headers=headers)
    assert response.status_code == 200, response.text

    logs = client.get("/api/audit-logs", headers=headers)
    record = next(item for item in logs.json() if item["action"] == "retention.reminder_dismissed")
    assert record["actor_user_id"] == staff_id
    assert record["entity_id"] == reminder_id
