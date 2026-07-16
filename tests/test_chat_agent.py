from fastapi.testclient import TestClient
from datetime import datetime
import uuid

from backend.main import app
from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole


client = TestClient(app)


def _auth_headers(phone: str, name: str):
    registered = client.post(
        "/api/auth/register",
        json={"phone": phone, "name": name, "password": "StrongPass123!"},
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "StrongPass123!"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _staff_headers():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.role == UserRole.STYLIST).first()
        user.password_hash = hash_password("StrongPass123!")
        db.commit()
        phone = user.phone
    finally:
        db.close()
    return _login_headers(phone)


def _admin_headers():
    phone = "13919999999"
    db = SessionLocal()
    try:
        user = User(
            id=uuid.uuid4(),
            name="测试管理员",
            phone=phone,
            role=UserRole.ADMIN,
            password_hash=hash_password("StrongPass123!"),
            is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()
    return _login_headers(phone)


def _login_headers(phone: str):
    login = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "StrongPass123!"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _first_available_slot(service: str = "护理"):
    stylists = client.get("/api/stylists", params={"specialty": service}).json()
    assert stylists, f"expected at least one stylist for {service}"

    for stylist in stylists:
        slots = client.get(f"/api/stylists/{stylist['stylist_id']}/slots").json()
        if slots:
            return stylist, slots[0]

    raise AssertionError(f"expected at least one available slot for {service}")


def test_chat_recommends_stylist_with_slot_id():
    headers = _auth_headers("13910000001", "测试客户")
    response = client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": "推荐一个擅长护理的发型师",
            "phone": "13910000001",
            "name": "测试客户",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["actions"] == ["search_stylists", "check_availability"]
    assert "slot_id" in payload["reply"]


def test_langchain_agent_falls_back_without_key():
    headers = _auth_headers("13910000006", "适配测试")
    response = client.post(
        "/api/chat/langchain",
        headers=headers,
        json={
            "message": "烫后怎么护理比较好？",
            "phone": "13910000006",
            "name": "适配测试",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # 无 LLM key 环境应降级到规则 Agent；有 key 时首个 action 为 langchain_agent:<role>
    assert payload["actions"][0] in {"rule_agent_fallback", "langchain_agent:customer"}
    assert "护理" in payload["reply"]


def test_langchain_staff_role_falls_back_without_key():
    headers = _staff_headers()
    denied = client.post(
        "/api/chat/langchain",
        headers=headers,
        json={
            "message": "今天有哪些预约？",
            "phone": "13910000099",
            "role": "staff",
        },
    )
    assert denied.status_code == 403

    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "今天有哪些预约？"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["actions"]


def test_customer_tool_rejects_foreign_appointment_cancel():
    """护栏单测：编造/他人的 appointment_id 必须被工具拒绝，不落库。"""
    import json

    from backend.agents.tools import build_customer_tools

    tools = {t.name: t for t in build_customer_tools(phone="13910000200", name="护栏测试")}
    result = json.loads(
        tools["cancel_appointment"].invoke(
            {"appointment_id": "00000000-0000-0000-0000-000000000000"}
        )
    )
    assert result["success"] is False


def test_chat_books_and_cancels_own_appointment():
    _, slot = _first_available_slot("护理")
    phone = "13910000002"
    headers = _auth_headers(phone, "李雷")

    booking = client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": f"我叫李雷，预约护理，slot_id: {slot['slot_id']}",
            "phone": phone,
        },
    )

    assert booking.status_code == 200
    booking_payload = booking.json()
    assert booking_payload["actions"] == ["book_appointment"]
    assert "等待店长确认" in booking_payload["reply"]

    appointments = client.get(
        "/api/appointments", params={"phone": phone}, headers=headers
    ).json()
    active = [item for item in appointments if item["status"] != "cancelled"]
    assert active
    appointment_id = active[-1]["appointment_id"]

    cancel = client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": f"取消预约 {appointment_id}",
            "phone": phone,
        },
    )

    assert cancel.status_code == 200
    cancel_payload = cancel.json()
    assert cancel_payload["actions"] == ["cancel_appointment"]
    assert appointment_id in cancel_payload["reply"]

    updated = client.get(
        "/api/appointments", params={"phone": phone}, headers=headers
    ).json()
    cancelled = [item for item in updated if item["appointment_id"] == appointment_id]
    assert cancelled[0]["status"] == "cancelled"


def test_chat_does_not_cancel_other_customers_appointment():
    _, slot = _first_available_slot("护理")
    owner_phone = "13910000003"
    other_phone = "13910000004"
    owner_headers = _auth_headers(owner_phone, "韩梅梅")
    other_headers = _auth_headers(other_phone, "其他客户")

    booking = client.post(
        "/api/chat",
        headers=owner_headers,
        json={
            "message": f"我叫韩梅梅，预约护理，slot_id: {slot['slot_id']}",
            "phone": owner_phone,
        },
    )
    assert booking.status_code == 200

    appointments = client.get(
        "/api/appointments", params={"phone": owner_phone}, headers=owner_headers
    ).json()
    active = [item for item in appointments if item["status"] != "cancelled"]
    appointment_id = active[-1]["appointment_id"]

    denied = client.post(
        "/api/chat",
        headers=other_headers,
        json={
            "message": f"取消预约 {appointment_id}",
            "phone": other_phone,
        },
    )

    assert denied.status_code == 200
    denied_payload = denied.json()
    assert denied_payload["actions"] == ["lookup_appointments"]

    cleanup = client.delete(
        f"/api/appointments/{appointment_id}", headers=owner_headers
    )
    assert cleanup.status_code == 200


def test_member_transaction_and_birthday_campaign_flow():
    phone = "13910000005"
    birthday = datetime.now().strftime("%m-%d")
    headers = _auth_headers(phone, "生日会员")

    member = client.post(
        "/api/members",
        headers=headers,
        json={
            "phone": phone,
            "name": "生日会员",
            "birthday": birthday,
            "level": "gold",
        },
    )
    assert member.status_code == 200
    member_payload = member.json()
    assert member_payload["phone"] == phone
    assert member_payload["level"] == "silver"

    transaction = client.post(
        "/api/transactions",
        headers=headers,
        json={
            "phone": phone,
            "amount": 268,
            "service": "护理",
        },
    )
    assert transaction.status_code == 410

    point_records = client.get("/api/points/transactions", headers=headers)
    assert point_records.status_code == 200
    assert point_records.json() == []

    members = client.get("/api/members", headers=headers)
    assert members.status_code == 200
    updated_member = next(
        item for item in members.json() if item["phone"] == phone
    )
    assert updated_member["points"] == 0

    birthdays = client.get("/api/marketing/birthdays", headers=_admin_headers())
    assert birthdays.status_code == 200
    campaign = next(
        item for item in birthdays.json() if item["phone"] == phone
    )
    assert "生日" in campaign["message"]


def test_init_db_requires_admin_token_when_configured(monkeypatch):
    from backend.api import routers

    monkeypatch.setattr(routers.settings, "ADMIN_TOKEN", "test-admin-token")
    admin_headers = _admin_headers()

    denied = client.post("/api/init-db")
    assert denied.status_code == 403

    allowed = client.post(
        "/api/init-db",
        headers={**admin_headers, "X-Admin-Token": "test-admin-token"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["success"] is True
