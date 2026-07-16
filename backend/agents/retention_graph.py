"""客户留存建议 Graph。

规则引擎先决定谁能被联系并创建 RetentionTask；本 Graph 只把任务整理为
可解释、可编辑且不虚构优惠的建议。当前安全模板是稳定主路径，后续接入模型时
也必须遵守同一份结构化输入输出协议。
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, TypedDict

from backend.agents.trace import new_trace, trace_node
from backend.database.connection import SessionLocal
from backend.database.models import RetentionTask, User, UserRole
from backend.database.retention import (
    BIRTHDAY_LOOKAHEAD_DAYS,
    CHURN_THRESHOLD_DAYS,
    REPURCHASE_BUFFER,
    RetentionService,
)

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover
    END = START = StateGraph = None


class RetentionState(TypedDict, total=False):
    requester_id: str
    candidates: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    summary: dict[str, int]
    analysis_basis: dict[str, Any]
    trace_id: str
    trace: dict[str, Any]


def _task_candidate(task: RetentionTask) -> dict[str, Any]:
    trigger_types = [item.get("type") for item in (task.trigger_reasons or [])]
    risk_flags: list[str] = []
    if "balance_customer" in (task.strategy_tags or []):
        risk_flags.append("余额客户：只能陈述真实余额，不得制造余额失效紧迫感")
    if len(trigger_types) > 1:
        risk_flags.append("多触发原因已合并为一个任务，避免重复触达")

    if task.primary_type.value == "birthday":
        strategy = "birthday_care"
    elif task.primary_type.value == "repurchase":
        strategy = "repurchase_reminder"
    elif "balance_customer" in (task.strategy_tags or []):
        strategy = "balance_service_care"
    else:
        strategy = "churn_care"

    return {
        "task_id": str(task.id),
        "segment": task.primary_type.value,
        "primary_type": task.primary_type.value,
        "customer_id": str(task.customer_id),
        "name": task.customer.name if task.customer else "未知",
        "phone": task.customer.phone if task.customer else None,
        "reason": task.suggestion_reason or "符合留存规则",
        "evidence": task.evidence or {},
        "trigger_reasons": task.trigger_reasons or [],
        "strategy_tags": task.strategy_tags or [],
        "strategy": strategy,
        "suggested_message": task.suggested_message or "您好，近期如需预约，我可以帮您安排合适的时间。",
        "coupon_id": None,
        "coupon_reason": "当前系统未配置可校验的优惠券，未推荐优惠券。",
        "risk_flags": risk_flags,
        "agent_mode": "safe_template",
        "explainable": True,
    }


def collect_candidates(state: RetentionState) -> RetentionState:
    db = SessionLocal()
    now = datetime.now()
    try:
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
        scan_result = RetentionService.scan_and_generate(db, now=now)
        tasks = RetentionService.list_tasks(db, today_only=True)
        candidates = [_task_candidate(task) for task in tasks]
        analysis_basis = {
            "scope": "全店客户",
            "scanned_customer_count": len(customers),
            "created_task_count": scan_result["total"],
            "data_sources": ["历史到店记录", "最近服务项目", "账户余额", "联系记录", "忽略与退订记录"],
            "agent_mode": "safe_template",
            "rules": [
                {
                    "segment": "churn_risk",
                    "label": "流失风险",
                    "description": f"距上次到店达到 {CHURN_THRESHOLD_DAYS} 天；有余额时调整为余额服务策略",
                },
                {
                    "segment": "birthday",
                    "label": "生日提醒",
                    "description": f"客户生日进入未来 {BIRTHDAY_LOOKAHEAD_DAYS} 天提醒窗口",
                },
                {
                    "segment": "repurchase",
                    "label": "复购提醒",
                    "description": f"距上次到店达到个人复购周期的 {REPURCHASE_BUFFER} 倍，且不足 {CHURN_THRESHOLD_DAYS} 天",
                },
                {
                    "segment": "contact_guard",
                    "label": "触达保护",
                    "description": "退订、忽略、人工跟进和冷却期优先于所有提醒规则",
                },
            ],
        }
    finally:
        db.close()
    return trace_node(
        {**state, "candidates": candidates, "analysis_basis": analysis_basis},
        "collect_candidates",
        detail={"candidate_count": len(candidates), "scanned_customer_count": len(customers)},
    )


def classify_candidates(state: RetentionState) -> RetentionState:
    summary = {"churn_risk": 0, "birthday": 0, "repurchase": 0, "balance_customer": 0}
    for item in state.get("candidates", []):
        summary[item["segment"]] = summary.get(item["segment"], 0) + 1
        if "balance_customer" in item.get("strategy_tags", []):
            summary["balance_customer"] += 1
    return trace_node({**state, "summary": summary}, "classify_candidates", detail={"segments": summary})


def generate_recommendations(state: RetentionState) -> RetentionState:
    """安全模板已在规则任务中生成；这里固定结构，方便后续 LLM 替换。"""
    recommendations = state.get("candidates", [])
    return trace_node(
        {**state, "recommendations": recommendations},
        "generate_recommendations",
        detail={"recommendation_count": len(recommendations), "agent_mode": "safe_template"},
    )


@lru_cache(maxsize=1)
def build_retention_graph():
    if StateGraph is None:
        return None
    graph = StateGraph(RetentionState)
    graph.add_node("collect_candidates", collect_candidates)
    graph.add_node("classify_candidates", classify_candidates)
    graph.add_node("generate_recommendations", generate_recommendations)
    graph.add_edge(START, "collect_candidates")
    graph.add_edge("collect_candidates", "classify_candidates")
    graph.add_edge("classify_candidates", "generate_recommendations")
    graph.add_edge("generate_recommendations", END)
    return graph.compile()


def run_retention_graph(requester_id: str) -> dict[str, Any]:
    state: RetentionState = {"requester_id": requester_id, **new_trace("retention_segmentation")}
    graph = build_retention_graph()
    if graph is None:
        state = collect_candidates(state)
        state = classify_candidates(state)
        state = generate_recommendations(state)
    else:
        state = graph.invoke(state)
    return {
        "summary": state.get("summary", {}),
        "recommendations": state.get("recommendations", []),
        "analysis_basis": state.get("analysis_basis", {}),
        "trace_id": state.get("trace_id"),
        "trace": state.get("trace", {}),
    }
