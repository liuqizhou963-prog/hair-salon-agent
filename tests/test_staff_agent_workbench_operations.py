import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import (
    Appointment,
    AppointmentStatus,
    Notification,
    ReminderType,
    RetentionSuppression,
    RetentionTask,
    RetentionTaskStatus,
    ServiceVerification,
    ServiceVerificationStatus,
    Stylist,
    StylistTimeSlot,
    User,
    UserRole,
)
from backend.main import app


client = TestClient(app)


def _manager_headers() -> dict[str, str]:
    password = "ManagerPass123!"
    db = SessionLocal()
    try:
        manager = db.query(User).filter(User.role == UserRole.ADMIN).first()
        manager.password_hash = hash_password(password)
        manager_phone = manager.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": manager_phone, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _employee_headers() -> dict[str, str]:
    password = "EmployeePass123!"
    db = SessionLocal()
    try:
        employee = db.query(User).filter(User.role == UserRole.STYLIST).first()
        employee.password_hash = hash_password(password)
        employee_phone = employee.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": employee_phone, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_customer(name: str, phone: str) -> uuid.UUID:
    db = SessionLocal()
    try:
        customer = User(
            id=uuid.uuid4(),
            name=name,
            phone=phone,
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
        )
        db.add(customer)
        db.commit()
        return customer.id
    finally:
        db.close()


def test_manager_agent_creates_staff_appointment_from_natural_language():
    headers = _manager_headers()
    customer_id = _create_customer("Agent代约客户", "13970000701")
    db = SessionLocal()
    try:
        stylist = db.query(Stylist).filter(Stylist.is_available.is_(True)).first()
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
        ).order_by(StylistTimeSlot.date, StylistTimeSlot.time).first()
        stylist_name, slot_time = stylist.user.name, slot.time
        slot_date = slot.date
    finally:
        db.close()


    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"帮我给Agent代约客户{slot_date}{slot_time}的护理，{stylist_name}老师"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert "创建" in body["reply"]
    assert body["actions"][-1] == "tool:create_staff_appointment"

    db = SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.customer_id == customer_id).one()
        assert appointment.status == AppointmentStatus.CONFIRMED
        assert appointment.service == "护理"
    finally:
        db.close()


def test_employee_cannot_use_agent_to_create_staff_appointment():
    headers = _employee_headers()
    customer_id = _create_customer("普通员工代约客户", "13970000704")
    db = SessionLocal()
    try:
        stylist = db.query(Stylist).filter(Stylist.is_available.is_(True)).first()
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
        ).order_by(StylistTimeSlot.date, StylistTimeSlot.time).first()
        stylist_name, slot_time = stylist.user.name, slot.time
        slot_date = slot.date
    finally:
        db.close()

    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"帮我给普通员工代约客户{slot_date}{slot_time}的护理，{stylist_name}老师"},
    )
    assert response.status_code == 200, response.text
    assert "不能创建预约" in response.json()["reply"]
    db = SessionLocal()
    try:
        assert db.query(Appointment).filter(Appointment.customer_id == customer_id).count() == 0
    finally:
        db.close()

def test_manager_agent_can_manage_a_retention_task():
    headers = _manager_headers()
    customer_id = _create_customer("Agent留存处理客户", "13970000702")
    db = SessionLocal()
    try:
        task = RetentionTask(
            id=uuid.uuid4(),
            customer_id=customer_id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.REPURCHASE,
            strategy_tags=[],
            trigger_reasons=[{"type": "repurchase", "reason": "复购提醒"}],
            evidence={},
            priority=20,
            status=RetentionTaskStatus.PENDING_REVIEW,
            suggested_message="欢迎回来。",
            suggestion_reason="复购提醒",
        )
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()


    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "把Agent留存处理客户的留存任务转人工跟进：客户暂时没时间"},
    )
    assert response.status_code == 200, response.text
    assert "manual_followup" in response.json()["reply"]

    db = SessionLocal()
    try:
        assert db.query(RetentionTask).filter(RetentionTask.id == task_id).one().status == RetentionTaskStatus.MANUAL_FOLLOWUP
        assert db.query(RetentionSuppression).filter(
            RetentionSuppression.customer_id == customer_id,
        ).count() == 1
    finally:
        db.close()


