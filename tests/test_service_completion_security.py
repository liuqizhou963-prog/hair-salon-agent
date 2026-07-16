import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import Appointment, AppointmentStatus, ServiceVerification, ServiceVerificationStatus, Stylist, StylistTimeSlot, User, UserRole, WalletAccount
from backend.main import app


client = TestClient(app)


def test_service_completion_uses_logged_in_admin_permission_without_extra_password():
    manager_password = "ManagerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(manager_password)
        customer = User(id=uuid.uuid4(), name="核销安全客户", phone="13970000401", role=UserRole.CUSTOMER, password_hash=hash_password("CustomerPass123!"))
        db.add(customer)
        db.flush()
        db.add(WalletAccount(id=uuid.uuid4(), user_id=customer.id, balance_cents=10000))
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.stylist_id == stylist.id, StylistTimeSlot.is_booked.is_(False)).first()
        appointment = Appointment(id=uuid.uuid4(), customer_id=customer.id, stylist_id=stylist.id, time_slot_id=slot.id, service="护理", appointment_datetime=datetime.now(), status=AppointmentStatus.CONFIRMED)
        verification = ServiceVerification(id=uuid.uuid4(), appointment=appointment, customer_id=customer.id, stylist_id=stylist.id, service="护理", amount=88, status=ServiceVerificationStatus.VERIFIED, verified_by=manager.id, verified_at=datetime.now())
        db.add_all([appointment, verification])
        db.commit()
        manager_phone, verification_id = manager.phone, str(verification.id)
    finally:
        db.close()

    login = client.post("/api/auth/login", json={"phone": manager_phone, "password": manager_password})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    completed = client.post(f"/api/staff/service-verifications/{verification_id}/complete", headers=headers, json={})
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"


def test_manager_agent_completes_verified_service_after_task_confirmation_without_password():
    manager_password = "ManagerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(manager_password)
        customer = User(id=uuid.uuid4(), name="Agent核销客户", phone="13970000402", role=UserRole.CUSTOMER, password_hash=hash_password("CustomerPass123!"))
        db.add(customer)
        db.flush()
        db.add(WalletAccount(id=uuid.uuid4(), user_id=customer.id, balance_cents=10000))
        stylist = db.query(Stylist).first()
        slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.stylist_id == stylist.id, StylistTimeSlot.is_booked.is_(False)).first()
        appointment = Appointment(id=uuid.uuid4(), customer_id=customer.id, stylist_id=stylist.id, time_slot_id=slot.id, service="护理", appointment_datetime=datetime.now(), status=AppointmentStatus.CONFIRMED)
        verification = ServiceVerification(id=uuid.uuid4(), appointment=appointment, customer_id=customer.id, stylist_id=stylist.id, service="护理", amount=88, status=ServiceVerificationStatus.VERIFIED, verified_by=manager.id, verified_at=datetime.now())
        db.add_all([appointment, verification])
        db.commit()
        manager_phone, verification_id = manager.phone, str(verification.id)
    finally:
        db.close()

    login = client.post("/api/auth/login", json={"phone": manager_phone, "password": manager_password})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    proposed = client.post("/api/staff/agent/query", headers=headers, json={"message": "完成Agent核销客户的护理服务"})
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["agent_task"]["workflow_type"] == "service_completion"
    assert body["agent_task"]["result_payload"]["verification_id"] == verification_id

    completed = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm",
        headers=headers,
        json={"confirmed": True},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["result_payload"]["status"] == "completed"
    audits = client.get("/api/audit-logs", headers=headers).json()
    assert any(item["action"] == "agent.service_completion_confirmed" for item in audits)
