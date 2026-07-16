"""轻量聊天编排层：用规则意图识别串联现有业务服务。"""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger

from backend.client.appointment import client_appointment_service
from backend.client.knowledge_query import rag_retriever
from backend.database.connection import SessionLocal
from backend.database.models import StylistTimeSlot
from backend.database.service import AppointmentService, StylistService


SERVICE_KEYWORDS = ("烫", "染", "护理", "造型", "头皮")
KNOWLEDGE_KEYWORDS = (
    "烫发",
    "烫后",
    "染发",
    "染后",
    "锁色",
    "褪色",
    "护理",
    "产品",
    "洗头",
    "毛躁",
    "干枯",
    "发膜",
    "精油",
    "头皮",
    "掉色",
    "防晒",
)
STYLIST_KEYWORDS = ("发型师", "老师", "推荐", "擅长", "安排")
AVAILABILITY_KEYWORDS = ("时间", "空档", "有空", "档期", "什么时候", "哪天", "周末")
APPOINTMENT_LOOKUP_KEYWORDS = ("我的预约", "查预约", "预约记录", "已预约", "预约情况")
APPOINTMENT_CANCEL_KEYWORDS = ("取消预约", "改约", "改时间")
APPOINTMENT_BOOKING_KEYWORDS = ("预约", "帮我约", "我要约", "定一下", "订一下")

STATUS_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "completed": "已完成",
    "cancelled": "已取消",
}


