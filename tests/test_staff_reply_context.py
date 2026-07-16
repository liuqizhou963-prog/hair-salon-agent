from fastapi.testclient import TestClient

from backend.api.routers import _staff_agent_message
from backend.agents.langchain_agent import langchain_agent
from backend.agents.staff_operation_planner import StaffOperationPlan
from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole
from backend.main import app


client = TestClient(app)


def _login_manager():
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password("ManagerPass123!")
        db.commit()
        phone = manager.phone
    finally:
        db.close()
    response = client.post(
        "/api/auth/login",
        json={"phone": phone, "password": "ManagerPass123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_staff_reply_context_is_delimited_and_current_instruction_is_last():
    from backend.api.schemas import StaffAgentQueryRequest

    message = _staff_agent_message(StaffAgentQueryRequest(
        message="请根据上面继续回答",
        reply_to={
            "message_id": "message-1",
            "role": "assistant",
            "content": "这是上一条智能助手回复，今天预约有 0 条。",
        },
    ))

    assert "[引用消息开始]" in message
    assert "这是上一条智能助手回复，今天预约有 0 条。" in message
    assert message.endswith("当前用户的新指令：请根据上面继续回答")


def test_staff_reply_context_reaches_planner_agent_and_task(monkeypatch):
    observed = {}

    def fake_plan(message):
        observed["plan"] = message
        return StaffOperationPlan(action="read.schedule")

    def fake_handle_message(**kwargs):
        observed["handle"] = kwargs["message"]
        return {"reply": "已根据引用消息继续回答。", "actions": ["fake_agent"]}

    def fake_staff_query(message, requester_id, allow_financial=False):
        observed["query"] = message
        return {
            "reply": "今天没有预约。",
            "actions": ["intent:schedule"],
            "sources": ["database:staff_schedule"],
            "intent": "schedule",
            "trace_id": "trace-reply-context",
            "trace": {"trace_id": "trace-reply-context", "steps": []},
        }

    monkeypatch.setattr(langchain_agent, "plan_staff_operation", fake_plan)
    monkeypatch.setattr(langchain_agent, "handle_message", fake_handle_message)
    monkeypatch.setattr("backend.api.routers.run_staff_query", fake_staff_query)

    response = client.post(
        "/api/staff/agent/query",
        headers=_login_manager(),
        json={
            "message": "请根据上面继续回答",
            "reply_to": {
                "message_id": "message-1",
                "role": "assistant",
            "content": "这是上一条智能助手回复，今天预约有 0 条。",
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == "已根据引用消息继续回答。"
    for key in ("plan", "handle", "query"):
        assert "这是上一条智能助手回复，今天预约有 0 条。" in observed[key]
        assert observed[key].endswith("当前用户的新指令：请根据上面继续回答")

    task = client.get(
        f"/api/staff/agent/tasks/{body['task_id']}",
        headers=_login_manager(),
    )
    assert task.status_code == 200, task.text
    assert task.json()["input_payload"]["reply_to"]["message_id"] == "message-1"
