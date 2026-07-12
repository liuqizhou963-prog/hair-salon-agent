"""Optional ChromaDB vector store for hair-care knowledge."""

import os

from langchain_core.documents import Document
from loguru import logger

from backend.config import settings
from backend.rag.knowledge_base import load_knowledge_documents

COLLECTION_NAME = "hair_salon_knowledge"


def _get_embeddings():
    if settings.EMBEDDING_PROVIDER == "ollama":
        from langchain_community.embeddings import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
        )

    if not settings.LLM_API_KEY:
        raise ValueError("LLM_API_KEY is required when EMBEDDING_PROVIDER=openai")

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
    )


def build_vector_store(persist_dir: str | None = None):
    from langchain_chroma import Chroma

    if persist_dir is None:
        persist_dir = settings.CHROMA_PERSIST_DIR

    raw_docs = load_knowledge_documents()
    documents = [
        Document(page_content=item["content"], metadata=item["metadata"])
        for item in raw_docs
    ]

    logger.info(f"Building Chroma vector store with {len(documents)} documents")
    return Chroma.from_documents(
        documents=documents,
        embedding=_get_embeddings(),
        collection_name=COLLECTION_NAME,
        persist_directory=persist_dir,
    )


def get_vector_store(persist_dir: str | None = None):
    from langchain_chroma import Chroma

    if persist_dir is None:
        persist_dir = settings.CHROMA_PERSIST_DIR

    if os.path.exists(persist_dir) and os.listdir(persist_dir):
        logger.info(f"Loading Chroma vector store from {persist_dir}")
        return Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=_get_embeddings(),
            persist_directory=persist_dir,
        )

    return build_vector_store(persist_dir)
