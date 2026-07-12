"""客户留存运营 Graph。

这个 Graph 只做客户分层和建议生成，不自动给客户发消息、不自动扣款，也不修改预约。
执行结果会由 API 保存到 AgentTaskState，便于复盘本次扫描的依据。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, TypedDict

from backend.database.connection import SessionLocal
from backend.database.models import Member, User, UserRole, WalletAccount
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
    trace_id: str
    trace: dict[str, Any]


def collect_candidates(state: RetentionState) -> RetentionState:
    db = SessionLocal()
    candidates: list[dict[str, Any]] = []
    now = datetime.now()
    try:
        customers = db.query(User).filter(User.role == UserRole.CUSTOMER).all()
        for customer in customers:
            wallet = db.query(WalletAccount).filter(WalletAccount.user_id == customer.id).first()
            member = db.query(Member).filter(Member.user_id == customer.id).first()
            if customer.last_visit and (now - customer.last_visit).days >= 60:
                candidates.append({
                    "segment": "churn_risk",
                    "customer_id": str(customer.id),
                    "name": customer.name,
                    "phone": customer.phone,
                    "reason": f"距上次到店 {(now - customer.last_visit).days} 天",
                })
            if wallet and wallet.balance_cents > 0:
                candidates.append({
                    "segment": "balance_customer",
                    "customer_id": str(customer.id),
                    "name": customer.name,
                    "phone": customer.phone,
                    "reason": f"账户余额 ￥{wallet.balance_cents / 100:.2f}",
                })
            if member and member.expires_at and member.expires_at <= now + timedelta(days=30):
                days = (member.expires_at.date() - now.date()).days
                candidates.append({
                    "segment": "membership_expiring",
                    "customer_id": str(customer.id),
                    "name": customer.name,
                    "phone": customer.phone,
                    "reason": "会员已到期" if days < 0 else f"会员将在 {days} 天后到期",
                })
    finally:
        db.close()
    return trace_node({**state, "candidates": candidates}, "collect_candidates", detail={"candidate_count": len(candidates)})


def classify_candidates(state: RetentionState) -> RetentionState:
    summary = {"churn_risk": 0, "balance_customer": 0, "membership_expiring": 0}
    for item in state.get("candidates", []):
        summary[item["segment"]] = summary.get(item["segment"], 0) + 1
    return trace_node({**state, "summary": summary}, "classify_candidates", detail={"segments": summary})


def generate_recommendations(state: RetentionState) -> RetentionState:
    messages = {
        "churn_risk": "您好，最近有一段时间没见到您了，想帮您安排一次护理或造型吗？",
        "balance_customer": "您好，您账户还有余额，最近有需要安排护理或造型吗？我可以帮您看看时间。",
        "membership_expiring": "您好，您的会员权益即将到期，欢迎提前安排一次到店服务，我们可以帮您确认续期方案。",
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
    return {"summary": state.get("summary", {}), "recommendations": state.get("recommendations", []), "trace_id": state.get("trace_id"), "trace": state.get("trace", {})}

