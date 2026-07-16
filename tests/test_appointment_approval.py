from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.agents.staff_intent import classify_staff_intent
from backend.database.connection import SessionLocal
from backend.database.models import Appointment, AppointmentStatus, StylistTimeSlot, User, UserRole
from backend.main import app


client = TestClient(app)


def test_intent_retrieval_groups_different_phrasings_by_business_meaning():
    assert classify_staff_intent("帮我批复龙百川的预约")["intent"] == "appointment_approval"
    assert classify_staff_intent("把客户的预约审核通过")["intent"] == "appointment_approval"
    assert classify_staff_intent("今天店里忙不忙")["intent"] == "schedule"
    assert classify_staff_intent("卡里还有多少钱")["intent"] == "membership"


def _headers(role: UserRole, password: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == role).first()
        user.password_hash = hash_password(password)
        phone = user.phone
        db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_customer_appointment_is_pending_until_manager_approves_and_syncs_everywhere():
    customer_phone = "13970000191"
    customer_password = "CustomerPass123!"
    registered = client.post(
        "/api/auth/register",
        json={"phone": customer_phone, "name": "龙百川", "password": customer_password},
    )
    assert registered.status_code == 201, registered.text
    customer_headers = {
        "Authorization": f"Bearer {client.post('/api/auth/login', json={'phone': customer_phone, 'password': customer_password}).json()['access_token']}"
    }

    stylist = client.get("/api/stylists").json()[0]
    slot = next(item for item in client.get(
        f"/api/stylists/{stylist['stylist_id']}/slots"
    ).json() if not item["is_booked"])
    created = client.post(
        "/api/appointments",
        headers=customer_headers,
        json={"stylist_id": stylist["stylist_id"], "slot_id": slot["slot_id"], "service": "护理"},
    )
    assert created.status_code == 200, created.text
    appointment_id = created.json()["appointment_id"]
    assert created.json()["status"] == "pending"

    employee_headers = _headers(UserRole.STYLIST, "EmployeePass123!")
    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")
    schedule = client.get("/api/staff/schedule", params={"date": slot["date"]}, headers=employee_headers)
    assert schedule.status_code == 200, schedule.text
    assert any(
        item["appointment_id"] == appointment_id and item["status"] == "pending"
        for group in schedule.json() for item in group["appointments"]
    )

    denied = client.post(
        "/api/staff/agent/appointment-approval/propose",
        headers=employee_headers,
        json={"appointment_id": appointment_id},
    )
    assert denied.status_code == 403

    proposal = client.post(
        "/api/staff/agent/appointment-approval/propose",
        headers=manager_headers,
        json={"appointment_id": appointment_id},
    )
    assert proposal.status_code == 200, proposal.text
    task = proposal.json()
    assert task["awaiting_confirmation"] is True
    assert task["result_payload"]["customer_name"] == "龙百川"

    before_confirmation = client.get("/api/appointments", headers=customer_headers).json()
    assert next(item for item in before_confirmation if item["appointment_id"] == appointment_id)["status"] == "pending"

    confirmed = client.post(
        f"/api/staff/agent/tasks/{task['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result_payload"]["status"] == "confirmed"

    customer_appointments = client.get("/api/appointments", headers=customer_headers).json()
    assert next(item for item in customer_appointments if item["appointment_id"] == appointment_id)["status"] == "confirmed"
    notifications = client.get("/api/notifications", headers=customer_headers).json()
    assert any(item["title"] == "预约已确认" for item in notifications)

    audits = client.get("/api/audit-logs", headers=manager_headers).json()
    assert any(item["action"] == "agent.appointment_approved" and item["entity_id"] == appointment_id for item in audits)

    repeated = client.post(
        f"/api/staff/agent/tasks/{task['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    )
    assert repeated.status_code == 409


def test_direct_approval_endpoint_is_retired_and_manager_uses_confirmation_task():
    customer_phone = "13970000193"
    customer_password = "CustomerPass123!"
    registered = client.post(
        "/api/auth/register",
        json={"phone": customer_phone, "name": "员工直批客户", "password": customer_password},
    )
    assert registered.status_code == 201, registered.text
    customer_headers = {
        "Authorization": f"Bearer {client.post('/api/auth/login', json={'phone': customer_phone, 'password': customer_password}).json()['access_token']}"
    }
    stylist = client.get("/api/stylists").json()[0]
    slot = next(item for item in client.get(
        f"/api/stylists/{stylist['stylist_id']}/slots"
    ).json() if not item["is_booked"])
    created = client.post(
        "/api/appointments",
        headers=customer_headers,
        json={"stylist_id": stylist["stylist_id"], "slot_id": slot["slot_id"], "service": "剪发"},
    )
    assert created.status_code == 200, created.text
    appointment_id = created.json()["appointment_id"]

    employee_headers = _headers(UserRole.STYLIST, "EmployeePass123!")
    approved = client.post(
        f"/api/staff/appointments/{appointment_id}/approve",
        headers=employee_headers,
    )
    assert approved.status_code == 403, approved.text

    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")
    approved = client.post(
        f"/api/staff/appointments/{appointment_id}/approve",
        headers=manager_headers,
    )
    assert approved.status_code == 410, approved.text

    proposed = client.post(
        "/api/staff/agent/appointment-approval/propose",
        headers=manager_headers,
        json={"appointment_id": appointment_id},
    )
    assert proposed.status_code == 200, proposed.text
    confirmed = client.post(
        f"/api/staff/agent/tasks/{proposed.json()['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    customer_appointment = next(
        item for item in client.get("/api/appointments", headers=customer_headers).json()
        if item["appointment_id"] == appointment_id
    )
    assert customer_appointment["status"] == "confirmed"
    assert any(
        item["title"] == "预约已确认"
        for item in client.get("/api/notifications", headers=customer_headers).json()
    )

    repeated = client.post(
        f"/api/staff/appointments/{appointment_id}/approve",
        headers=manager_headers,
    )
    assert repeated.status_code == 410


def test_manager_agent_creates_a_confirmation_task_from_natural_language():
    customer_phone = "13970000192"
    customer_password = "CustomerPass123!"
    client.post(
        "/api/auth/register",
        json={"phone": customer_phone, "name": "语义客户", "password": customer_password},
    )
    customer_headers = {
        "Authorization": f"Bearer {client.post('/api/auth/login', json={'phone': customer_phone, 'password': customer_password}).json()['access_token']}"
    }
    stylist = client.get("/api/stylists").json()[0]
    slot = next(item for item in client.get(
        f"/api/stylists/{stylist['stylist_id']}/slots"
    ).json() if not item["is_booked"])
    created = client.post(
        "/api/appointments",
        headers=customer_headers,
        json={"stylist_id": stylist["stylist_id"], "slot_id": slot["slot_id"], "service": "染发"},
    )
    appointment_id = created.json()["appointment_id"]

    employee_headers = _headers(UserRole.STYLIST, "EmployeePass123!")
    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")
    employee_result = client.post(
        "/api/staff/agent/query",
        headers=employee_headers,
        json={"message": "把语义客户的预约审核通过"},
    )
    assert employee_result.status_code == 200, employee_result.text
    assert "不能批复" in employee_result.json()["reply"]

    manager_result = client.post(
        "/api/staff/agent/query",
        headers=manager_headers,
        json={"message": "把语义客户的预约审核通过"},
    )
    assert manager_result.status_code == 200, manager_result.text
    body = manager_result.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["agent_task"]["result_payload"]["appointment_id"] == appointment_id

    confirmed = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    appointments = client.get("/api/appointments", headers=customer_headers).json()
    assert next(item for item in appointments if item["appointment_id"] == appointment_id)["status"] == "confirmed"


def test_manager_agent_proposes_natural_language_change_after_manager_approval():
    customer_phone = "13970000193"
    customer_password = "CustomerPass123!"
    client.post("/api/auth/register", json={"phone": customer_phone, "name": "自然改约客户", "password": customer_password})
    customer_headers = {
        "Authorization": f"Bearer {client.post('/api/auth/login', json={'phone': customer_phone, 'password': customer_password}).json()['access_token']}"
    }
    stylist = client.get("/api/stylists").json()[0]
    slots = client.get(f"/api/stylists/{stylist['stylist_id']}/slots").json()
    first_slot, target_slot = slots[0], slots[1]
    created = client.post(
        "/api/appointments", headers=customer_headers,
        json={"stylist_id": stylist["stylist_id"], "slot_id": first_slot["slot_id"], "service": "护理"},
    )
    appointment_id = created.json()["appointment_id"]
    employee_headers = _headers(UserRole.STYLIST, "EmployeePass123!")
    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")

    approved = client.post(
        f"/api/staff/appointments/{appointment_id}/approve", headers=employee_headers,
    )
    assert approved.status_code == 403, approved.text
    approved = client.post(
        f"/api/staff/appointments/{appointment_id}/approve", headers=manager_headers,
    )
    assert approved.status_code == 410, approved.text
    approval = client.post(
        "/api/staff/agent/appointment-approval/propose",
        headers=manager_headers,
        json={"appointment_id": appointment_id},
    )
    assert approval.status_code == 200, approval.text
    assert client.post(
        f"/api/staff/agent/tasks/{approval.json()['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True},
    ).status_code == 200

    proposal = client.post(
        "/api/staff/agent/query", headers=manager_headers,
        json={"message": f"把自然改约客户的预约改到{target_slot['date']} {target_slot['time']}"},
    )
    assert proposal.status_code == 200, proposal.text
    body = proposal.json()
    assert body["agent_task"]["workflow_type"] == "appointment_change"
    assert body["agent_task"]["result_payload"]["new_slot_id"] == target_slot["slot_id"]

    confirmed = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm", headers=manager_headers, json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    db = SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).one()
        assert str(appointment.time_slot_id) == target_slot["slot_id"]
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert db.query(StylistTimeSlot).filter(StylistTimeSlot.id == first_slot["slot_id"]).one().is_booked is False
    finally:
        db.close()
