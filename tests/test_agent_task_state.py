from backend.database.connection import SessionLocal
from backend.database.models import AgentTaskState, AgentTaskStatus, User


def test_agent_task_state_persists_requester_and_confirmation_status():
    """Agent workflow state must keep its requester and human-review flag."""
    db = SessionLocal()
    try:
        requester = db.query(User).first()
        assert requester is not None

        task = AgentTaskState(
            requester_id=requester.id,
            workflow_type="appointment_adjustment",
            input_payload='{"appointment_id": "demo-id"}',
            awaiting_confirmation=True,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        stored = db.query(AgentTaskState).filter(AgentTaskState.id == task.id).one()
        assert stored.requester_id == requester.id
        assert stored.workflow_type == "appointment_adjustment"
        assert stored.status == AgentTaskStatus.PENDING
        assert stored.awaiting_confirmation is True
        assert stored.requester.id == requester.id
    finally:
        db.close()
