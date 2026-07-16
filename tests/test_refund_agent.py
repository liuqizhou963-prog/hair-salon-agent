from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.main import app


client = TestClient(app)


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


def _customer_with_refund(phone: str, name: str) -> tuple[dict[str, str], str]:
    password = "CustomerPass123!"
    created = client.post("/api/auth/register", json={"phone": phone, "name": name, "password": password})
    assert created.status_code == 201, created.text
    headers = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'phone': phone, 'password': password}).json()['access_token']}"}
    assert client.post("/api/wallet/recharge", headers=headers, json={"amount": 200}).status_code == 200
    refund = client.post("/api/refunds", headers=headers, json={"amount": 50, "reason": "不再使用"})
    assert refund.status_code == 201, refund.text
    return headers, refund.json()["refund_id"]


def test_refund_requires_manager_password_and_agent_confirmation_is_atomic():
    customer_headers, refund_id = _customer_with_refund("13970000201", "退款语义客户")
    manager_headers = _headers(UserRole.ADMIN, "ManagerPass123!")

    wrong_password = client.post(
        f"/api/refunds/{refund_id}/approve",
        headers=manager_headers,
        json={"manager_password": "wrong-password"},
    )
    assert wrong_password.status_code == 403
    assert client.get("/api/wallet", headers=customer_headers).json()["balance_cents"] == 20000

    proposal = client.post(
        "/api/staff/agent/query",
        headers=manager_headers,
        json={"message": "通过退款语义客户的退款申请"},
    )
    assert proposal.status_code == 200, proposal.text
    body = proposal.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["agent_task"]["workflow_type"] == "refund_approve"
    assert body["agent_task"]["result_payload"]["refund_id"] == refund_id

    denied_confirmation = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True, "manager_password": "wrong-password"},
    )
    assert denied_confirmation.status_code == 403
    assert client.get("/api/wallet", headers=customer_headers).json()["balance_cents"] == 20000

    confirmed = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm",
        headers=manager_headers,
        json={"confirmed": True, "manager_password": "ManagerPass123!"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result_payload"]["status"] == "approved"
    assert client.get("/api/wallet", headers=customer_headers).json()["balance_cents"] == 15000

    notifications = client.get("/api/notifications", headers=customer_headers).json()
    assert any(item["title"] == "退款已通过" for item in notifications)
    audits = client.get("/api/audit-logs", headers=manager_headers).json()
    assert any(item["action"] == "agent.refund_decision_confirmed" for item in audits)
    assert any(item["action"] == "security.step_up_denied" for item in audits)
