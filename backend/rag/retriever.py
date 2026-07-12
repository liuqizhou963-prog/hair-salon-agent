"""统一检索入口：Chroma 向量检索优先，BM25 本地语义检索兜底。

检索优先级：
1. Chroma 向量检索（配置了 embedding：API key 或 Ollama 时）
2. BM25 本地语义检索（无需任何 key，纯本地 jieba 分词）

两者都基于同一份知识库（backend/rag/knowledge_base.py）。关键词子串匹配
只作为最后的兜底，留在 knowledge_query.py 里。
"""

from typing import Dict, List

from loguru import logger

from backend.config import settings
from backend.rag.bm25_index import bm25_search
from backend.rag.vector_store import get_vector_store


def _chroma_search(query: str, k: int, threshold: float) -> List[Dict]:
    """Chroma 向量检索。未启用或不可用时返回空列表。"""
    if not settings.RAG_USE_CHROMA:
        return []

    try:
        store = get_vector_store()
        docs_with_scores = store.similarity_search_with_relevance_scores(query, k=k)
    except Exception as exc:
        logger.warning(f"Chroma RAG unavailable, falling back to BM25: {exc}")
        return []

    results = []
    for doc, score in docs_with_scores:
        if score < threshold:
            continue
        results.append({
            "title": doc.metadata.get("title", "护理知识"),
            "category": doc.metadata.get("category", ""),
            "content": doc.page_content,
            "metadata": doc.metadata,
            "score": round(score, 4),
        })

    logger.info(f"Chroma RAG retrieved {len(results)}/{k} docs")
    return results


def retrieve(query: str, k: int = 3, threshold: float = 0.3) -> List[Dict]:
    """统一检索：Chroma 优先，BM25 兜底。

    返回空列表时，调用方（knowledge_query.py）会退回到关键词子串匹配，
    保证任何环境下都有结果可展示。
    """
    chroma_results = _chroma_search(query, k=k, threshold=threshold)
    if chroma_results:
        return chroma_results

    return bm25_search(query, k=k)
