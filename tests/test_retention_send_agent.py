import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import (
    Notification,
    ReminderType,
    RetentionTask,
    RetentionTaskStatus,
    User,
    UserRole,
)
from backend.main import app


client = TestClient(app)


def test_manager_agent_previews_then_sends_retention_message():
    manager_password = "ManagerPass123!"
    customer_password = "CustomerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(manager_password)
        customer = User(id=uuid.uuid4(), name="Agent留存客户", phone="13970000403", role=UserRole.CUSTOMER, password_hash=hash_password(customer_password))
        db.add(customer)
        db.flush()
        retention_task = RetentionTask(
            id=uuid.uuid4(), customer_id=customer.id, business_date=datetime.now().date(),
            primary_type=ReminderType.REPURCHASE, strategy_tags=[], trigger_reasons=[], evidence={}, priority=20,
            status=RetentionTaskStatus.PENDING_REVIEW,
            suggested_message="您好，近期需要安排护理吗？", suggestion_reason="复购提醒",
        )
        db.add(retention_task)
        db.commit()
        manager_phone, customer_phone, task_id = manager.phone, customer.phone, str(retention_task.id)
    finally:
        db.close()

    manager_login = client.post("/api/auth/login", json={"phone": manager_phone, "password": manager_password})
    manager_headers = {"Authorization": f"Bearer {manager_login.json()['access_token']}"}
    proposed = client.post(
        "/api/staff/agent/query", headers=manager_headers,
        json={"message": "给Agent留存客户发送回访消息"},
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["agent_task"]["workflow_type"] == "retention_send"
    assert body["agent_task"]["result_payload"]["message"] == "您好，近期需要安排护理吗？"

    db = SessionLocal()
    try:
        assert db.query(RetentionTask).filter(RetentionTask.id == uuid.UUID(task_id)).one().status == RetentionTaskStatus.PENDING_REVIEW
    finally:
        db.close()

    confirmed = client.post(
        f"/api/staff/agent/tasks/{body['task_id']}/confirm",
        headers=manager_headers, json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result_payload"]["status"] == "cooling"

    customer_login = client.post("/api/auth/login", json={"phone": customer_phone, "password": customer_password})
    customer_headers = {"Authorization": f"Bearer {customer_login.json()['access_token']}"}
    assert any(item["title"] == "留存提醒" for item in client.get("/api/notifications", headers=customer_headers).json())
    audits = client.get("/api/audit-logs", headers=manager_headers).json()
    assert any(item["action"] == "agent.retention_send_confirmed" for item in audits)


def test_manager_agent_sends_all_birthday_retention_messages():
    manager_password = "ManagerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(manager_password)
        birthday_customers = []
        birthday_customer_ids = []
        for index in range(2):
            customer = User(
                id=uuid.uuid4(),
                name=f"批量生日客户{index}",
                phone=f"1397000050{index}",
                role=UserRole.CUSTOMER,
                password_hash=hash_password("CustomerPass123!"),
            )
            db.add(customer)
            db.flush()
            birthday_customers.append(customer)
            birthday_customer_ids.append(customer.id)
            db.add(RetentionTask(
                id=uuid.uuid4(),
                customer_id=customer.id,
                business_date=datetime.now().date(),
                primary_type=ReminderType.BIRTHDAY,
                strategy_tags=["birthday"],
                trigger_reasons=[{"type": "birthday", "reason": "生日提醒"}],
                evidence={},
                priority=30,
                status=RetentionTaskStatus.PENDING_REVIEW,
                suggested_message=f"生日快乐，客户{index}！",
                suggestion_reason="生日提醒",
            ))
        other_customer = User(
            id=uuid.uuid4(),
            name="批量复购客户",
            phone="13970000599",
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
        )
        db.add(other_customer)
        db.flush()
        other_task = RetentionTask(
            id=uuid.uuid4(),
            customer_id=other_customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.REPURCHASE,
            strategy_tags=["repurchase"],
            trigger_reasons=[{"type": "repurchase", "reason": "复购提醒"}],
            evidence={},
            priority=10,
            status=RetentionTaskStatus.PENDING_REVIEW,
            suggested_message="复购提醒，不应被生日批量发送带上。",
            suggestion_reason="复购提醒",
        )
        db.add(other_task)
        db.commit()
        manager_phone = manager.phone
        other_task_id = other_task.id
    finally:
        db.close()

    manager_login = client.post(
        "/api/auth/login",
        json={"phone": manager_phone, "password": manager_password},
    )
    manager_headers = {"Authorization": f"Bearer {manager_login.json()['access_token']}"}
    response = client.post(
        "/api/staff/agent/query",
        headers=manager_headers,
        json={"message": "帮我把留存提醒里的生日提醒一起发送一下"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["agent_task"] is None
    assert body["actions"][-1] == "tool:batch_send_birthday_retention"
    assert body["reply"] == "生日提醒批量发送完成：共 2 条，成功 2 条，失败 0 条。"

    db = SessionLocal()
    try:
        birthday_statuses = db.query(RetentionTask.status).filter(
            RetentionTask.primary_type == ReminderType.BIRTHDAY,
        ).all()
        assert [item[0] for item in birthday_statuses] == [RetentionTaskStatus.COOLING] * 2
        assert db.query(RetentionTask).filter(RetentionTask.id == other_task_id).one().status == RetentionTaskStatus.PENDING_REVIEW
        assert db.query(Notification).filter(
            Notification.user_id.in_(birthday_customer_ids),
            Notification.title == "留存提醒",
        ).count() == 2
    finally:
        db.close()

    audits = client.get("/api/audit-logs", headers=manager_headers).json()
    assert any(item["action"] == "agent.retention_birthday_batch_send_completed" for item in audits)


def test_employee_cannot_send_all_birthday_retention_messages():
    employee_password = "EmployeePass123!"
    db = SessionLocal()
    try:
        employee = db.query(User).filter(User.role == UserRole.STYLIST).first()
        employee.password_hash = hash_password(employee_password)
        customer = User(
            id=uuid.uuid4(),
            name="员工权限生日客户",
            phone="13970000601",
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
        )
        db.add(customer)
        db.flush()
        task = RetentionTask(
            id=uuid.uuid4(),
            customer_id=customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.BIRTHDAY,
            strategy_tags=[],
            trigger_reasons=[{"type": "birthday", "reason": "生日提醒"}],
            evidence={},
            priority=30,
            status=RetentionTaskStatus.PENDING_REVIEW,
            suggested_message="员工不应发送这条生日提醒。",
            suggestion_reason="生日提醒",
        )
        db.add(task)
        db.commit()
        employee_phone = employee.phone
        task_id = task.id
    finally:
        db.close()


    employee_login = client.post(
        "/api/auth/login",
        json={"phone": employee_phone, "password": employee_password},
    )
    employee_headers = {"Authorization": f"Bearer {employee_login.json()['access_token']}"}
    response = client.post(
        "/api/staff/agent/query",
        headers=employee_headers,
        json={"message": "帮我把留存提醒里的生日提醒全部发送"},
    )
    assert response.status_code == 200, response.text
    assert "不能发送留存提醒" in response.json()["reply"]

    db = SessionLocal()
    try:
        assert db.query(RetentionTask).filter(RetentionTask.id == task_id).one().status == RetentionTaskStatus.PENDING_REVIEW
        assert db.query(Notification).filter(Notification.title == "留存提醒").count() == 0
    finally:
        db.close()


def test_named_birthday_customer_keeps_single_send_confirmation_flow():
    manager_password = "ManagerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(manager_password)
        customer = User(
            id=uuid.uuid4(),
            name="指定生日客户",
            phone="13970000602",
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
        )
        db.add(customer)
        db.flush()
        db.add(RetentionTask(
            id=uuid.uuid4(),
            customer_id=customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.BIRTHDAY,
            strategy_tags=[],
            trigger_reasons=[{"type": "birthday", "reason": "生日提醒"}],
            evidence={},
            priority=20,
            status=RetentionTaskStatus.PENDING_REVIEW,
            suggested_message="指定客户生日快乐。",
            suggestion_reason="生日提醒",
        ))
        db.commit()
        manager_phone, customer_name = manager.phone, customer.name
    finally:
        db.close()

    login = client.post(
        "/api/auth/login",
        json={"phone": manager_phone, "password": manager_password},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"给{customer_name}发送生日提醒"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["agent_task"]["workflow_type"] == "retention_send"