def test_manager_agent_handles_all_retention_management_actions():
    headers = _manager_headers()
    customers = {}
    db = SessionLocal()
    try:
        for label in ("忽略", "回复", "关闭"):
            customer = User(
                id=uuid.uuid4(),
                name=f"Agent{label}客户",
                phone=f"1397000080{len(customers)}",
                role=UserRole.CUSTOMER,
                password_hash=hash_password("CustomerPass123!"),
            )
            db.add(customer)
            db.flush()
            task = RetentionTask(
                id=uuid.uuid4(),
                customer_id=customer.id,
                business_date=datetime.now().date(),
                primary_type=ReminderType.REPURCHASE,
                strategy_tags=[],
                trigger_reasons=[{"type": "repurchase", "reason": "复购提醒"}],
                evidence={},
                priority=20,
                status=RetentionTaskStatus.PENDING_REVIEW,
                suggested_message="欢迎回来。",
                suggestion_reason="复购提醒",
            )
            db.add(task)
            customers[label] = (customer.name, task.id)
        db.commit()
    finally:
        db.close()

    ignored_name, ignored_id = customers["忽略"]
    ignored = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"忽略{ignored_name}的留存任务90天"},
    )
    assert ignored.status_code == 200, ignored.text
    assert "ignored" in ignored.json()["reply"]

    reply_name, reply_id = customers["回复"]
    sent = client.post(
        f"/api/retention/tasks/{reply_id}/send",
        headers=headers,
        json={"message": "先发送一条消息"},
    )
    assert sent.status_code == 200, sent.text
    recorded = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"记录{reply_name}的客户回复：下周有空"},
    )
    assert recorded.status_code == 200, recorded.text
    assert "replied" in recorded.json()["reply"]

    closed_name, closed_id = customers["关闭"]
    closed = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": f"关闭{closed_name}的留存任务"},
    )
    assert closed.status_code == 200, closed.text
    assert "closed" in closed.json()["reply"]

    db = SessionLocal()
    try:
        assert db.query(RetentionTask).filter(RetentionTask.id == ignored_id).one().status == RetentionTaskStatus.IGNORED
        assert db.query(RetentionTask).filter(RetentionTask.id == reply_id).one().status == RetentionTaskStatus.REPLIED
        assert db.query(RetentionTask).filter(RetentionTask.id == closed_id).one().status == RetentionTaskStatus.CLOSED
    finally:
        db.close()

def test_manager_agent_verifies_service_from_natural_language():
    headers = _manager_headers()
    customer_id = _create_customer("Agent核验客户", "13970000703")
    db = SessionLocal()
    try:
        stylist = db.query(Stylist).filter(Stylist.is_available.is_(True)).first()
        slot = db.query(StylistTimeSlot).filter(
            StylistTimeSlot.stylist_id == stylist.id,
            StylistTimeSlot.is_booked.is_(False),
        ).first()
        stylist_id, slot_id = str(stylist.id), str(slot.id)
    finally:
        db.close()

    created = client.post(
        "/api/staff/appointments",
        headers=headers,
        json={
            "customer_id": str(customer_id),
            "stylist_id": stylist_id,
            "slot_id": slot_id,
            "service": "护理",
        },
    )
    assert created.status_code == 201, created.text

    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "核验Agent核验客户的护理，金额88元"},
    )
    assert response.status_code == 200, response.text
    assert "已核验" in response.json()["reply"]

    db = SessionLocal()
    try:
        verification = db.query(ServiceVerification).filter(
            ServiceVerification.customer_id == customer_id,
        ).one()
        assert verification.status == ServiceVerificationStatus.VERIFIED
        assert verification.amount == 88
    finally:
        db.close()


def test_manager_agent_sends_to_customers_absent_for_at_least_200_days():
    headers = _manager_headers()
    db = SessionLocal()
    try:
        customer = User(
            id=uuid.uuid4(),
            name="两百天未到店客户",
            phone="13970000901",
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
            last_visit=datetime.now() - timedelta(days=220),
        )
        db.add(customer)
        cooling_customer = User(
            id=uuid.uuid4(),
            name="已冷却未到店客户",
            phone="13970000902",
            role=UserRole.CUSTOMER,
            password_hash=hash_password("CustomerPass123!"),
            last_visit=datetime.now() - timedelta(days=210),
        )
        db.add(cooling_customer)
        db.flush()
        db.add(RetentionTask(
            id=uuid.uuid4(),
            customer_id=cooling_customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.CHURN_RISK,
            strategy_tags=[],
            trigger_reasons=[{"type": "churn_risk", "reason": "超过200天未到店"}],
            evidence={"days_since_last_visit": 210},
            priority=30,
            status=RetentionTaskStatus.COOLING,
            suggested_message="已冷却客户不应重复发送。",
            suggestion_reason="流失风险提醒",
        ))
        db.commit()
        customer_id, cooling_customer_id = customer.id, cooling_customer.id
    finally:
        db.close()

    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "给超过200天没来的客户发一次消息：您好，最近有空欢迎回来。"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert "200 天以上" in body["reply"]
    assert "命中 2 人" in body["reply"]
    assert "可发送任务 1 条" in body["reply"]
    assert "跳过 1 人" in body["reply"]
    assert body["actions"][-1] == "tool:batch_send_retention_by_visit_age"

    db = SessionLocal()
    try:
        task = db.query(RetentionTask).filter(
            RetentionTask.customer_id == customer_id,
            RetentionTask.primary_type == ReminderType.CHURN_RISK,
        ).one()
        assert task.status == RetentionTaskStatus.COOLING
        assert task.suggested_message == "您好，最近有空欢迎回来。"
        cooling_task = db.query(RetentionTask).filter(
            RetentionTask.customer_id == cooling_customer_id,
        ).one()
        assert cooling_task.status == RetentionTaskStatus.COOLING
        assert db.query(Notification).filter(
            Notification.user_id == customer_id,
            Notification.title == "留存提醒",
        ).count() == 1
        assert db.query(Notification).filter(
            Notification.user_id == cooling_customer_id,
            Notification.title == "留存提醒",
        ).count() == 0
    finally:
        db.close()


def test_manager_agent_rewrites_ambiguous_workbench_request_without_mutating_business_data():
    headers = _manager_headers()
    response = client.post(
        "/api/staff/agent/query",
        headers=headers,
        json={"message": "帮我处理一下这笔退款"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert "我理解你的意思是" in body["reply"]
    assert "确认" in body["reply"]
    assert body["actions"] == ["planner:clarification"]
