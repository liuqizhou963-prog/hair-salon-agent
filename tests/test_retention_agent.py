import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import (
    AgentTaskState,
    AgentTaskStatus,
    Member,
    Notification,
    ReminderLog,
    ReminderStatus,
    ReminderType,
    User,
    UserRole,
    WalletAccount,
)
from backend.auth.security import hash_password
from backend.agents.retention_graph import build_retention_graph


client = TestClient(app)


def _staff_headers():
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.ADMIN).first()
        staff.password_hash = hash_password("StaffPass123!")
        db.commit()
        phone = staff.phone
    finally:
        db.close()
    token = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_retention_graph_merges_balance_into_one_churn_task():
    assert build_retention_graph() is not None
    db = SessionLocal()
    try:
        customer = User(name="运营客户", phone="13970000003", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        customer_id = customer.id
        db.add(WalletAccount(user_id=customer.id, balance_cents=8800))
        customer.last_visit = datetime.now() - timedelta(days=170)
        db.commit()
    finally:
        db.close()

    response = client.post("/api/retention/agent/run", headers=_staff_headers())

    assert response.status_code == 200, response.text
    body = response.json()
    recommendations = [item for item in body["recommendations"] if item["phone"] == "13970000003"]
    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation["segment"] == "churn_risk"
    assert "balance_customer" in recommendation["strategy_tags"]
    assert recommendation["coupon_id"] is None
    assert recommendation["agent_mode"] == "safe_template"
    assert any("余额客户" in flag for flag in recommendation["risk_flags"])
    assert body["analysis_basis"]["scanned_customer_count"] > 0
    assert {rule["segment"] for rule in body["analysis_basis"]["rules"]} >= {"churn_risk", "birthday", "repurchase", "contact_guard"}
    assert body["task_id"]

    db = SessionLocal()
    try:
        task = db.query(AgentTaskState).filter(
            AgentTaskState.workflow_type == "retention_segmentation",
            AgentTaskState.requester_id == db.query(User).filter(User.role == UserRole.ADMIN).first().id,
        ).order_by(AgentTaskState.created_at.desc()).first()
        assert task is not None
        assert task.status == AgentTaskStatus.COMPLETED
        assert json.loads(task.result_payload)["summary"] == body["summary"]
        assert body["summary"]["balance_customer"] >= 1
        assert db.query(Notification).filter(Notification.user_id == customer_id).count() == 0
    finally:
        db.close()


def test_retention_agent_includes_birthday_and_repurchase_candidates():
    now = datetime.now()
    db = SessionLocal()
    try:
        birthday_customer = User(
            name="生日扫描客户",
            phone="13970000009",
            role=UserRole.CUSTOMER,
            birthday=(now + timedelta(days=3)).strftime("%m-%d"),
        )
        repurchase_customer = User(
            name="复购扫描客户",
            phone="13970000010",
            role=UserRole.CUSTOMER,
            last_visit=now - timedelta(days=60),
        )
        db.add_all([birthday_customer, repurchase_customer])
        db.commit()
    finally:
        db.close()

    response = client.post("/api/retention/agent/run", headers=_staff_headers())

    assert response.status_code == 200, response.text
    body = response.json()
    segments = {item["segment"] for item in body["recommendations"]}
    assert "birthday" in segments
    assert "repurchase" in segments
    assert body["summary"]["birthday"] >= 1
    assert body["summary"]["repurchase"] >= 1


def test_contacted_retention_reminder_creates_customer_notification():
    db = SessionLocal()
    try:
        customer = User(name="提醒客户", phone="13970000004", role=UserRole.CUSTOMER)
        db.add(customer)
        db.commit()
        customer_id = customer.id
    finally:
        db.close()

    # 复用现有扫描逻辑的模型底座，直接创建一条待办验证通知边界。
    from backend.database.models import ReminderLog, ReminderStatus, ReminderType
    db = SessionLocal()
    try:
        reminder = ReminderLog(customer_id=customer_id, reminder_type=ReminderType.REPURCHASE, status=ReminderStatus.PENDING, priority=10, reason="该回店了", suggested_message="欢迎回来")
        db.add(reminder)
        db.commit()
        reminder_id = reminder.id
    finally:
        db.close()

    response = client.post(f"/api/retention/reminders/{reminder_id}/contacted", headers=_staff_headers())
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        from backend.database.models import Notification
        assert db.query(Notification).filter(Notification.user_id == customer_id, Notification.title == "留存提醒").count() == 1
    finally:
        db.close()


def test_customer_cannot_run_retention_agent():
    register = client.post(
        "/api/auth/register",
        json={"phone": "13970000008", "name": "普通客户", "password": "StrongPass123!"},
    )
    assert register.status_code == 201
    token = client.post(
        "/api/auth/login",
        json={"phone": "13970000008", "password": "StrongPass123!"},
    ).json()["access_token"]

    response = client.post(
        "/api/retention/agent/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_existing_birthday_reminder_returns_explainable_evidence():
    birthday = (datetime.now() + timedelta(days=2)).strftime("%m-%d")
    db = SessionLocal()
    try:
        customer = User(name="生日证据客户", phone="13970000991", role=UserRole.CUSTOMER, birthday=birthday)
        db.add(customer)
        db.flush()
        db.add(ReminderLog(
            customer_id=customer.id,
            reminder_type=ReminderType.BIRTHDAY,
            status=ReminderStatus.PENDING,
            priority=20,
            reason="2 天后生日",
            suggested_message="提前祝您生日快乐",
            reference_date=datetime.now(),
        ))
        db.commit()
        customer_id = str(customer.id)
    finally:
        db.close()

    response = client.get("/api/retention/reminders", headers=_staff_headers())
    assert response.status_code == 200, response.text
    reminder = next(item for item in response.json() if item["customer_id"] == customer_id)
    assert reminder["evidence"] is not None
    assert birthday in reminder["evidence"]
    assert "还有 2 天" in reminder["evidence"]


def test_retention_agent_failure_is_persisted_without_breaking_normal_api(monkeypatch):
    def fail_retention_graph(requester_id):
        raise RuntimeError("模拟留存分析失败")

    monkeypatch.setattr("backend.api.routers.run_retention_graph", fail_retention_graph)
    headers = _staff_headers()
    response = client.post("/api/retention/agent/run", headers=headers)

    assert response.status_code == 500

    db = SessionLocal()
    try:
        task = db.query(AgentTaskState).filter(
            AgentTaskState.workflow_type == "retention_segmentation"
        ).order_by(AgentTaskState.created_at.desc()).first()
        assert task is not None
        assert task.status == AgentTaskStatus.FAILED
        assert "模拟留存分析失败" in task.result_payload
    finally:
        db.close()

    assert client.get("/api/stylists").status_code == 200
