"""本地 BM25 语义检索 — 无需 API key 的默认检索路径。

Chroma 需要 embedding（API key 或 Ollama）。当两者都不可用时，我们仍然希望
比"子串匹配"更聪明的检索：用 jieba 中文分词 + BM25 排序，对同义/近义表达
也能召回。这样 demo 不配 key 也能展示真·检索效果。
"""

from typing import Dict, List, Optional

from loguru import logger

from backend.rag.knowledge_base import load_knowledge_documents


class _BM25KnowledgeIndex:
    """在内存里为知识库文档片段构建 BM25 索引（惰性构建、单例复用）。"""

    def __init__(self):
        self._bm25 = None
        self._docs: List[Dict] = []
        self._ready = False

    @staticmethod
    def _tokenize(text: str, jieba) -> List[str]:
        """过滤中文单字噪声，避免常见的“发”“染”等词压过主题词。"""
        return [
            token.strip()
            for token in jieba.cut_for_search(text)
            if len(token.strip()) > 1 or token.strip().isdigit()
        ]

    def _ensure_built(self) -> None:
        if self._ready:
            return

        import jieba
        from rank_bm25 import BM25Okapi

        raw_docs = load_knowledge_documents()
        corpus_tokens = []
        for item in raw_docs:
            meta = item["metadata"]
            # 标题和关键词代表文档主题，适度重复可让明确术语优先于泛化正文命中。
            text = " ".join([
                meta.get("title", ""),
                meta.get("title", ""),
                meta.get("category", ""),
                meta.get("keywords", ""),
                meta.get("keywords", ""),
                item["content"],
            ])
            corpus_tokens.append(self._tokenize(text, jieba))
            self._docs.append({
                "title": meta.get("title", "护理知识"),
                "category": meta.get("category", ""),
                "content": item["content"],
                "keywords": meta.get("keywords", ""),
                "metadata": meta,
            })

        self._bm25 = BM25Okapi(corpus_tokens)
        self._ready = True
        logger.info(f"BM25 knowledge index built with {len(self._docs)} chunks")

    def search(self, query: str, k: int = 3, min_score: float = 0.5) -> List[Dict]:
        try:
            self._ensure_built()
        except Exception as exc:  # jieba/rank-bm25 未安装等
            logger.warning(f"BM25 index unavailable, will fall back to keywords: {exc}")
            return []

        import jieba

        query_tokens = self._tokenize(query, jieba)
        scores = self._bm25.get_scores(query_tokens)

        ranked = sorted(
            enumerate(scores), key=lambda pair: pair[1], reverse=True
        )

        results = []
        for idx, score in ranked[:k]:
            if score < min_score:
                continue
            doc = dict(self._docs[idx])
            doc["score"] = round(float(score), 4)
            results.append(doc)

        logger.info(f"BM25 retrieved {len(results)} docs for query: {query[:40]}")
        return results


_index: Optional[_BM25KnowledgeIndex] = None


def bm25_search(query: str, k: int = 3, min_score: float = 0.5) -> List[Dict]:
    """对外的 BM25 检索入口，复用单例索引。"""
    global _index
    if _index is None:
        _index = _BM25KnowledgeIndex()
    return _index.search(query, k=k, min_score=min_score)
