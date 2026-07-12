"""预约调整 Graph：提议 -> 人工确认 -> 事务执行。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TypedDict
import uuid

from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal
from backend.database.models import Appointment, AppointmentStatus, Stylist, StylistTimeSlot
from backend.database.appointment_change import AppointmentChangeError, apply_appointment_change

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover
    END = START = StateGraph = None


class AppointmentChangeState(TypedDict, total=False):
    request: dict[str, Any]
    proposal: dict[str, Any]
    actor_id: str
    db: Session
    confirmed: bool
    awaiting_confirmation: bool
    result: dict[str, Any]
    error: str


def load_and_validate_proposal(state: AppointmentChangeState) -> AppointmentChangeState:
    if state.get("proposal"):
        return state
    request = state["request"]
    db = SessionLocal()
    try:
        appointment = db.query(Appointment).filter(Appointment.id == uuid.UUID(request["appointment_id"])).first()
        new_slot = db.query(StylistTimeSlot).filter(StylistTimeSlot.id == uuid.UUID(request["new_slot_id"])).first()
        if not appointment or not new_slot:
            raise AppointmentChangeError("预约或新的时间槽不存在")
        if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
            raise AppointmentChangeError("已取消或已完成的预约不能调整")
        stylist_id = request.get("new_stylist_id") or str(new_slot.stylist_id)
        stylist = db.query(Stylist).filter(Stylist.id == uuid.UUID(stylist_id)).first()
        if not stylist or new_slot.stylist_id != stylist.id:
            raise AppointmentChangeError("新的时间槽和发型师不匹配")
        if new_slot.is_booked and new_slot.booked_by_appointment_id != appointment.id:
            raise AppointmentChangeError("新的时间槽已经被占用")
        if appointment.time_slot_id == new_slot.id:
            raise AppointmentChangeError("新的时间槽和原预约相同")
        proposal = {
            "appointment_id": str(appointment.id),
            "customer_name": appointment.customer.name,
            "customer_phone": appointment.customer.phone,
            "old_datetime": appointment.appointment_datetime.isoformat(),
            "old_stylist_name": appointment.stylist.user.name,
            "new_slot_id": str(new_slot.id),
            "new_stylist_id": str(stylist.id),
            "new_datetime": f"{new_slot.date}T{new_slot.time}:00",
            "new_stylist_name": stylist.user.name,
            "service": request.get("service") or appointment.service,
            "notes": request.get("notes"),
        }
        return {**state, "proposal": proposal}
    except (ValueError, KeyError) as exc:
        if isinstance(exc, AppointmentChangeError):
            raise
        raise AppointmentChangeError("预约调整参数无效") from exc
    finally:
        db.close()


def human_confirmation_gate(state: AppointmentChangeState) -> AppointmentChangeState:
    if not state.get("confirmed"):
        return {**state, "awaiting_confirmation": True}
    return {**state, "awaiting_confirmation": False}


def _execute_with_actor(state: AppointmentChangeState) -> AppointmentChangeState:
    from backend.database.models import User
    actor = state["db"].query(User).filter(User.id == uuid.UUID(state["actor_id"])).first()
    if not actor:
        raise AppointmentChangeError("执行人不存在")
    return {**state, "result": apply_appointment_change(state["db"], state["proposal"], actor)}


@lru_cache(maxsize=1)
def build_appointment_change_graph():
    if StateGraph is None:
        return None
    graph = StateGraph(AppointmentChangeState)
    graph.add_node("load_and_validate_proposal", load_and_validate_proposal)
    graph.add_node("human_confirmation_gate", human_confirmation_gate)
    graph.add_node("execute_confirmed_change", _execute_with_actor)
    graph.add_edge(START, "load_and_validate_proposal")
    graph.add_edge("load_and_validate_proposal", "human_confirmation_gate")
    graph.add_conditional_edges(
        "human_confirmation_gate",
        lambda state: "execute" if state.get("confirmed") else "wait",
        {"execute": "execute_confirmed_change", "wait": END},
    )
    graph.add_edge("execute_confirmed_change", END)
    return graph.compile()


def run_appointment_change_workflow(
    request: dict[str, Any], actor_id: str, db: Session, confirmed: bool = False, proposal: dict[str, Any] | None = None
) -> dict[str, Any]:
    state: AppointmentChangeState = {
        "request": request,
        "actor_id": actor_id,
        "db": db,
        "confirmed": confirmed,
    }
    if proposal:
        state["proposal"] = proposal
    graph = build_appointment_change_graph()
    if graph is None:
        state = load_and_validate_proposal(state)
        state = human_confirmation_gate(state)
        if confirmed:
            state = _execute_with_actor(state)
    else:
        state = graph.invoke(state)
    return {"proposal": state.get("proposal"), "awaiting_confirmation": state.get("awaiting_confirmation", False), "result": state.get("result")}
