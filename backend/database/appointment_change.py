"""预约调整的事务执行器。

Agent 只能生成 proposal；只有员工确认后才会进入这里。所有关键写操作在同一个
SQLAlchemy Session 中完成，失败时由调用方回滚。
"""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from backend.database.finance import FinanceService
from backend.database.models import Appointment, AppointmentStatus, NotificationKind, Stylist, StylistTimeSlot, User


class AppointmentChangeError(ValueError):
    pass


def apply_appointment_change(db: Session, proposal: dict, actor: User) -> dict:
    try:
        appointment_id = uuid.UUID(proposal["appointment_id"])
        new_slot_id = uuid.UUID(proposal["new_slot_id"])
        stylist_id = uuid.UUID(proposal["new_stylist_id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AppointmentChangeError("预约调整方案编号无效") from exc

    # 确认阶段锁住预约和目标时间槽，避免两个员工同时确认同一个空档。
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )
    new_slot = (
        db.query(StylistTimeSlot)
        .filter(StylistTimeSlot.id == new_slot_id)
        .with_for_update()
        .first()
    )
    stylist = db.query(Stylist).filter(Stylist.id == stylist_id).first()
    if not appointment or not new_slot or not stylist:
        raise AppointmentChangeError("预约、时间槽或发型师不存在")
    if appointment.status in {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED}:
        raise AppointmentChangeError("已取消或已完成的预约不能调整")
    if new_slot.stylist_id != stylist.id:
        raise AppointmentChangeError("新的时间槽不属于指定发型师")
    if new_slot.is_booked and new_slot.booked_by_appointment_id != appointment.id:
        raise AppointmentChangeError("新的时间槽刚刚被其他预约占用，请重新查询")

    old_slot = appointment.time_slot
    old_value = {
        "appointment_datetime": appointment.appointment_datetime.isoformat(),
        "stylist_name": appointment.stylist.user.name,
        "service": appointment.service,
    }
    if old_slot and old_slot.id != new_slot.id:
        old_slot.is_booked = False
        old_slot.booked_by_appointment_id = None

    new_slot.is_booked = True
    new_slot.booked_by_appointment_id = appointment.id
    appointment.time_slot_id = new_slot.id
    appointment.stylist_id = stylist.id
    appointment.appointment_datetime = datetime.strptime(
        f"{new_slot.date} {new_slot.time}", "%Y-%m-%d %H:%M"
    )
    if proposal.get("service"):
        appointment.service = proposal["service"]
    if proposal.get("notes"):
        appointment.notes = proposal["notes"]

    new_value = {
        "appointment_datetime": appointment.appointment_datetime.isoformat(),
        "stylist_name": stylist.user.name,
        "service": appointment.service,
    }
    FinanceService.create_audit(
        db,
        actor.id,
        "appointment.agent_change_confirmed",
        "appointment",
        str(appointment.id),
        {"before": old_value, "after": new_value},
    )
    FinanceService.create_notification(
        db,
        appointment.customer_id,
        NotificationKind.APPOINTMENT,
        "预约已调整",
        f"您的预约已调整为 {new_value['appointment_datetime'][:16].replace('T', ' ')}，发型师：{new_value['stylist_name']}，项目：{new_value['service']}。",
    )
    db.commit()
    db.refresh(appointment)
    return {"success": True, "appointment_id": str(appointment.id), "before": old_value, "after": new_value}
