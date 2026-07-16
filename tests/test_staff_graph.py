import pytest
from datetime import date

from fastapi.testclient import TestClient

from backend.main import app
from backend.agents.staff_graph import build_staff_query_graph
from backend.agents.staff_graph import classify_request
from backend.database.connection import SessionLocal
from backend.database.models import (
    AgentTaskState,
    AgentTaskStatus,
    Member,
    ReminderType,
    RetentionTask,
    RetentionTaskStatus,
    User,
    UserRole,
    WalletAccount,
)


client = TestClient(app)


def _login_staff():
    # seed_sample_data 在测试夹具中创建的发型师没有密码；为测试显式设置一个员工账号。
    from backend.database.connection import SessionLocal
    from backend.database.models import User, UserRole
    from backend.auth.security import hash_password

    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.STYLIST).first()
        staff.password_hash = hash_password("StaffPass123!")
        db.commit()
        phone = staff.phone
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _login_manager():
    from backend.auth.security import hash_password

    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password("ManagerPass123!")
        db.commit()
        phone = manager.phone
    finally:
        db.close()
    response = client.post("/api/auth/login", json={"phone": phone, "password": "ManagerPass123!"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_staff_readonly_graph_queries_schedule_and_records_trace():
    assert build_staff_query_graph() is not None
    headers = _login_staff()
    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "今天有哪些预约？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert "tool:get_salon_schedule" in body["actions"]
    assert "database:staff_schedule" in body["sources"]
    assert body["task_id"]
    assert body["trace_id"] == body["trace"]["trace_id"]
    assert [step["node"] for step in body["trace"]["steps"]] == [
        "classify_request", "query_schedule", "format_response"
    ]

    task = client.get(
        f"/api/staff/agent/tasks/{body['task_id']}", headers=headers
    )
    assert task.status_code == 200, task.text
    assert task.json()["workflow_type"] == "staff_readonly_query"
    assert task.json()["result_payload"]["intent"] == "schedule"
    assert task.json()["result_payload"]["trace_id"] == body["trace_id"]


def test_customer_cannot_use_staff_readonly_graph():
    register = client.post(
        "/api/auth/register",
        json={"phone": "13970000001", "name": "普通客户", "password": "StrongPass123!"},
    )
    assert register.status_code == 201
    token = client.post(
        "/api/auth/login",
        json={"phone": "13970000001", "password": "StrongPass123!"},
    ).json()["access_token"]

    response = client.post(
        "/api/staff/agent/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "今天有哪些预约？"},
    )

    assert response.status_code == 403


def test_staff_graph_uses_rag_for_haircare_question():
    response = client.post(
        "/api/staff/agent/query",
        headers=_login_manager(),
        json={"message": "染发后怎么护理？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "tool:search_knowledge" in body["actions"]
    assert any(source.startswith("rag:") for source in body["sources"])


@pytest.mark.parametrize(
    ("question", "expected_title"),
    [
        ("7度底色想做冷棕怎么配？", "七度底色做冷棕的判断思路"),
        ("染膏和双氧怎么配比？", "染膏和氧化乳配比记录方法"),
        ("发根染和发尾染有什么区别？", "为什么发根反应通常更快"),
        ("漂到橙黄色应该怎么校色？", "橙黄色底色如何校色"),
        ("染发需要加热多久？", "加热条件与禁止加热情况"),
        ("受损发能不能染？", "受损发的染发处理"),
        ("染发前要做过敏测试吗？", "染发前过敏测试"),
    ],
)
def test_staff_graph_routes_apprentice_hair_color_questions_to_rag(
    question, expected_title
):
    state = classify_request({"message": question})

    assert state["intent"] == "knowledge"

    response = client.post(
        "/api/staff/agent/query",
        headers=_login_staff(),
        json={"message": question},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "tool:search_knowledge" in body["actions"]
    assert body["sources"][0] == f"rag:{expected_title}"
    assert expected_title in body["reply"]


def test_staff_graph_queries_customer_membership_and_wallet_from_database():
    db = SessionLocal()
    try:
        customer = User(name="会员查询客户", phone="13970000005", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        db.add(Member(user_id=customer.id, points=128))
        db.add(WalletAccount(user_id=customer.id, balance_cents=6800))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/staff/agent/query",
        headers=_login_manager(),
        json={"message": "13970000005的会员余额和积分是多少？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert "tool:query_membership" in body["actions"]
    assert "database:members" in body["sources"]
    assert "会员查询客户" in body["reply"]
    assert "68.00" in body["reply"]


def test_staff_membership_query_hides_wallet_balance():
    db = SessionLocal()
    try:
        customer = User(name="员工会员查询客户", phone="13970000015", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        db.add(Member(user_id=customer.id, points=88))
        db.add(WalletAccount(user_id=customer.id, balance_cents=9900))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/staff/agent/query",
        headers=_login_staff(),
        json={"message": "13970000015的会员余额和积分是多少？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "员工会员查询客户" in body["reply"]
    assert "积分 88" in body["reply"]
    assert "99.00" not in body["reply"]
    assert "database:wallets" not in body["sources"]


def test_staff_graph_queries_retention_reminders_from_database():
    db = SessionLocal()
    try:
        customer = User(name="留存查询客户", phone="13970000006", role=UserRole.CUSTOMER)
        db.add(customer)
        db.flush()
        db.add(RetentionTask(
            customer_id=customer.id,
            business_date=date.today(),
            primary_type=ReminderType.REPURCHASE,
            status=RetentionTaskStatus.PENDING_REVIEW,
            priority=10,
            suggestion_reason="距离上次护理已超过个人节奏",
            suggested_message="欢迎回来",
        ))
        cooling_customer = User(name="已联系留存客户", phone="13970000007", role=UserRole.CUSTOMER)
        db.add(cooling_customer)
        db.flush()
        db.add(RetentionTask(
            customer_id=cooling_customer.id,
            business_date=date.today(),
            primary_type=ReminderType.CHURN_RISK,
            status=RetentionTaskStatus.COOLING,
            priority=20,
            suggestion_reason="已经发送过",
            suggested_message="不应再次展示",
        ))
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/staff/agent/query",
        headers=_login_staff(),
        json={"message": "现在有哪些留存提醒？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "tool:get_retention_reminders" in body["actions"]
    assert "database:retention_tasks" in body["sources"]
    assert "留存查询客户" in body["reply"]
    assert "已联系留存客户" not in body["reply"]


def test_staff_graph_understands_natural_date_phrases():
    response = client.post(
        "/api/staff/agent/query",
        headers=_login_staff(),
        json={"message": "明天的预约有哪些？"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "intent:schedule" in body["actions"]
    assert "database:staff_schedule" in body["sources"]


def test_staff_endpoint_uses_model_agent(monkeypatch):
    observed = {}

    def fake_staff_agent(**kwargs):
        observed.update(kwargs)
        return {
            "reply": "已通过模型工具查询到预约。",
            "actions": ["langchain_agent:staff", "get_salon_schedule"],
            "sources": ["database:staff_schedule"],
        }

    monkeypatch.setattr("backend.api.routers.langchain_agent.handle_message", fake_staff_agent)
    response = client.post(
        "/api/staff/agent/query",
        headers=_login_staff(),
        json={"message": "帮我看看明天的预约，并告诉我最忙的发型师"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "已通过模型工具查询到预约。"
    assert observed["role"] == "staff"
    assert observed["message"] == "帮我看看明天的预约，并告诉我最忙的发型师"


def test_staff_agent_failure_is_persisted_without_breaking_normal_api(monkeypatch):
    def fail_staff_agent(**kwargs):
        raise RuntimeError("模拟查询失败")

    monkeypatch.setattr("backend.api.routers.langchain_agent.handle_message", fail_staff_agent)
    headers = _login_staff()
    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "今天有哪些预约？"},
    )

    assert response.status_code == 500

    db = SessionLocal()
    try:
        task = db.query(AgentTaskState).filter(
            AgentTaskState.workflow_type == "staff_readonly_query"
        ).order_by(AgentTaskState.created_at.desc()).first()
        assert task is not None
        assert task.status == AgentTaskStatus.FAILED
        assert "模拟查询失败" in task.result_payload
    finally:
        db.close()

    assert client.get("/api/stylists").status_code == 200
