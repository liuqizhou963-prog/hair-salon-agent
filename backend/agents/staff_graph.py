"""LangGraph 员工只读查询 Graph。

Graph 只负责编排受控查询工具：
  意图识别 -> 条件路由 -> 数据库或 RAG 查询 -> 结果整理

工具本身不提供写入能力，因此员工助手即使理解错问题，也不能直接修改预约、钱包或通知。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, TypedDict

from loguru import logger

from backend.database.connection import SessionLocal
from backend.database.models import Appointment, Member, User, UserRole
from backend.database.retention import RetentionService
from backend.staff.schedule import staff_schedule_service
from backend.rag.retriever import retrieve

try:
    from langgraph.graph import END, START, StateGraph
except Exception as exc:  # pragma: no cover - only used when optional dependency is absent
    END = START = StateGraph = None
    _LANGGRAPH_IMPORT_ERROR = exc
else:
    _LANGGRAPH_IMPORT_ERROR = None


class StaffQueryState(TypedDict, total=False):
    message: str
    requester_id: str
    intent: str
    tool_result: Dict[str, Any]
    reply: str
    actions: List[str]
    sources: List[str]
    error: str


def _date_from_message(message: str) -> str | None:
    match = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", message)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            ).strftime("%Y-%m-%d")
        except ValueError:
            return None

    month_day = re.search(r"(?:今年)?(\d{1,2})月(\d{1,2})日?", message)
    if month_day:
        try:
            return datetime(
                datetime.now().year, int(month_day.group(1)), int(month_day.group(2))
            ).strftime("%Y-%m-%d")
        except ValueError:
            return None

    if "明天" in message:
        return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if "后天" in message:
        return (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    return None


def _is_schedule_request(message: str, has_customer_identifier: bool) -> bool:
    """识别员工日程问题，避免只支持固定的“今天有哪些预约”说法。"""
    if has_customer_identifier:
        return False
    if any(marker in message for marker in ("日程", "排班", "预约有哪些", "有哪些预约", "预约情况")):
        return True
    return bool(re.search(r"(?:今天|今日|明天|后天)(?:的)?(?:预约|日程|排班)", message))


def _phone_from_message(message: str) -> str | None:
    match = re.search(r"1[3-9]\d{9}", message)
    return match.group(0) if match else None


def _name_from_message(message: str) -> str | None:
    # 先处理中文姓名，避免把整句问题当成客户姓名。
    match = re.search(r"([\u4e00-\u9fa5]{2,4})(?:最近|有没有|的预约|会员|余额|积分)", message)
    if not match:
        return None
    candidate = match.group(1)
    if candidate in {"今天", "明天", "后天", "今年"}:
        return None
    return candidate


def classify_request(state: StaffQueryState) -> StaffQueryState:
    message = state["message"].strip()
    compact = message.replace(" ", "")
    phone_or_name = _phone_from_message(compact) or _name_from_message(compact)

    if phone_or_name and any(word in compact for word in ("客户", "最近", "有没有", "历史", "预约记录")):
        intent = "customer"
    elif any(word in compact for word in ("余额", "积分", "会员", "到期")):
        intent = "membership"
    elif any(word in compact for word in ("留存", "流失", "复购", "跟进", "运营提醒")):
        intent = "retention"
    elif any(word in compact for word in (
        "护理", "头发", "洗发", "护发", "头皮", "烫发后", "染发后",
        "染膏", "双氧", "氧化乳", "双氧奶", "底色", "目标色", "配比",
        "用量", "校色", "补根", "补色", "漂粉", "漂发", "加热",
        "冷棕", "灰棕", "发根", "发中", "发尾", "褪色", "色度",
        "染前", "过敏测试", "发束测试", "白发覆盖", "多孔发", "受损发",
    )):
        intent = "knowledge"
    elif _is_schedule_request(compact, bool(phone_or_name)):
        intent = "schedule"
    elif phone_or_name:
        intent = "customer"
    else:
        intent = "help"

    return {**state, "intent": intent, "actions": [f"intent:{intent}"]}


def _appointment_payload(appointment: Appointment) -> dict[str, Any]:
    return {
        "appointment_id": str(appointment.id),
        "customer_name": appointment.customer.name,
        "customer_phone": appointment.customer.phone,
        "stylist_name": appointment.stylist.user.name,
        "service": appointment.service,
        "appointment_datetime": appointment.appointment_datetime.isoformat(),
        "status": appointment.status.value,
        "notes": appointment.notes,
    }


def query_schedule(state: StaffQueryState) -> StaffQueryState:
    date = _date_from_message(state["message"])
    schedule = staff_schedule_service.get_salon_schedule(date=date)
    data = {
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "schedule": schedule,
    }
    return {**state, "tool_result": data, "actions": [*state.get("actions", []), "tool:get_salon_schedule"], "sources": ["database:staff_schedule"]}


def _find_customer(db, message: str) -> User | None:
    phone = _phone_from_message(message)
    name = _name_from_message(message)
    query = db.query(User).filter(User.role == UserRole.CUSTOMER)
    if phone:
        return query.filter(User.phone == phone).first()
    if name:
        return query.filter(User.name == name).first()
    return None


def query_customer(state: StaffQueryState) -> StaffQueryState:
    db = SessionLocal()
    try:
        customer = _find_customer(db, state["message"])
        if not customer:
            result = {"found": False, "hint": "没有根据手机号或姓名找到客户。"}
        else:
            appointments = db.query(Appointment).filter(
                Appointment.customer_id == customer.id,
            ).order_by(Appointment.appointment_datetime.desc()).limit(10).all()
            result = {
                "found": True,
                "customer": {"customer_id": str(customer.id), "name": customer.name, "phone": customer.phone, "birthday": customer.birthday},
                "appointments": [_appointment_payload(item) for item in appointments],
            }
    finally:
        db.close()
    return {**state, "tool_result": result, "actions": [*state.get("actions", []), "tool:lookup_customer"], "sources": ["database:customers", "database:appointments"]}


def query_membership(state: StaffQueryState) -> StaffQueryState:
    db = SessionLocal()
    try:
        customer = _find_customer(db, state["message"])
        if customer:
            members = db.query(Member).filter(Member.user_id == customer.id).all()
        else:
            members = db.query(Member).join(User).filter(User.role == UserRole.CUSTOMER).limit(50).all()
        result = {
            "members": [
                {
                    "customer_id": str(member.user_id),
                    "name": member.user.name,
                    "phone": member.user.phone,
                    "level": member.level.value,
                    "points": member.points,
                    "expires_at": member.expires_at.isoformat() if getattr(member, "expires_at", None) else None,
                    "balance": round((member.user.wallet_account.balance_cents if member.user.wallet_account else 0) / 100, 2),
                }
                for member in members
            ]
        }
    finally:
        db.close()
    return {**state, "tool_result": result, "actions": [*state.get("actions", []), "tool:query_membership"], "sources": ["database:members", "database:wallets"]}


def query_retention(state: StaffQueryState) -> StaffQueryState:
    db = SessionLocal()
    try:
        reminders = RetentionService.list_reminders(db, status="pending")
        result = {
            "reminders": [
                {
                    "reminder_id": str(item.id),
                    "customer_name": item.customer.name if item.customer else "未知",
                    "customer_phone": item.customer.phone if item.customer else "",
                    "reminder_type": item.reminder_type.value,
                    "priority": item.priority,
                    "reason": item.reason,
                    "suggested_message": item.suggested_message,
                }
                for item in reminders
            ]
        }
    finally:
        db.close()
    return {**state, "tool_result": result, "actions": [*state.get("actions", []), "tool:get_retention_reminders"], "sources": ["database:reminder_logs"]}


def query_knowledge(state: StaffQueryState) -> StaffQueryState:
    docs = retrieve(state["message"], k=3)
    result = {"found": bool(docs), "knowledge": docs}
    sources = [f"rag:{item.get('title', '护理知识')}" for item in docs] or ["rag:none"]
    return {**state, "tool_result": result, "actions": [*state.get("actions", []), "tool:search_knowledge"], "sources": sources}


def query_help(state: StaffQueryState) -> StaffQueryState:
    return {**state, "tool_result": {}, "actions": [*state.get("actions", []), "tool:none"], "sources": []}


def format_response(state: StaffQueryState) -> StaffQueryState:
    intent = state.get("intent")
    result = state.get("tool_result", {})
    if intent == "help":
        reply = "我可以帮你查询：今天预约、客户预约记录、会员余额和积分、留存提醒，以及护理知识。"
    elif intent == "schedule":
        lines = [f"{result.get('date', '今天')}共有 {sum(len(items) for items in result.get('schedule', {}).values())} 条预约。"]
        for stylist, items in result.get("schedule", {}).items():
            if items:
                lines.append(f"{stylist}：" + "；".join(f"{item['appointment_datetime'][11:16]} {item['customer_name']}（{item['service']}，预约ID {item['appointment_id']}）" for item in items))
        reply = "\n".join(lines)
    elif intent == "customer":
        if not result.get("found"):
            reply = result.get("hint", "没有找到客户。")
        else:
            customer = result["customer"]
            appointments = result.get("appointments", [])
            reply = f"客户：{customer['name']}（{customer['phone']}）\n预约记录 {len(appointments)} 条。"
            if appointments:
                reply += "\n" + "\n".join(f"- {item['appointment_datetime'][:16].replace('T', ' ')} {item['service']}，{item['status']}" for item in appointments[:5])
    elif intent == "membership":
        members = result.get("members", [])
        if not members:
            reply = "没有查到会员资料。"
        else:
            reply = "\n".join(f"{item['name']}：{item['level']}，积分 {item['points']}，余额 ￥{item['balance']:.2f}" for item in members[:10])
    elif intent == "retention":
        reminders = result.get("reminders", [])
        reply = "暂无待跟进提醒。" if not reminders else "\n".join(f"{item['customer_name']}：{item['reason']}" for item in reminders[:10])
    elif intent == "knowledge":
        docs = result.get("knowledge", [])
        reply = "没有检索到匹配的护理知识。" if not docs else "\n\n".join(f"【{item.get('title', '护理知识')}】\n{item.get('content', '')}" for item in docs[:2])
    else:
        reply = "暂时无法识别这个查询，请换一种说法。"
    return {**state, "reply": reply}


@lru_cache(maxsize=1)
def build_staff_query_graph():
    if StateGraph is None:
        return None
    graph = StateGraph(StaffQueryState)
    graph.add_node("classify_request", classify_request)
    graph.add_node("query_schedule", query_schedule)
    graph.add_node("query_customer", query_customer)
    graph.add_node("query_membership", query_membership)
    graph.add_node("query_retention", query_retention)
    graph.add_node("query_knowledge", query_knowledge)
    graph.add_node("query_help", query_help)
    graph.add_node("format_response", format_response)
    graph.add_edge(START, "classify_request")
    graph.add_conditional_edges(
        "classify_request",
        lambda state: state["intent"],
        {
            "schedule": "query_schedule",
            "customer": "query_customer",
            "membership": "query_membership",
            "retention": "query_retention",
            "knowledge": "query_knowledge",
            "help": "query_help",
        },
    )
    for node in ("query_schedule", "query_customer", "query_membership", "query_retention", "query_knowledge", "query_help"):
        graph.add_edge(node, "format_response")
    graph.add_edge("format_response", END)
    return graph.compile()


def run_staff_query(message: str, requester_id: str) -> dict[str, Any]:
    state: StaffQueryState = {"message": message, "requester_id": requester_id}
    graph = build_staff_query_graph()
    if graph is None:
        logger.warning("LangGraph unavailable, using the same deterministic nodes sequentially: %s", _LANGGRAPH_IMPORT_ERROR)
        state = classify_request(state)
        nodes = {
            "schedule": query_schedule,
            "customer": query_customer,
            "membership": query_membership,
            "retention": query_retention,
            "knowledge": query_knowledge,
            "help": query_help,
        }
        state = nodes[state["intent"]](state)
        state = format_response(state)
    else:
        state = graph.invoke(state)
    return {
        "reply": state.get("reply", ""),
        "actions": state.get("actions", []),
        "sources": state.get("sources", []),
        "intent": state.get("intent", "unknown"),
    }
