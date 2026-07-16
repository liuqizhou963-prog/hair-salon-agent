"""LangChain 工具集 — 把现有业务函数包装成 LLM 可调用的 tools。

设计原则（护栏而非大脑）：
1. 顾客身份（phone/name）通过闭包绑定，LLM 永远无法伪造，只能提供语义参数。
2. 下单/取消前在工具内做真实校验（时间槽是否存在、预约是否属于本人），
   LLM 编造的 slot_id / appointment_id 会被工具拒绝。
3. 工具只返回真实数据库结果，价格、发型师、空档都来自 DB，杜绝 LLM 幻觉。

对外分两套皮肤：
- build_customer_tools(phone, name) — C 端顾客顾问
- build_staff_tools()               — B 端店员助手
"""

import json
from typing import List, Optional

from langchain_core.tools import tool
from loguru import logger

from backend.client.appointment import client_appointment_service
from backend.client.knowledge_query import rag_retriever
from backend.database.connection import SessionLocal
from backend.database.models import Member, User, UserRole
from backend.database.retention import RetentionService
from backend.database.membership import member_display_level
from backend.database.service import AppointmentService, MemberService
from backend.staff.schedule import staff_schedule_service


def _dump(data) -> str:
    """统一把工具结果序列化为中文可读 JSON 字符串给 LLM。"""
    return json.dumps(data, ensure_ascii=False, default=str)


# ==================== C 端顾客工具 ====================

def build_customer_tools(phone: str, name: Optional[str] = None) -> List:
    """构建顾客侧工具集。phone/name 通过闭包绑定，LLM 不可见、不可改。"""

    @tool
    def search_knowledge(query: str) -> str:
        """检索美发护理专业知识。用于回答烫发、染发、护理、头皮、毛躁、
        产品、日常养护等问题。query 传用户的护理疑问，如"染后掉色怎么办"。"""
        docs = rag_retriever.search(query, k=3)
        if not docs:
            return _dump({"found": False, "hint": "没有检索到匹配的护理知识，请让用户把问题描述得更具体。"})
        return _dump({"found": True, "knowledge": docs})

    @tool
    def recommend_stylists(service_type: str) -> str:
        """推荐擅长某类项目的发型师，并附带每位发型师近 7 天的真实可用时间槽。
        service_type 只能是单个中文关键词：烫、染、护理、造型、头皮。
        下单需要的 stylist_id 和 slot_id 都来自这里，不要自己编造。"""
        result = rag_retriever.search_stylists_and_availability(service_type)
        stylists = result.get("stylists", [])
        if not stylists:
            return _dump({"found": False, "service_type": service_type,
                          "hint": "没有擅长该项目的可用发型师，建议换个项目关键词。"})
        # 精简每位发型师的空档，避免上下文过长
        for s in stylists:
            s["available_slots"] = s.get("available_slots", [])[:4]
        return _dump({"found": True, "service_type": service_type,
                      "stylists": stylists[:3], "knowledge": result.get("knowledge", [])[:1]})

    @tool
    def book_appointment(stylist_id: str, slot_id: str, service: str) -> str:
        """为当前顾客下单预约。stylist_id 和 slot_id 必须来自 recommend_stylists
        的真实返回值。service 是项目名（烫/染/护理/造型/头皮）。
        若顾客是新客且没有姓名，工具会返回需要姓名的提示。"""
        if not name:
            return _dump({"success": False, "need_name": True,
                          "hint": "这是新顾客，缺少姓名，无法建档。请先询问顾客姓名。"})
        result = client_appointment_service.book_appointment(
            customer_phone=phone,
            customer_name=name,
            stylist_id=stylist_id,
            slot_id=slot_id,
            service=service,
            notes="来自 AI 助手预约",
        )
        return _dump(result)

    @tool
    def lookup_my_appointments() -> str:
        """查询当前顾客本人的所有预约记录（含状态）。取消或改约前先用它拿到
        真实的 appointment_id。"""
        appts = client_appointment_service.get_customer_appointments(phone)
        if not appts:
            return _dump({"found": False, "hint": "该顾客暂无预约记录。"})
        return _dump({"found": True, "appointments": appts})

    @tool
    def cancel_appointment(appointment_id: str) -> str:
        """取消当前顾客的某条预约。appointment_id 必须来自 lookup_my_appointments，
        且工具会校验该预约确实属于本顾客，防止误取消他人预约。"""
        owned = {a["appointment_id"] for a in
                 client_appointment_service.get_customer_appointments(phone)}
        if appointment_id not in owned:
            return _dump({"success": False,
                          "hint": "该预约编号不属于当前顾客，拒绝取消。请先用 lookup_my_appointments 核对。"})
        db = SessionLocal()
        try:
            ok = AppointmentService.cancel_appointment(db, appointment_id)
        finally:
            db.close()
        return _dump({"success": ok, "appointment_id": appointment_id})

    return [search_knowledge, recommend_stylists, book_appointment,
            lookup_my_appointments, cancel_appointment]


