"""数据库连接配置"""

import os
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.types import TypeDecorator, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.pool import StaticPool
from loguru import logger

DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL and DATABASE_URL.startswith("sqlite://"):
    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        engine = create_engine(
            "sqlite://",
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            DATABASE_URL,
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
            connect_args={"check_same_thread": False},
        )
elif DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
        pool_pre_ping=True,
    )
else:
    DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    SQLITE_PATH = os.path.join(DB_DIR, "hair_salon.db")
    engine = create_engine(
        f"sqlite:///{SQLITE_PATH}",
        echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
        connect_args={"check_same_thread": False},
    )
    logger.info(f"Using SQLite at {SQLITE_PATH}")


class UniversalUUID(TypeDecorator):
    """Cross-database UUID type."""
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        else:
            return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name != "postgresql" and isinstance(value, str):
            return uuid.UUID(value)
        return value


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")

def drop_all_tables():
    logger.warning("Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("Database tables dropped")
