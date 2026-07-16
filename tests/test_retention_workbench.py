from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from backend.auth.security import hash_password
from backend.database.connection import SessionLocal
from backend.database.models import (
    RetentionContact,
    RetentionContactStatus,
    RetentionSuppression,
    RetentionSuppressionType,
    RetentionTask,
    RetentionTaskStatus,
    ReminderType,
    User,
    UserRole,
)
from backend.database.retention import RetentionService
from backend.main import app


client = TestClient(app)


def _customer(db, phone: str, **kwargs) -> User:
    customer = User(name="留存测试客户", phone=phone, role=UserRole.CUSTOMER, **kwargs)
    db.add(customer)
    db.flush()
    return customer


def _staff_headers() -> dict[str, str]:
    db = SessionLocal()
    try:
        staff = db.query(User).filter(User.role == UserRole.ADMIN).first()
        staff.password_hash = hash_password("StaffPass123!")
        phone = staff.phone
        db.commit()
    finally:
        db.close()
    login = client.post("/api/auth/login", json={"phone": phone, "password": "StaffPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _pending_task(db, customer: User, task_type: ReminderType = ReminderType.CHURN_RISK) -> RetentionTask:
    task = RetentionTask(
        customer_id=customer.id,
        business_date=datetime.now().date(),
        primary_type=task_type,
        strategy_tags=[],
        trigger_reasons=[{"type": task_type.value, "reason": "测试触发"}],
        evidence={},
        priority=30,
        status=RetentionTaskStatus.PENDING_REVIEW,
        suggested_message="安全测试话术",
    )
    db.add(task)
    db.commit()
    return task


def test_churn_boundary_is_fixed_at_150_days():
    now = datetime.now()
    db = SessionLocal()
    try:
        day_149 = _customer(db, "13770000149", last_visit=now - timedelta(days=149))
        day_150 = _customer(db, "13770000150", last_visit=now - timedelta(days=150))
        db.commit()

        before_boundary = RetentionService.evaluate_customer(db, day_149, now=now)
        assert before_boundary is not None
        assert before_boundary["type"] == ReminderType.REPURCHASE
        hit = RetentionService.evaluate_customer(db, day_150, now=now)
        assert hit is not None
        assert hit["type"] == ReminderType.CHURN_RISK
        assert hit["evidence"]["primary"]["churn_threshold_days"] == 150
    finally:
        db.close()


def test_birthday_and_balance_churn_merge_into_one_birthday_task():
    now = datetime.now()
    db = SessionLocal()
    try:
        customer = _customer(
            db,
            "13770000151",
            birthday=(now + timedelta(days=2)).strftime("%m-%d"),
            last_visit=now - timedelta(days=170),
        )
        from backend.database.models import WalletAccount
        db.add(WalletAccount(user_id=customer.id, balance_cents=8800))
        db.commit()

        hit = RetentionService.evaluate_customer(db, customer, now=now)
        assert hit is not None
        assert hit["type"] == ReminderType.BIRTHDAY
        assert "balance_customer" in hit["tags"]
        assert {item["type"] for item in hit["trigger_reasons"]} == {"birthday", "churn_risk"}
        assert "生日护理" not in hit["message"]
    finally:
        db.close()


def test_active_suppression_blocks_all_retention_candidates():
    now = datetime.now()
    db = SessionLocal()
    try:
        customer = _customer(db, "13770000152", last_visit=now - timedelta(days=170))
        staff = db.query(User).filter(User.role == UserRole.STYLIST).first()
        db.add(RetentionSuppression(
            customer_id=customer.id,
            suppression_type=RetentionSuppressionType.TEMPORARY_IGNORE,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=30),
            reason="客户暂不需要",
            created_by=staff.id,
        ))
        db.commit()

        assert RetentionService.evaluate_customer(db, customer, now=now) is None
    finally:
        db.close()


def test_successful_contact_enters_cross_type_cooldown():
    now = datetime.now()
    db = SessionLocal()
    try:
        customer = _customer(db, "13770000153", last_visit=now - timedelta(days=170))
        staff = db.query(User).filter(User.role == UserRole.STYLIST).first()
        task = RetentionTask(
            customer_id=customer.id,
            business_date=(now - timedelta(days=10)).date(),
            primary_type=ReminderType.CHURN_RISK,
            strategy_tags=[],
            trigger_reasons=[],
            evidence={},
            priority=30,
            status=RetentionTaskStatus.COOLING,
        )
        db.add(task)
        db.flush()
        db.add(RetentionContact(
            task_id=task.id,
            customer_id=customer.id,
            reviewer_id=staff.id,
            sender_id=staff.id,
            status=RetentionContactStatus.SENT,
            actual_message="安全测试话术",
            sent_at=now - timedelta(days=10),
        ))
        db.commit()

        assert RetentionService.evaluate_customer(db, customer, now=now) is None
    finally:
        db.close()


def test_scan_is_idempotent_and_creates_one_daily_task():
    now = datetime.now()
    db = SessionLocal()
    try:
        customer = _customer(db, "13770000154", last_visit=now - timedelta(days=160))
        db.commit()

        first = RetentionService.scan_and_generate(db, now=now)
        second = RetentionService.scan_and_generate(db, now=now)

        tasks = db.query(RetentionTask).filter(RetentionTask.customer_id == customer.id).all()
        assert first["churn_risk"] == 1
        assert second["total"] == 0
        assert len(tasks) == 1
        assert tasks[0].status == RetentionTaskStatus.PENDING_REVIEW
    finally:
        db.close()


def test_send_creates_full_contact_record_and_blocks_repeat_send():
    db = SessionLocal()
    try:
        customer = _customer(db, "13770000155", last_visit=datetime.now() - timedelta(days=170))
        task = _pending_task(db, customer)
        task_id = str(task.id)
        customer_id = customer.id
    finally:
        db.close()

    headers = _staff_headers()
    response = client.post(
        f"/api/retention/tasks/{task_id}/send",
        json={"message": "您好，近期需要安排护理吗？"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cooling"
    assert response.json()["next_contact_at"] is not None

    duplicate = client.post(
        f"/api/retention/tasks/{task_id}/send",
        json={"message": "重复发送"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    db = SessionLocal()
    try:
        contact = db.query(RetentionContact).filter(RetentionContact.task_id == task.id).one()
        assert contact.status == RetentionContactStatus.SENT
        assert contact.actual_message == "您好，近期需要安排护理吗？"
        assert contact.provider_message_id.startswith("mock-")
        from backend.database.models import Notification
        assert db.query(Notification).filter(Notification.user_id == customer_id, Notification.title == "留存提醒").count() == 1
    finally:
        db.close()


def test_failed_send_can_retry_without_entering_cooldown():
    db = SessionLocal()
    try:
        customer = _customer(db, "13770000156", last_visit=datetime.now() - timedelta(days=170))
        task = _pending_task(db, customer)
        task_id = str(task.id)
    finally:
        db.close()

    headers = _staff_headers()
    failed = client.post(
        f"/api/retention/tasks/{task_id}/send",
        json={"message": "第一次发送", "simulate_failure": True},
        headers=headers,
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "send_failed"
    assert failed.json()["next_contact_at"] is None

    retried = client.post(
        f"/api/retention/tasks/{task_id}/retry",
        json={"message": "第二次发送"},
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "cooling"

    db = SessionLocal()
    try:
        statuses = [item.status for item in db.query(RetentionContact).filter(RetentionContact.task_id == task.id).all()]
        assert statuses == [RetentionContactStatus.FAILED, RetentionContactStatus.SENT]
    finally:
        db.close()


def test_ignore_reply_and_close_manage_suppressions():
    db = SessionLocal()
    try:
        ignored_customer = _customer(db, "13770000157", last_visit=datetime.now() - timedelta(days=170))
        ignored_task = _pending_task(db, ignored_customer)
        replied_customer = _customer(db, "13770000158", last_visit=datetime.now() - timedelta(days=170))
        replied_task = _pending_task(db, replied_customer)
        ignored_task_id = str(ignored_task.id)
        replied_task_id = str(replied_task.id)
        ignored_customer_id = ignored_customer.id
        replied_customer_id = replied_customer.id
    finally:
        db.close()

    headers = _staff_headers()
    ignored = client.post(
        f"/api/retention/tasks/{ignored_task_id}/ignore",
        json={"mode": "30_days", "reason": "客户暂不需要"},
        headers=headers,
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["status"] == "ignored"

    sent = client.post(
        f"/api/retention/tasks/{replied_task_id}/send",
        json={"message": "您好，想确认近期是否需要预约。"},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    reply = client.post(
        f"/api/retention/tasks/{replied_task_id}/reply",
        json={"reply_content": "下周再联系我"},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "replied"
    closed = client.post(
        f"/api/retention/tasks/{replied_task_id}/close",
        json={"reason": "已完成电话沟通"},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    db = SessionLocal()
    try:
        ignore = db.query(RetentionSuppression).filter(
            RetentionSuppression.customer_id == ignored_customer_id,
        ).one()
        assert ignore.suppression_type == RetentionSuppressionType.TEMPORARY_IGNORE
        manual = db.query(RetentionSuppression).filter(
            RetentionSuppression.customer_id == replied_customer_id,
            RetentionSuppression.suppression_type == RetentionSuppressionType.MANUAL_FOLLOWUP,
        ).one()
        assert manual.released_at is not None
    finally:
        db.close()
def test_records_view_excludes_uncontacted_tasks():
    db = SessionLocal()
    try:
        pending_customer = _customer(db, "13770000159", last_visit=datetime.now() - timedelta(days=170))
        manual_customer = _customer(db, "13770000160", last_visit=datetime.now() - timedelta(days=170))
        failed_customer = _customer(db, "13770000161", last_visit=datetime.now() - timedelta(days=170))
        pending_task = _pending_task(db, pending_customer)

        manual_task = RetentionTask(
            customer_id=manual_customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.CHURN_RISK,
            strategy_tags=[],
            trigger_reasons=[],
            evidence={},
            priority=30,
            status=RetentionTaskStatus.MANUAL_FOLLOWUP,
            suggested_message="人工跟进话术",
        )
        failed_task = RetentionTask(
            customer_id=failed_customer.id,
            business_date=datetime.now().date(),
            primary_type=ReminderType.CHURN_RISK,
            strategy_tags=[],
            trigger_reasons=[],
            evidence={},
            priority=30,
            status=RetentionTaskStatus.SEND_FAILED,
            suggested_message="发送失败话术",
        )
        db.add_all([manual_task, failed_task])
        db.flush()
        staff = db.query(User).filter(User.role == UserRole.STYLIST).first()
        db.add(RetentionContact(
            task_id=failed_task.id,
            customer_id=failed_customer.id,
            reviewer_id=staff.id,
            sender_id=staff.id,
            status=RetentionContactStatus.FAILED,
            actual_message="发送失败话术",
            attempted_at=datetime.now(),
            failed_at=datetime.now(),
            failure_reason="模拟渠道失败",
        ))
        db.commit()

        records = RetentionService.list_tasks(db, records_only=True)
        record_ids = {task.id for task in records}
        assert pending_task.id not in record_ids
        assert manual_task.id in record_ids
        assert failed_task.id in record_ids
    finally:
        db.close()
