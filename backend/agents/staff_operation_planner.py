"""店长 Agent 的结构化操作规划。

这个模块只把自然语言转换为受控计划，不执行数据库写操作。执行权留在
工作台路由和业务服务中，避免模型直接拼接 SQL、接口地址或业务状态。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


StaffAction = Literal[
    "unknown",
    "appointment.create",
    "appointment.approve",
    "appointment.change",
    "service.verify",
    "service.complete",
    "refund.approve",
    "refund.reject",
    "retention.scan",
    "retention.send",
    "retention.manual_followup",
    "retention.ignore",
    "retention.reply",
    "retention.close",
    "retention.reminder_contacted",
    "retention.reminder_dismiss",
    "read.schedule",
    "read.customer",
    "read.membership",
    "read.retention",
    "read.knowledge",
]


class StaffOperationPlan(BaseModel):
    """LLM 或本地解析器生成的最小可执行计划。"""

    action: StaffAction = "unknown"
    target_scope: Literal["single", "batch", "none"] = "none"
    customer_name: str | None = None
    customer_phone: str | None = None
    task_id: str | None = None
    appointment_id: str | None = None
    service: str | None = None
    date: str | None = None
    time: str | None = None
    stylist_name: str | None = None
    days_since_visit: int | None = Field(None, ge=1, le=3650)
    reminder_type: Literal["birthday", "repurchase", "churn_risk"] | None = None
    message: str | None = None
    reason: str | None = None
    ignore_mode: Literal["30_days", "90_days", "permanent", "unsubscribe"] | None = None
    needs_confirmation: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    interpretation: str = ""
    clarification: str | None = None


_SEND_WORDS = (
    "发送", "发消息", "发通知", "发出", "发了", "发一下", "发一次消息", "发一条消息",
    "发送一条", "发短信", "联系", "联系一下", "推送",
)
_BATCH_WORDS = ("全部", "所有", "批量", "一键", "一起", "都", "全量")
_UUID_PATTERN = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"


def _compact(message: str) -> str:
    return re.sub(r"\s+", "", message.strip())


def _extract_message(message: str) -> str | None:
    matched = re.search(r"[：:](.+)$", message.strip())
    return matched.group(1).strip() if matched else None


def _extract_days(message: str) -> int | None:
    compact = _compact(message)
    chinese_days = {
        "两百": 200,
        "二百": 200,
        "一百五十": 150,
        "一百": 100,
        "九十": 90,
        "六十": 60,
        "三十": 30,
    }
    if any(
        f"{token}天" in compact and _has_any(compact, ("以上", "超过", "未到店", "没到店", "未回店", "没回店"))
        for token in chinese_days
    ):
        return next(value for token, value in chinese_days.items() if f"{token}天" in compact)
    patterns = (
        r"(?:超过|大于|至少|达到|满|未到店|没到店|未回店|没回店)(\d+)天",
        r"(\d+)天(?:以上|没有到店|未到店|没到店|未回店|没回店)",
        r"距上次到店(\d+)天",
    )
    for pattern in patterns:
        matched = re.search(pattern, compact)
        if matched:
            return int(matched.group(1))
    return None


def _extract_target(message: str) -> tuple[str | None, str | None, str | None]:
    compact = _compact(message)
    phone = re.search(r"1[3-9]\d{9}", compact)
    identifier = re.search(_UUID_PATTERN, compact)
    if phone:
        return None, phone.group(0), identifier.group(0) if identifier else None
    return None, None, identifier.group(0) if identifier else None


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def fallback_staff_operation_plan(message: str) -> StaffOperationPlan:
    """没有 LLM 时的本地解析器，保证离线环境也能安全运行。"""
    compact = _compact(message)
    customer_name, customer_phone, identifier = _extract_target(message)
    days_since_visit = _extract_days(message)
    message_content = _extract_message(message)

    reminder_type = None
    if "生日" in compact:
        reminder_type = "birthday"
    elif _has_any(compact, ("流失", "未到店", "没到店", "没回店", "未回店")):
        reminder_type = "churn_risk"
    elif "复购" in compact:
        reminder_type = "repurchase"

    action: StaffAction = "unknown"
    needs_confirmation = False
    interpretation = ""

    if "退款" in compact and _has_any(compact, ("拒绝", "驳回", "不通过")):
        action, needs_confirmation = "refund.reject", True
    elif "退款" in compact and _has_any(compact, ("通过", "同意", "批准", "批复")):
        action, needs_confirmation = "refund.approve", True
    elif "预约" in compact and _has_any(compact, ("改约", "改到", "改成", "调整", "换个发型师", "换一个时间", "换时间")):
        action, needs_confirmation = "appointment.change", True
    elif "预约" in compact and _has_any(compact, ("批复", "审核通过", "批准", "同意", "确认")):
        action, needs_confirmation = "appointment.approve", True
    elif "预约" in compact and _has_any(compact, ("代约", "安排", "预定", "预订", "约一下", "下一个预约", "帮我给", "替")):
        action = "appointment.create"
    elif _has_any(compact, ("完成服务", "核销", "扣套餐", "录入消费")):
        action, needs_confirmation = "service.complete", True
    elif _has_any(compact, ("核验", "登记服务", "录入服务")) and _has_any(compact, ("服务", "护理", "金额", "套餐")):
        action = "service.verify"
    elif _has_any(compact, ("扫描", "扫描一下", "生成任务", "运行扫描", "运行今日")) and _has_any(compact, ("留存", "今日")):
        action = "retention.scan"
    elif "提醒" in compact and _has_any(compact, ("已联系", "标记联系")):
        action = "retention.reminder_contacted"
    elif "提醒" in compact and _has_any(compact, ("忽略", "不处理")):
        action = "retention.reminder_dismiss"
    elif _has_any(compact, ("转人工", "人工跟进")):
        action = "retention.manual_followup"
    elif _has_any(compact, ("忽略", "不再联系", "退订")) and "留存" in compact:
        action = "retention.ignore"
    elif _has_any(compact, ("记录回复", "客户回复")):
        action = "retention.reply"
    elif ("关闭" in compact and _has_any(compact, ("留存", "跟进", "任务"))) or "完成跟进" in compact:
        action = "retention.close"
    elif _has_any(compact, _SEND_WORDS) and _has_any(compact, ("留存", "生日", "回访", "未到店", "流失", "复购", "客户")):
        action = "retention.send"
    elif "留存" in compact and _has_any(compact, ("查询", "查看", "看看", "哪些", "谁", "任务", "提醒")):
        action = "read.retention"
    elif "预约" in compact and _has_any(compact, ("今天", "明天", "后天", "有哪些", "看看", "查一下", "日程", "排班")):
        action = "read.schedule"
    elif _has_any(compact, ("日程", "排班", "预约有哪些", "有哪些预约", "预约情况")):
        action = "read.schedule"
    elif _has_any(compact, ("会员", "积分", "余额", "到期")):
        action = "read.membership"
    elif _has_any(compact, ("留存提醒", "需要跟进", "回访谁", "流失客户")):
        action = "read.retention"
    elif _has_any(compact, ("客户历史", "预约记录", "客户资料")):
        action = "read.customer"
    elif _has_any(compact, ("护理知识", "染发后", "烫发后", "头皮护理")):
        action = "read.knowledge"

    target_scope: Literal["single", "batch", "none"] = "none"
    if customer_phone or identifier:
        target_scope = "single"
    if days_since_visit or _has_any(compact, _BATCH_WORDS):
        target_scope = "batch"
    if action in {"retention.send", "retention.ignore", "retention.manual_followup", "retention.close"} and target_scope == "none":
        target_scope = "single"
    if action == "retention.send" and days_since_visit:
        target_scope = "batch"

    interpretation_map = {
        "retention.scan": "运行留存规则扫描，生成今天可处理的留存任务",
        "retention.send": "按筛选条件找到目标客户，并发送留存消息",
        "retention.reminder_contacted": "将指定旧版留存提醒标记为已联系",
        "retention.reminder_dismiss": "将指定旧版留存提醒标记为已忽略",
        "appointment.create": "为指定客户创建一个新的预约",
        "appointment.change": "生成预约调整方案，确认后修改预约",
        "service.complete": "确认完成服务，并同步消费、套餐、积分和绩效",
        "refund.approve": "生成退款通过方案，确认后处理退款和钱包流水",
        "refund.reject": "生成退款拒绝方案，确认后关闭退款申请",
    }
    interpretation = interpretation_map.get(action, "")
    confidence = 0.78 if action != "unknown" else 0.0
    clarification = None
    if action == "unknown":
        clarification = "请说明要操作的工作台模块和动作，例如预约、服务核验、退款或留存提醒。"

    return StaffOperationPlan(
        action=action,
        target_scope=target_scope,
        customer_name=customer_name,
        customer_phone=customer_phone,
        task_id=identifier,
        days_since_visit=days_since_visit,
        reminder_type=reminder_type,
        message=message_content,
        needs_confirmation=needs_confirmation,
        confidence=confidence,
        interpretation=interpretation,
        clarification=clarification,
    )


LLM_PLANNER_PROMPT = """你是门店工作台 Agent 的操作规划器，只负责理解员工指令并输出结构化计划，不执行任何操作。
可用动作：
appointment.create / appointment.approve / appointment.change
service.verify / service.complete
refund.approve / refund.reject
retention.scan / retention.send / retention.manual_followup / retention.ignore / retention.reply / retention.close
retention.reminder_contacted / retention.reminder_dismiss
read.schedule / read.customer / read.membership / read.retention / read.knowledge

规则：
1. “给两百天以上未到店的人员发消息”必须识别为 retention.send、batch、days_since_visit=200、reminder_type=churn_risk。
2. 指定姓名、手机号、预约 ID 或任务 ID时是 single；“全部、所有、批量、一起”或明确人群时是 batch。
3. 退款、改约、完成服务属于高风险动作，needs_confirmation=true。明确的批量留存发送可以直接执行。
4. 不清楚时 action=unknown，并在 clarification 中写出需要员工确认的理解，不要猜客户、预约或任务编号。
5. 只能从上述动作中选择，不能输出接口地址、SQL 或虚构的 ID。
"""
