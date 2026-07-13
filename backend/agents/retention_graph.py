"""客户留存运营 Graph。

这个 Graph 只做客户分层和建议生成，不自动给客户发消息、不自动扣款，也不修改预约。
执行结果会由 API 保存到 AgentTaskState，便于复盘本次扫描的依据。
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, TypedDict

from backend.database.connection import SessionLocal
from backend.database.models import User, UserRole, WalletAccount
from backend.database.retention import CHURN_MULTIPLIER, RetentionService
from backend.agents.trace import new_trace, trace_node

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


def collect_candidates(state: RetentionState) -> RetentionState:
    db = SessionLocal()
    candidates: list[dict[str, Any]] = []
    now = datetime.now()
    try:
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
        analysis_basis = {
            "scope": "全店客户",
            "scanned_customer_count": len(customers),
            "data_sources": ["历史到店记录", "最近服务项目", "账户余额"],
            "rules": [
                {
                    "segment": "churn_risk",
                    "label": "流失风险",
                    "description": "距上次到店达到个人复购周期的 2.5 倍",
                },
                {
                    "segment": "balance_customer",
                    "label": "余额客户",
                    "description": "客户账户余额大于 0",
                },
            ],
        }
        for customer in customers:
            wallet = db.query(WalletAccount).filter(WalletAccount.user_id == customer.id).first()
            if customer.last_visit:
                days_since_last_visit = (now - customer.last_visit).days
                cycle_days, cycle_basis = RetentionService.compute_cycle_days(db, customer)
                threshold_days = round(cycle_days * CHURN_MULTIPLIER)
                if days_since_last_visit >= cycle_days * CHURN_MULTIPLIER:
                    candidates.append({
                        "segment": "churn_risk",
                        "customer_id": str(customer.id),
                        "name": customer.name,
                        "phone": customer.phone,
                        "reason": (
                            f"距上次到店 {days_since_last_visit} 天，{cycle_basis}，"
                            f"已达到流失阈值 {threshold_days} 天"
                        ),
                        "evidence": {
                            "days_since_last_visit": days_since_last_visit,
                            "cycle_days": cycle_days,
                            "threshold_days": threshold_days,
                            "cycle_basis": cycle_basis,
                        },
                    })
            if wallet and wallet.balance_cents > 0:
                candidates.append({
                    "segment": "balance_customer",
                    "customer_id": str(customer.id),
                    "name": customer.name,
                    "phone": customer.phone,
                    "reason": f"账户余额 ￥{wallet.balance_cents / 100:.2f}，可作为回访触发点",
                    "evidence": {
                        "balance_cents": wallet.balance_cents,
                        "balance": round(wallet.balance_cents / 100, 2),
                    },
                })
    finally:
        db.close()
    return trace_node(
        {**state, "candidates": candidates, "analysis_basis": analysis_basis},
        "collect_candidates",
        detail={
            "candidate_count": len(candidates),
            "scanned_customer_count": analysis_basis["scanned_customer_count"],
        },
    )


def classify_candidates(state: RetentionState) -> RetentionState:
    summary = {"churn_risk": 0, "balance_customer": 0}
    for item in state.get("candidates", []):
        summary[item["segment"]] = summary.get(item["segment"], 0) + 1
    return trace_node({**state, "summary": summary}, "classify_candidates", detail={"segments": summary})


def generate_recommendations(state: RetentionState) -> RetentionState:
    messages = {
        "churn_risk": "您好，最近有一段时间没见到您了，想帮您安排一次护理或造型吗？",
        "balance_customer": "您好，您账户还有余额，最近有需要安排护理或造型吗？我可以帮您看看时间。",
    }
    recommendations = [
        {
            **item,
            "suggested_message": messages[item["segment"]],
            "explainable": True,
        }
        for item in state.get("candidates", [])
    ]
    return trace_node({**state, "recommendations": recommendations}, "generate_recommendations", detail={"recommendation_count": len(recommendations)})


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
