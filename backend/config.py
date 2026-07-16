"""应用配置"""
import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DEFAULT_AUTH_SECRET_KEY = "dev-only-change-this-secret"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    APP_NAME: str = "Hair Salon AI Agent"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = os.getenv("APP_ENV", "development").lower()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
    AUTH_SECRET_KEY: str = os.getenv("AUTH_SECRET_KEY", DEFAULT_AUTH_SECRET_KEY)
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    WECHAT_APP_ID: str = os.getenv("WECHAT_APP_ID", "")
    WECHAT_APP_SECRET: str = os.getenv("WECHAT_APP_SECRET", "")
    DEMO_STAFF_PASSWORD: str = os.getenv("DEMO_STAFF_PASSWORD", "")
    DEMO_ADMIN_PHONE: str = os.getenv("DEMO_ADMIN_PHONE", "")
    DEMO_ADMIN_NAME: str = os.getenv("DEMO_ADMIN_NAME", "演示管理员")
    DEMO_ADMIN_PASSWORD: str = os.getenv("DEMO_ADMIN_PASSWORD", "")
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() == "true"
    SCHEDULER_ENABLED: bool = os.getenv(
        "SCHEDULER_ENABLED",
        "false" if APP_ENV in {"production", "prod"} else "true",
    ).lower() == "true"

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
    STAFF_INTENT_USE_CHROMA: bool = os.getenv(
        "STAFF_INTENT_USE_CHROMA", os.getenv("RAG_USE_CHROMA", "false")
    ).lower() == "true"

    # Redis (预留)
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    CORS_ALLOWED_ORIGINS: list[str] = _split_csv(
        os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
    )

    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

    @property
    def is_production(self) -> bool:
        return self.APP_ENV in {"production", "prod"}


settings = Settings()


def validate_security_settings(config: Settings | None = None) -> None:
    """Block obvious demo settings when starting production."""
    config = config or settings
    if not config.is_production:
        if config.AUTH_SECRET_KEY == DEFAULT_AUTH_SECRET_KEY:
            logger.warning("Development mode is using the demo JWT secret")
        return

    errors: list[str] = []
    if config.DEBUG:
        errors.append("DEBUG must be false")
    if config.AUTH_SECRET_KEY == DEFAULT_AUTH_SECRET_KEY or len(config.AUTH_SECRET_KEY) < 32:
        errors.append("AUTH_SECRET_KEY must be a random string of at least 32 characters")
    if not config.CORS_ALLOWED_ORIGINS or "*" in config.CORS_ALLOWED_ORIGINS:
        errors.append("CORS_ALLOWED_ORIGINS must contain explicit frontend origins")
    if not config.DATABASE_URL or config.DATABASE_URL.startswith("sqlite://"):
        errors.append("DATABASE_URL must point to the production database")
    if not config.RATE_LIMIT_ENABLED:
        errors.append("RATE_LIMIT_ENABLED must be true")
    if config.DEMO_MODE:
        errors.append("DEMO_MODE must be false")

    if errors:
        raise RuntimeError("Production security checks failed: " + "; ".join(errors))
