"""应用配置"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "Hair Salon AI Agent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
    AUTH_SECRET_KEY: str = os.getenv("AUTH_SECRET_KEY", "dev-only-change-this-secret")
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    DEMO_STAFF_PASSWORD: str = os.getenv("DEMO_STAFF_PASSWORD", "")
    DEMO_ADMIN_PHONE: str = os.getenv("DEMO_ADMIN_PHONE", "")
    DEMO_ADMIN_NAME: str = os.getenv("DEMO_ADMIN_NAME", "演示管理员")
    DEMO_ADMIN_PASSWORD: str = os.getenv("DEMO_ADMIN_PASSWORD", "")

    # 数据库
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # LLM
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    # ChromaDB
    RAG_USE_CHROMA: bool = os.getenv("RAG_USE_CHROMA", "false").lower() == "true"
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")

    # Redis (预留)
    REDIS_URL: str = os.getenv("REDIS_URL", "")


settings = Settings()
