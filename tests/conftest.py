import sys
import os
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试必须与开发演示库隔离；该变量要在导入 backend 模块前设置。
os.environ["DATABASE_URL"] = "sqlite://"

from backend.database.connection import drop_all_tables, init_db
from backend.database.init_db import seed_sample_data


@pytest.fixture(autouse=True)
def reset_test_database():
    """每个测试使用干净的共享内存数据库，避免测试之间互相污染。"""
    drop_all_tables()
    init_db()
    seed_sample_data(days_ahead=7)
    yield