# ==================== B 端店员工具 ====================

def build_staff_tools() -> List:
    """构建店员侧只读工具集，供模型自主选择查询路径。"""

    @tool
    def search_knowledge(query: str) -> str:
        """检索美发护理专业知识，供店员话术支持时快速查证。"""
        docs = rag_retriever.search(query, k=3)
        return _dump({"found": bool(docs), "knowledge": docs})

    @tool
    def get_salon_schedule(date: Optional[str] = None) -> str:
        """查询全店当天（或指定 YYYY-MM-DD 日期）的所有发型师预约日程。"""
        schedule = staff_schedule_service.get_salon_schedule(date=date)
        return _dump({"date": date or "今天", "schedule": schedule})

    @tool
    def get_birthday_members() -> str:
        """查询今天过生日的会员，用于生日营销触达。"""
        db = SessionLocal()
        try:
            members = MemberService.get_birthday_members_today(db)
            data = [{"name": m.user.name, "phone": m.user.phone,
                     "level": member_display_level(m.level.value, m.user.wallet_account.balance_cents if m.user.wallet_account else 0), "points": m.points} for m in members]
        finally:
            db.close()
        return _dump({"count": len(data), "members": data})

    @tool
    def lookup_customer(identifier: str) -> str:
        """按顾客姓名或手机号查询预约历史；姓名重复时不要猜，先向店员确认。"""
        db = SessionLocal()
        try:
            query = db.query(User).filter(User.role == UserRole.CUSTOMER)
            customer = query.filter(User.phone == identifier).first()
            if not customer:
                customer = query.filter(User.name == identifier).first()
            if not customer:
                return _dump({"found": False, "hint": "没有找到该顾客，请提供准确姓名或手机号。"})
            appointments = client_appointment_service.get_customer_appointments(customer.phone)
            return _dump({
                "found": True,
                "customer": {"name": customer.name, "phone": customer.phone, "birthday": customer.birthday},
                "appointments": appointments,
            })
        finally:
            db.close()

    @tool
    def query_membership(identifier: Optional[str] = None) -> str:
        """查询会员等级和积分；identifier 可填姓名或手机号，不填则返回会员概览。"""
        db = SessionLocal()
        try:
            query = db.query(Member).join(User).filter(User.role == UserRole.CUSTOMER)
            if identifier:
                query = query.filter((User.phone == identifier) | (User.name == identifier))
            members = query.limit(50).all()
            data = [{
                "name": member.user.name,
                "phone": member.user.phone,
                "level": member_display_level(member.level.value, member.user.wallet_account.balance_cents if member.user.wallet_account else 0),
                "points": member.points,
                "expires_at": member.expires_at,
            } for member in members]
            return _dump({"found": bool(data), "members": data})
        finally:
            db.close()

    @tool
    def get_retention_reminders() -> str:
        """查询当前仍可处理的留存任务，已发送并进入冷却期的任务不会返回。"""
        db = SessionLocal()
        try:
            tasks = RetentionService.list_tasks(db, today_only=True)
            data = [{
                "customer_name": task.customer.name if task.customer else "未知",
                "customer_phone": task.customer.phone if task.customer else "",
                "priority": task.priority,
                "reason": task.suggestion_reason or "留存任务待处理",
                "suggested_message": task.suggested_message,
            } for task in tasks]
            return _dump({"count": len(data), "reminders": data})
        finally:
            db.close()

    return [
        search_knowledge,
        get_salon_schedule,
        get_birthday_members,
        lookup_customer,
        query_membership,
        get_retention_reminders,
    ]
