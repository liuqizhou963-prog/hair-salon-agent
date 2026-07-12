import uuid

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.main import app


client = TestClient(app)
PASSWORD = "StrongPass123!"


def _headers(phone: str):
    login = client.post("/api/auth/login", json={"phone": phone, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _register(phone: str):
    response = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": "钱包客户", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return _headers(phone)


def _staff_headers():
    phone = "13929999999"
    db = SessionLocal()
    try:
        staff = User(
            id=uuid.uuid4(),
            name="退款员工",
            phone=phone,
            role=UserRole.STYLIST,
            password_hash=hash_password(PASSWORD),
            is_active=True,
        )
        db.add(staff)
        db.commit()
    finally:
        db.close()
    return _headers(phone)


def test_recharge_creates_wallet_transaction_and_notification():
    headers = _register("13930000001")

    recharge = client.post("/api/wallet/recharge", headers=headers, json={"amount": 200})
    wallet = client.get("/api/wallet", headers=headers)
    notifications = client.get("/api/notifications", headers=headers)

    assert recharge.status_code == 200, recharge.text
    assert recharge.json()["balance_cents"] == 20000
    assert wallet.status_code == 200
    assert wallet.json()["transactions"][0]["transaction_type"] == "recharge"
    assert notifications.status_code == 200
    assert any(item["kind"] == "wallet" for item in notifications.json())


def test_refund_requires_staff_approval_before_wallet_is_debited():
    customer_headers = _register("13930000002")
    client.post("/api/wallet/recharge", headers=customer_headers, json={"amount": 200})

    created = client.post(
        "/api/refunds",
        headers=customer_headers,
        json={"amount": 80, "reason": "不再使用"},
    )
    refund_id = created.json()["refund_id"]
    before = client.get("/api/wallet", headers=customer_headers).json()
    denied = client.post(f"/api/refunds/{refund_id}/approve", headers=customer_headers)
    staff_headers = _staff_headers()
    approved = client.post(f"/api/refunds/{refund_id}/approve", headers=staff_headers)
    after = client.get("/api/wallet", headers=customer_headers).json()
    notifications = client.get("/api/notifications", headers=customer_headers)
    audit_logs = client.get("/api/audit-logs", headers=staff_headers)

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"
    assert before["balance_cents"] == 20000
    assert denied.status_code == 403
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert after["balance_cents"] == 12000
    assert any(item["transaction_type"] == "refund" for item in after["transactions"])
    assert any(
        item["kind"] == "refund" and item["title"] == "退款已通过"
        for item in notifications.json()
    )
    assert audit_logs.status_code == 200
    assert any(item["action"] == "refund.approve" for item in audit_logs.json())


def test_refund_cannot_exceed_available_wallet_balance():
    headers = _register("13930000003")
    client.post("/api/wallet/recharge", headers=headers, json={"amount": 20})

    response = client.post("/api/refunds", headers=headers, json={"amount": 30})

    assert response.status_code == 400


def test_notification_can_be_marked_read_by_its_owner():
    headers = _register("13930000004")
    client.post("/api/wallet/recharge", headers=headers, json={"amount": 20})
    notification = client.get("/api/notifications", headers=headers).json()[0]

    response = client.post(
        f"/api/notifications/{notification['notification_id']}/read", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is True


def test_notification_cannot_be_read_by_another_customer():
    owner_headers = _register("13930000005")
    client.post("/api/wallet/recharge", headers=owner_headers, json={"amount": 20})
    notification = client.get("/api/notifications", headers=owner_headers).json()[0]
    other_headers = _register("13930000006")

    response = client.post(
        f"/api/notifications/{notification['notification_id']}/read",
        headers=other_headers,
    )

    assert response.status_code == 404
    owner_notifications = client.get("/api/notifications", headers=owner_headers)
    assert owner_notifications.json()[0]["is_read"] is False
