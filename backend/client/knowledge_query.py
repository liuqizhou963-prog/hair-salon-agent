"""知识库查询（RAG）- 护理知识 + 发型师信息 + 可用时间槽。

检索走统一入口 backend.rag.retriever（Chroma → BM25），
关键词子串匹配只作为最后兜底，且同样基于主知识库
backend.rag.knowledge_base，不再维护第二套硬编码知识。
"""

from typing import Any, Dict, List

from loguru import logger

from backend.database.connection import SessionLocal
from backend.database.service import StylistService, TimeSlotService
from backend.rag.knowledge_base import KNOWLEDGE_ENTRIES
from backend.rag.retriever import retrieve


class RAGRetriever:
    """RAG 知识库检索（美发护理专业知识）。"""

    def search(self, query: str, k: int = 3) -> List[Dict[str, str]]:
        """检索护理知识。

        优先走语义检索（Chroma / BM25），召回为空时退回关键词子串兜底。
        """
        logger.info(f"RAG 检索: {query}")

        semantic_results = retrieve(query, k=k)
        if semantic_results:
            return [
                {
                    "title": item["title"],
                    "content": item["content"],
                    "category": item.get("category", ""),
                }
                for item in semantic_results
            ]

        return self._keyword_fallback(query, k=k)

    def _keyword_fallback(self, query: str, k: int = 3) -> List[Dict[str, str]]:
        """最后兜底：在主知识库上做关键词/分类打分。"""
        query_lower = query.lower()
        scored = []

        for entry in KNOWLEDGE_ENTRIES:
            title = entry["title"]
            content = entry["content"]
            category = entry["category"]
            keywords = entry.get("keywords", "")

            score = 0
            if query_lower in title.lower():
                score += 10
            if query_lower in content.lower():
                score += 5
            # BM25/向量不可用时，仍然利用条目维护的同义词和业务术语。
            for keyword in keywords.lower().split():
                if keyword and keyword in query_lower:
                    score += 2
            # 分类关键词命中
            if category and category[:2] in query:
                score += 3

            if score > 0:
                scored.append(({
                    "title": title,
                    "content": content,
                    "category": category,
                }, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        retrieved = [item for item, _ in scored[:k]]
        logger.info(f"关键词兜底检索到 {len(retrieved)} 条结果")
        return retrieved

    def search_stylists_and_availability(self, service_type: str) -> Dict[str, Any]:
        """继续查询：知识库 + 发型师 + 可用时间槽。

        这是整个系统的一个核心接口：
        1. RAG 查找相关知识
        2. 从 PostgreSQL 查找擅长该服务的发型师
        3. 从 PostgreSQL 查找发型师的可用时间槽
        """
        logger.info(f"继续查询: {service_type}")

        db = SessionLocal()
        try:
            knowledge = self.search(f"{service_type}护理", k=3)

            stylists = StylistService.search_stylists_by_specialty(db, service_type)

            stylists_with_slots = []
            for stylist in stylists:
                slots = TimeSlotService.get_available_slots(db, str(stylist.id), days_ahead=7)
                stylists_with_slots.append({
                    "stylist_id": str(stylist.id),
                    "name": stylist.user.name,
                    "specialty": stylist.specialty,
                    "experience_years": stylist.experience_years,
                    "rating": stylist.rating,
                    "available_slots": slots,
                })

            logger.info(
                f"查询完成: {len(knowledge)} 条知识, {len(stylists_with_slots)} 个发型师"
            )

            return {
                "service_type": service_type,
                "knowledge": knowledge,
                "stylists": stylists_with_slots,
                "total_stylists": len(stylists_with_slots),
            }
        finally:
            db.close()


# 全局 RAG 检索实例
rag_retriever = RAGRetriever()