class ChatAgent:
    """Day 3 MVP：轻量 Agent，负责把聊天请求路由到现有业务服务。"""

    def handle_message(
        self,
        message: str,
        phone: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_message = message.strip()
        logger.info(f"ChatAgent handling message for {phone}: {clean_message[:80]}")

        if self._is_cancel_request(clean_message):
            return self._build_cancel_result(clean_message, phone)

        if self._is_booking_request(clean_message):
            return self._build_booking_result(clean_message, phone, name)

        if self._is_appointment_lookup(clean_message):
            return self._build_appointment_summary(phone)

        if self._is_stylist_request(clean_message):
            service_type = self._extract_service_type(clean_message)
            if not service_type:
                return {
                    "reply": "可以的。你先告诉我想做哪类项目，比如烫、染、护理、造型或头皮护理，我就能继续推荐发型师和空档。",
                    "actions": ["clarify_service_type"],
                }
            return self._build_stylist_recommendation(service_type)

        if self._is_knowledge_request(clean_message):
            return self._build_knowledge_answer(clean_message)

        return self._build_fallback_reply(name=name)

    def _build_knowledge_answer(self, message: str) -> Dict[str, Any]:
        query = message
        service_type = self._extract_service_type(message)
        if service_type and "护理" not in query:
            query = f"{service_type}护理"

        docs = rag_retriever.search(query, k=3)
        if not docs:
            return {
                "reply": "我暂时没有检索到特别匹配的护理知识。你可以告诉我更具体一点的问题，比如烫后护理、染后掉色、头皮敏感或毛躁修复。",
                "actions": ["retrieve_knowledge"],
            }

        lines = ["结合店内知识库，我先给你几个直接可用的建议："]
        for index, doc in enumerate(docs, start=1):
            lines.append(f"{index}. {doc['title']}：{doc['content']}")
        lines.append("如果你想顺便看适合这类项目的发型师和近期空档，也可以直接告诉我。")

        return {
            "reply": "\n".join(lines),
            "actions": ["retrieve_knowledge"],
        }

    def _build_stylist_recommendation(self, service_type: str) -> Dict[str, Any]:
        result = rag_retriever.search_stylists_and_availability(service_type)
        stylists = result["stylists"][:3]
        if not stylists:
            return {
                "reply": f"我这边暂时没找到擅长“{service_type}”的可用发型师。你可以换个项目关键词，或者先看全部发型师列表 `/api/stylists`。",
                "actions": ["search_stylists"],
            }

        lines = [f"我先帮你筛了擅长“{service_type}”的发型师，优先推荐这几位："]
        for stylist in stylists:
            slots = stylist["available_slots"][:2]
            if slots:
                slot_text = "；".join(
                    f"{slot['datetime_str']}（slot_id: {slot['slot_id']}）"
                    for slot in slots
                )
            else:
                slot_text = "近 7 天暂无空档"

            lines.append(
                f"{stylist['name']}：擅长 {stylist['specialty']}，{stylist['experience_years']} 年经验，评分 {stylist['rating']}，最近空档 {slot_text}。"
            )

        knowledge = result["knowledge"]
        if knowledge:
            lines.append(f"护理提醒：{knowledge[0]['content']}")

        lines.append("你如果想直接预约，我建议下一步先确定发型师，再用 `/api/appointments` 传 `stylist_id` 和 `slot_id` 完成下单。")

        return {
            "reply": "\n".join(lines),
            "actions": ["search_stylists", "check_availability"],
        }

    def _build_booking_result(
        self,
        message: str,
        phone: str,
        name: Optional[str],
    ) -> Dict[str, Any]:
        service_type = self._extract_service_type(message)
        if not service_type:
            return {
                "reply": "可以预约。还差一个服务项目，你可以告诉我是烫、染、护理、造型还是头皮护理。",
                "actions": ["clarify_service_type"],
            }

        name = name or self._extract_customer_name(message)
        if not name:
            return {
                "reply": "可以预约。为了创建客户档案，还需要你的姓名；你可以在聊天请求里带上 `name`，或直接说“我叫张三，预约护理”。",
                "actions": ["clarify_customer_name"],
            }

        slot_info = self._find_requested_slot(message, service_type)
        if not slot_info["success"]:
            return {
                "reply": slot_info["reply"],
                "actions": slot_info["actions"],
            }

        result = client_appointment_service.book_appointment(
            customer_phone=phone,
            customer_name=name,
            stylist_id=slot_info["stylist_id"],
            slot_id=slot_info["slot_id"],
            service=service_type,
            notes=f"来自聊天预约：{message}",
        )

        if not result.get("success"):
            return {
                "reply": f"预约没有成功：{result.get('error', '未知错误')}。你可以换一个时间，我再帮你查空档。",
                "actions": ["book_appointment_failed"],
            }

        appointment_time = self._format_iso_datetime(result["appointment_datetime"])
        status_text = "已提交，等待店长确认" if result.get("status") == "pending" else "已确认"
        return {
            "reply": (
                f"预约{status_text}。已为{name}预约 {appointment_time} 的{service_type}服务，"
                f"预约编号：{result['appointment_id']}。"
            ),
            "actions": ["book_appointment"],
        }

    def _build_appointment_summary(self, phone: str) -> Dict[str, Any]:
        appointments = client_appointment_service.get_customer_appointments(phone)
        if not appointments:
            return {
                "reply": "我还没有查到你的预约记录。如果你是第一次来店，可以先告诉我想做的项目，我帮你推荐发型师和时间。",
                "actions": ["lookup_appointments"],
            }

        sorted_appointments = sorted(
            appointments,
            key=lambda item: item["appointment_datetime"],
        )

        lines = ["我查到你当前的预约记录："]
        for appointment in sorted_appointments[:5]:
            appointment_time = self._format_iso_datetime(appointment["appointment_datetime"])
            status = STATUS_LABELS.get(appointment["status"], appointment["status"])
            lines.append(
                f"{appointment_time}，{appointment['stylist_name']}，项目：{appointment['service']}，状态：{status}。"
            )

        lines.append("如果你要改约或取消，我也可以先帮你列出记录，再配合 `/api/appointments/{appointment_id}` 完成操作。")

        return {
            "reply": "\n".join(lines),
            "actions": ["lookup_appointments"],
        }

    def _build_cancel_result(self, message: str, phone: str) -> Dict[str, Any]:
        appointments = [
            appointment
            for appointment in client_appointment_service.get_customer_appointments(phone)
            if appointment["status"] != "cancelled"
        ]
        if not appointments:
            return {
                "reply": "目前没有查到你可取消的预约记录。",
                "actions": ["lookup_appointments"],
            }

        appointment_id = self._extract_uuid(message)
        if appointment_id:
            matched = next(
                (
                    appointment
                    for appointment in appointments
                    if appointment["appointment_id"] == appointment_id
                ),
                None,
            )
            if not matched:
                return {
                    "reply": "我没有在你的可取消预约里找到这个预约编号，请确认 `appointment_id` 是否正确。",
                    "actions": ["cancel_appointment_denied"],
                }
            return self._cancel_appointment(appointment_id)

        matched_appointments = self._filter_appointments_for_cancel(message, appointments)
        if not matched_appointments:
            return {
                "reply": "我没有找到符合这些条件的可取消预约。你可以换个描述，或者提供准确的 `appointment_id`。",
                "actions": ["cancel_appointment_not_found"],
            }
        if len(matched_appointments) == 1:
            return self._cancel_appointment(matched_appointments[0]["appointment_id"])

        lines = ["你当前的预约如下，取消时可以使用对应的 `appointment_id` 调用 `/api/appointments/{appointment_id}`："]
        for appointment in matched_appointments[:5]:
            appointment_time = self._format_iso_datetime(appointment["appointment_datetime"])
            lines.append(
                f"{appointment_time}，{appointment['stylist_name']}，项目：{appointment['service']}，appointment_id：{appointment['appointment_id']}。"
            )

        return {
            "reply": "\n".join(lines),
            "actions": ["lookup_appointments", "clarify_cancel_appointment"],
        }

    def _cancel_appointment(self, appointment_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            success = AppointmentService.cancel_appointment(db, appointment_id)
        finally:
            db.close()

        if not success:
            return {
                "reply": "取消失败，这条预约可能已经不存在或状态发生了变化。",
                "actions": ["cancel_appointment_failed"],
            }

        return {
            "reply": f"预约已取消，预约编号：{appointment_id}。",
            "actions": ["cancel_appointment"],
        }

    def _build_fallback_reply(self, name: Optional[str] = None) -> Dict[str, Any]:
        greeting_name = f"{name}，" if name else ""
        return {
            "reply": (
                f"{greeting_name}我现在可以帮你做 3 件事："
                "1. 回答护发/头皮/产品问题；"
                "2. 推荐擅长某类项目的发型师并查看空档；"
                "3. 查询你已有的预约记录。"
                "你可以直接说“推荐一个擅长染发的发型师”或“帮我查下我的预约”。"
            ),
            "actions": ["fallback_guidance"],
        }

    def _is_knowledge_request(self, message: str) -> bool:
        return any(keyword in message for keyword in KNOWLEDGE_KEYWORDS)

    def _is_stylist_request(self, message: str) -> bool:
        if any(keyword in message for keyword in STYLIST_KEYWORDS + AVAILABILITY_KEYWORDS):
            return True
        return "预约" in message and self._extract_service_type(message) is not None

    def _is_appointment_lookup(self, message: str) -> bool:
        return any(keyword in message for keyword in APPOINTMENT_LOOKUP_KEYWORDS)

    def _is_cancel_request(self, message: str) -> bool:
        return any(keyword in message for keyword in APPOINTMENT_CANCEL_KEYWORDS)

    def _is_booking_request(self, message: str) -> bool:
        if any(keyword in message for keyword in APPOINTMENT_LOOKUP_KEYWORDS):
            return False
        return any(keyword in message for keyword in APPOINTMENT_BOOKING_KEYWORDS)

    def _extract_service_type(self, message: str) -> Optional[str]:
        for keyword in SERVICE_KEYWORDS:
            if keyword in message:
                return keyword
        return None

    def _find_requested_slot(self, message: str, service_type: str) -> Dict[str, Any]:
        slot_id = self._extract_uuid(message)
        if slot_id:
            return self._find_slot_by_id(slot_id)

        requested_date = self._extract_date(message)
        requested_time = self._extract_time(message)
        stylist_name = self._extract_stylist_name(message)

        if not stylist_name:
            return {
                "success": False,
                "reply": "可以预约。还差发型师信息，你可以先说“推荐护理发型师”，或直接说“预约张也明天 10 点护理”。",
                "actions": ["clarify_stylist"],
            }
        if not requested_date or not requested_time:
            return {
                "success": False,
                "reply": "可以预约。还差具体时间，你可以说“今天 9 点”“明天 10 点”，或者使用前面推荐里的 `slot_id`。",
                "actions": ["clarify_time"],
            }

        db = SessionLocal()
        try:
            stylists = StylistService.search_stylists_by_specialty(db, service_type)
            stylist = next((item for item in stylists if item.user.name in stylist_name or stylist_name in item.user.name), None)
            if not stylist:
                return {
                    "success": False,
                    "reply": f"我没有找到同时匹配“{stylist_name}”和“{service_type}”的可用发型师。你可以换一位老师，或先让我推荐。",
                    "actions": ["search_stylists"],
                }

            slot = db.query(StylistTimeSlot).filter(
                StylistTimeSlot.stylist_id == stylist.id,
                StylistTimeSlot.date == requested_date,
                StylistTimeSlot.time == requested_time,
                StylistTimeSlot.is_booked == False,
            ).first()
            if not slot:
                return {
                    "success": False,
                    "reply": f"{stylist.user.name} 在 {requested_date} {requested_time} 暂时没有可用空档。你可以换个时间，或让我重新查最近空档。",
                    "actions": ["check_availability"],
                }

            return {
                "success": True,
                "slot_id": str(slot.id),
                "stylist_id": str(stylist.id),
            }
        finally:
            db.close()

    def _find_slot_by_id(self, slot_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            slot = db.query(StylistTimeSlot).filter(
                StylistTimeSlot.id == uuid.UUID(slot_id),
                StylistTimeSlot.is_booked == False,
            ).first()
            if not slot:
                return {
                    "success": False,
                    "reply": "这个时间槽不存在或已经被预约了。你可以换一个 `slot_id`，或让我重新查询空档。",
                    "actions": ["check_availability"],
                }
            return {
                "success": True,
                "slot_id": str(slot.id),
                "stylist_id": str(slot.stylist_id),
            }
        except ValueError:
            return {
                "success": False,
                "reply": "`slot_id` 格式不正确。你可以使用空档列表里返回的完整 `slot_id`。",
                "actions": ["clarify_slot_id"],
            }
        finally:
            db.close()

    def _extract_uuid(self, message: str) -> Optional[str]:
        match = re.search(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            message,
        )
        return match.group(0) if match else None

    def _extract_date(self, message: str) -> Optional[str]:
        today = datetime.now().date()
        if "今天" in message:
            return today.strftime("%Y-%m-%d")
        if "明天" in message:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")

        match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", message)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        return None

    def _extract_time(self, message: str) -> Optional[str]:
        match = re.search(r"(\d{1,2})[:：](\d{2})", message)
        if match:
            hour, minute = match.groups()
            return f"{int(hour):02d}:{int(minute):02d}"

        match = re.search(r"(\d{1,2})\s*点", message)
        if match:
            return f"{int(match.group(1)):02d}:00"
        return None

    def _extract_stylist_name(self, message: str) -> Optional[str]:
        db = SessionLocal()
        try:
            for stylist in StylistService.get_all_stylists(db):
                if stylist.user.name in message:
                    return stylist.user.name
        finally:
            db.close()
        return None

    def _extract_customer_name(self, message: str) -> Optional[str]:
        match = re.search(r"我叫([\u4e00-\u9fa5]{2,6})", message)
        if match:
            return match.group(1)
        match = re.search(r"我是([\u4e00-\u9fa5]{2,6})", message)
        if match:
            return match.group(1)
        return None

    def _filter_appointments_for_cancel(
        self,
        message: str,
        appointments: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        service_type = self._extract_service_type(message)
        stylist_name = self._extract_stylist_name(message)
        requested_date = self._extract_date(message)
        requested_time = self._extract_time(message)

        matched = appointments
        has_filter = False
        if service_type:
            has_filter = True
            matched = [
                appointment
                for appointment in matched
                if appointment["service"] == service_type
            ]
        if stylist_name:
            has_filter = True
            matched = [
                appointment
                for appointment in matched
                if appointment["stylist_name"] == stylist_name
            ]
        if requested_date:
            has_filter = True
            matched = [
                appointment
                for appointment in matched
                if appointment["appointment_datetime"].startswith(requested_date)
            ]
        if requested_time:
            has_filter = True
            matched = [
                appointment
                for appointment in matched
                if self._format_iso_datetime(appointment["appointment_datetime"]).endswith(requested_time)
            ]

        return matched if has_filter else appointments

    def _format_iso_datetime(self, value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value


chat_agent = ChatAgent()
