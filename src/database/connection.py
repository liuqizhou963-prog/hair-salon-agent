"""数据库连接配置"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from loguru import logger

# 数据库URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://salon_user:salon_password@localhost:5432/hair_salon"
)

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
    pool_pre_ping=True
)

# 创建 Session端口
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 基类
Base = declarative_base()

def get_db():
    """SQL会话收赇"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """创建所有数据库表"""
    logger.info("🔨 创建数据库表...")
    Base.metadata.create_all(bind=engine)
    logger.info("✅ 数据库初始化完成")

def drop_all_tables():
    """删除所有表（为了测试）"""
    logger.warning("⚠️ 删除所有数据库表...")
    Base.metadata.drop_all(bind=engine)
    logger.info("✅ 数据库表已删除")
