"""员工工作台意图检索：向量检索优先，BM25 作为本地降级。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from loguru import logger

from backend.config import settings


@dataclass(frozen=True)
class IntentEntry:
    name: str
    description: str
    examples: tuple[str, ...]


INTENTS = (
    IntentEntry("schedule", "查询全店或指定日期的预约、排班和忙闲情况", (
        "今天有哪些预约", "下午店里忙不忙", "明天谁有客人", "查一下今天的安排",
        "这个门店今天有几单", "给我看一下预约表",
    )),
    IntentEntry("customer", "查询某位客户的预约历史、到店记录和服务项目", (
        "龙百川上次什么时候来的", "查一下李雷做过什么项目", "这个客户有没有预约记录",
        "帮我找张三的历史记录", "13900000000最近来过吗",
    )),
    IntentEntry("membership", "查询客户会员等级、积分、余额和到期信息", (
        "龙百川会员卡还有多少钱", "这个客户积分多少", "会员什么时候到期",
        "查一下李雷卡里余额", "账户还有多少储值",
    )),
    IntentEntry("retention", "查询需要回访、复购、生日或流失跟进的客户", (
        "哪些老客该联系", "今天要回访谁", "谁快流失了", "复购提醒有哪些",
        "看看需要跟进的客户", "生日客户名单",
    )),
    IntentEntry("knowledge", "查询美发护理、染烫、头皮或话术知识", (
        "染发后掉色快怎么办", "烫完多久能洗头", "头皮出油怎么护理",
        "漂到橙黄色怎么校色", "受损发能不能染", "发根染和发尾染有什么区别",
    )),
    IntentEntry("appointment_approval", "店长批复、确认、审核客户提交的待确认预约", (
        "帮我批复龙百川的预约", "确认一下李雷那单预约", "把张三的预约审核通过",
        "同意客户的预约申请", "把待确认预约确认掉", "龙百川那单可以安排",
    )),
    IntentEntry("appointment_change", "调整已存在预约的时间或发型师", (
        "把李雷的预约改到下午", "给张三换个发型师", "调整一下预约时间",
        "改约到明天", "帮客户换一个时间槽",
    )),
    IntentEntry("appointment_create", "店长代客户创建一个新预约", (
        "给龙百川约明天下午", "帮客户安排一个护理", "替李雷下一个预约",
        "给客户订一个染发时间", "门店帮他预约",
    )),
    IntentEntry("service_verification", "核验服务、完成服务、扣套餐次数或记录消费", (
        "核销龙百川的护理", "确认服务已经做完", "给这单扣套餐次数",
        "完成这次服务", "录入客户消费",
    )),
    IntentEntry("refund", "查看、通过或拒绝退款申请", (
        "待退款有哪些", "同意这笔退款", "帮我拒绝退款申请", "退款审核一下",
        "处理客户退款",
    )),
    IntentEntry("retention_action", "发送、重试、关闭或处理留存任务", (
        "给这个客户发送回访消息", "重试发送留存短信", "关闭这个跟进任务",
        "把客户转人工跟进", "设置客户不再联系",
    )),
)


def _intent_text(entry: IntentEntry) -> str:
    return " ".join((entry.name, entry.description, *entry.examples))


def _tokenize(text: str) -> list[str]:
    import jieba

    return [
        token.strip()
        for token in jieba.cut_for_search(text)
        if len(token.strip()) > 1 or token.strip().isdigit()
    ]


@lru_cache(maxsize=1)
def _bm25_index() -> tuple[Any, tuple[IntentEntry, ...]]:
    from rank_bm25 import BM25Okapi

    entries = tuple(INTENTS)
    return BM25Okapi([_tokenize(_intent_text(entry)) for entry in entries]), entries


@lru_cache(maxsize=1)
def _intent_vector_store():
    from langchain_chroma import Chroma
    from langchain_core.documents import Document

    # Reuse the configured embedding provider, but keep business intents in a
    # dedicated collection so hair-care documents cannot affect tool routing.
    from backend.rag.vector_store import _get_embeddings

    persist_dir = os.path.join(settings.CHROMA_PERSIST_DIR, "staff_intents")
    store = Chroma(
        collection_name="staff_workbench_intents",
        embedding_function=_get_embeddings(),
        persist_directory=persist_dir,
    )
    if store._collection.count() == 0:
        store.add_documents([
            Document(page_content=_intent_text(entry), metadata={"intent": entry.name})
            for entry in INTENTS
        ])
    return store


def _vector_match(message: str) -> dict[str, Any] | None:
    if not settings.STAFF_INTENT_USE_CHROMA:
        return None
    try:
        docs = _intent_vector_store().similarity_search_with_relevance_scores(message, k=1)
    except Exception as exc:
        logger.warning(f"Staff intent vector search unavailable, using BM25: {exc}")
        return None
    if not docs:
        return None
    doc, score = docs[0]
    if score < 0.35:
        return None
    return {"intent": doc.metadata.get("intent", "unknown"), "score": round(float(score), 4), "method": "vector"}


def classify_staff_intent(message: str) -> dict[str, Any]:
    """Return the closest workbench intent without granting any capability."""
    text = message.strip()
    if not text:
        return {"intent": "unknown", "score": 0.0, "method": "none"}

    vector_match = _vector_match(text)
    if vector_match:
        return vector_match

    index, entries = _bm25_index()
    scores = index.get_scores(_tokenize(text))
    if len(scores) == 0:
        return {"intent": "unknown", "score": 0.0, "method": "bm25"}
    best_index = max(range(len(scores)), key=lambda item: scores[item])
    score = float(scores[best_index])
    if score <= 0:
        return {"intent": "unknown", "score": 0.0, "method": "bm25"}
    return {"intent": entries[best_index].name, "score": round(score, 4), "method": "bm25"}
