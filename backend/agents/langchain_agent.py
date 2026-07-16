"""LangChain tool-calling Agent — LLM 负责意图理解与工具编排。

架构（相比旧版是反过来的）：
- 有 LLM key 时：LLM 用 tool-calling 自主选择/调用工具、多轮追问，规则退到
  工具内部做护栏（不许编造 slot_id/预约、下单前校验）。
- 无 LLM key 时：自动降级到规则版 ChatAgent，保证任何环境都能跑。

对外两套皮肤共用同一内核，靠 system prompt + 工具集切换：
- role="customer" → C 端顾客顾问
- role="staff"    → B 端店员助手
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from backend.agents.chat_agent import chat_agent
from backend.agents.staff_operation_planner import (
    LLM_PLANNER_PROMPT,
    StaffOperationPlan,
    fallback_staff_operation_plan,
)
from backend.agents.tools import build_customer_tools, build_staff_tools
from backend.config import settings
from backend.database.connection import SessionLocal
from backend.database.service import StylistService

try:
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI
except Exception as exc:  # pragma: no cover - optional runtime path
    create_agent = None
    HumanMessage = None
    ChatOpenAI = None
    _LANGCHAIN_IMPORT_ERROR = exc
else:
    _LANGCHAIN_IMPORT_ERROR = None


CUSTOMER_SYSTEM_PROMPT = (
    "你是美发门店的私人护发顾问，服务于当前正在对话的顾客。你的目标是：像一位懂"
    "这家店、也懂顾客头发的资深顾问一样，帮顾客解答护理问题、推荐合适的发型师、"
    "完成预约与改约。\n"
    "工作准则：\n"
    "1. 护理知识必须通过 search_knowledge 检索后再回答，不要凭空编造护理建议。\n"
    "2. 发型师、空档、价格只能来自工具返回的真实数据。stylist_id / slot_id / "
    "appointment_id 一律使用工具返回的原值，绝不能自己编造或猜测。\n"
    "3. 下单前若信息不全（缺项目、缺时间、缺发型师），主动向顾客追问，不要擅自替"
    "顾客做决定。\n"
    "4. 取消预约前先用 lookup_my_appointments 核对，只操作顾客本人的预约。\n"
    "5. 用户问什么先回答什么，不要用欢迎语、反问或泛泛介绍替代答案。\n"
    "6. 不要重复问候；除非用户先打招呼，否则不要每轮都说“您好/欢迎”。\n"
    "7. 回复简洁、礼貌、口语化，适合直接展示给顾客。"
)

STAFF_SYSTEM_PROMPT = (
    "你是美发门店的店长内部助手，服务对象是拥有最高工作台权限的店长，不是顾客。你的目标是帮店长"
    "查询信息，并通过受控工作台能力完成预约、服务、退款和留存操作。\n"
    "工作准则：\n"
    "1. 所有数据（日程、会员、顾客历史）必须来自工具真实返回，不要编造。\n"
    "2. 护理话术通过 search_knowledge 检索后给出。\n"
    "3. 对工作台写操作先确认对象和参数；退款、改约、完成服务必须等待店长确认。\n"
    "4. 你不能直接拼接 SQL、接口地址或业务 ID，实际写入必须交给后端白名单能力。\n"
    "5. 回复面向店长，可以简洁列点，便于快速执行。"
)


class LangChainAgent:
    """LangChain tool-calling 入口，带规则 Agent 降级。"""

    def __init__(self):
        self.enabled = bool(settings.LLM_API_KEY and ChatOpenAI and create_agent)
        self.llm = self._build_llm() if self.enabled else None

    def _build_llm(self):
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            temperature=0.2,
        )

    def handle_message(
        self,
        message: str,
        phone: str,
        name: Optional[str] = None,
        role: str = "customer",
    ) -> Dict[str, Any]:
        # 无 key 或 LangChain 不可用 → 规则 Agent 降级
        if not self.enabled or not self.llm:
            if _LANGCHAIN_IMPORT_ERROR:
                logger.warning(f"LangChain unavailable, fallback to rule agent: {_LANGCHAIN_IMPORT_ERROR}")
            result = self._run_rule_fallback(message=message, phone=phone, name=name, role=role)
            result["actions"] = ["rule_agent_fallback", *result.get("actions", [])]
            return result

        direct_reply = self._maybe_direct_customer_reply(message=message, role=role)
        if direct_reply:
            return direct_reply

        try:
            return self._run_agent(message=message, phone=phone, name=name, role=role)
        except Exception as exc:
            logger.warning(f"LangChain agent failed, fallback to rule agent: {exc}")
            result = self._run_rule_fallback(message=message, phone=phone, name=name, role=role)
            result["actions"] = ["rule_agent_fallback", *result.get("actions", [])]
            return result

    def plan_staff_operation(self, message: str) -> StaffOperationPlan:
        """先走本地高确定性解析，只有无法识别时才请求 LLM 结构化规划。"""
        fallback = fallback_staff_operation_plan(message)
        known_module_words = (
            "预约", "退款", "核验", "核销", "服务", "留存", "提醒", "会员", "客户",
        )
        if (
            fallback.action != "unknown"
            or any(word in message for word in known_module_words)
            or not self.enabled
            or not self.llm
        ):
            return fallback

        try:
            response = self.llm.invoke(
                f"{LLM_PLANNER_PROMPT}\n\n只输出一个 JSON 对象，不要 Markdown 代码块。员工原话：{message}"
            )
            content = getattr(response, "content", response)
            if not isinstance(content, str):
                content = str(content)
            matched = re.search(r"\{.*\}", content, re.DOTALL)
            if not matched:
                return fallback
            return StaffOperationPlan.model_validate(json.loads(matched.group(0)))
        except Exception as exc:  # pragma: no cover - depends on configured provider
            logger.warning(f"Staff operation planner failed, using local parser: {exc}")
            return fallback

    @staticmethod
    def _run_rule_fallback(
        message: str,
        phone: str,
        name: Optional[str],
        role: str,
    ) -> Dict[str, Any]:
        if role == "staff":
            from backend.agents.staff_graph import run_staff_query

            return run_staff_query(message, requester_id=phone)
        return chat_agent.handle_message(message=message, phone=phone, name=name)

    def _build_tools(self, phone: str, name: Optional[str], role: str) -> List:
        if role == "staff":
            return build_staff_tools()
        return build_customer_tools(phone=phone, name=name)

    def _run_agent(
        self,
        message: str,
        phone: str,
        name: Optional[str],
        role: str,
    ) -> Dict[str, Any]:
        tools = self._build_tools(phone, name, role)
        system_prompt = STAFF_SYSTEM_PROMPT if role == "staff" else CUSTOMER_SYSTEM_PROMPT

        agent = create_agent(self.llm, tools, system_prompt=system_prompt)
        outcome = agent.invoke({"messages": [HumanMessage(content=message)]})

        messages = outcome.get("messages", [])

        # 从 AIMessage.tool_calls 提取实际调用了哪些工具，作为 actions 返回
        called_tools: List[str] = []
        reply = ""
        for msg in messages:
            for call in getattr(msg, "tool_calls", None) or []:
                tool_name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                if tool_name:
                    called_tools.append(tool_name)
            # 最后一条 AI 文本消息即为回复
            if getattr(msg, "type", None) == "ai" and getattr(msg, "content", None):
                reply = msg.content if isinstance(msg.content, str) else reply

        actions = [f"langchain_agent:{role}", *called_tools]
        source_map = {
            "get_salon_schedule": "database:staff_schedule",
            "get_birthday_members": "database:members",
            "lookup_customer": "database:customers",
            "query_membership": "database:members",
            "get_retention_reminders": "database:reminder_logs",
            "search_knowledge": "rag:haircare_knowledge",
        }
        sources = list(dict.fromkeys(source_map[name] for name in called_tools if name in source_map))

        return {
            "reply": reply,
            "actions": actions,
            "sources": sources,
        }

    def _maybe_direct_customer_reply(self, message: str, role: str) -> Optional[Dict[str, Any]]:
        if role != "customer":
            return None

        text = message.strip()
        compact = text.replace(" ", "")

        if self._is_teacher_overview_question(compact):
            stylists = self._pick_stylist_examples()
            if len(stylists) >= 2:
                first, second = stylists[:2]
                return {
                    "reply": (
                        f"有的，先给你举两个比较常约的老师：\n"
                        f"1. {first['name']}：擅长{first['specialty']}，评分 {first['rating']}。\n"
                        f"2. {second['name']}：擅长{second['specialty']}，评分 {second['rating']}。\n"
                        "你想做烫、染、护理还是造型？我再按项目和时间帮你细推。"
                    ),
                    "actions": ["direct_stylist_examples"],
                }

        if self._is_perm_or_color_request(compact):
            stylists = self._pick_stylist_examples(keywords=("烫", "染"), limit=2)
            if stylists:
                lines = ["烫染的话，可以先看这两位："]
                for index, stylist in enumerate(stylists, start=1):
                    lines.append(
                        f"{index}. {stylist['name']}：擅长{stylist['specialty']}，评分 {stylist['rating']}。"
                    )
                lines.append("如果你偏自然卷感，我会优先推荐擅长烫的老师；如果更看重发色显白，就优先看染发强的老师。你想今天约还是明天约？")
                return {
                    "reply": "\n".join(lines),
                    "actions": ["direct_perm_color_recommendation"],
                }

        return None

    def _is_teacher_overview_question(self, text: str) -> bool:
        teacher_words = ("老师", "发型师", "设计师")
        ask_words = ("哪个", "哪些", "有什么", "有哪些", "推荐", "谁")
        return any(word in text for word in teacher_words) and any(word in text for word in ask_words)

    def _is_perm_or_color_request(self, text: str) -> bool:
        if len(text) > 12:
            return False
        return "烫染" in text or ("烫" in text and "染" in text) or text in {"烫发", "染发", "想烫", "想染"}

    def _pick_stylist_examples(self, keywords: tuple[str, ...] = (), limit: int = 2) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            stylists = StylistService.get_all_stylists(db)
            if keywords:
                matched = [
                    stylist for stylist in stylists
                    if any(keyword in stylist.specialty for keyword in keywords)
                ]
                stylists = matched or stylists
            stylists = sorted(stylists, key=lambda item: item.rating or 0, reverse=True)
            return [
                {
                    "name": stylist.user.name,
                    "specialty": stylist.specialty,
                    "rating": stylist.rating,
                }
                for stylist in stylists[:limit]
            ]
        finally:
            db.close()


langchain_agent = LangChainAgent()
# 向后兼容旧引用名
langchain_agent_adapter = langchain_agent
