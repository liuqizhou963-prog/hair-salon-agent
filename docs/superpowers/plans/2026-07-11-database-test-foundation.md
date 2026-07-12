# Database and Test Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make development and automated tests use explicitly separated databases, and add a versioned Alembic migration baseline without changing current business behavior.

**Architecture:** Production keeps using `DATABASE_URL` and can point to PostgreSQL. Tests set `DATABASE_URL=sqlite://` before importing the application, use a shared in-memory SQLite connection, and rebuild tables plus seed data for each test. Alembic reads the same SQLAlchemy metadata and records schema changes independently from runtime table creation.

**Tech Stack:** SQLAlchemy 2, SQLite, PostgreSQL, Alembic, pytest, FastAPI TestClient.

## Global Constraints

- Do not place real credentials in tracked files.
- Do not change appointment, agent, frontend, or authentication behavior in this step.
- Every completed step must be explained in beginner-friendly language in `开发总结.md`.
- Existing user changes in the dirty worktree must be preserved.

---

### Task 1: Prove tests must not use the development SQLite file

**Files:**
- Create: `tests/test_database_isolation.py`

- [x] **Step 1: Write the failing test**

```python
from pathlib import Path

from backend.database.connection import engine


def test_tests_use_a_separate_sqlite_database():
    project_database = Path(__file__).resolve().parents[1] / "hair_salon.db"
    assert engine.url.get_backend_name() == "sqlite"
    assert engine.url.database != str(project_database)
```

- [x] **Step 2: Run the test and verify it fails**

Run: `pytest tests/test_database_isolation.py::test_tests_use_a_separate_sqlite_database -q`

Expected: FAIL because the current engine points at the project-root `hair_salon.db`.

### Task 2: Isolate pytest with shared in-memory SQLite

**Files:**
- Modify: `tests/conftest.py`
- Modify: `backend/database/connection.py`
- Test: `tests/test_database_isolation.py`

- [x] **Step 1: Set `DATABASE_URL=sqlite://` before application imports.**
- [x] **Step 2: Configure SQLAlchemy `StaticPool` for shared in-memory SQLite.**
- [x] **Step 3: Add an autouse fixture that drops/recreates tables and seeds sample data before each test.**
- [x] **Step 4: Run the isolation test and the full test suite.**

Expected: the isolation test passes and all existing tests remain green.

### Task 3: Add Alembic baseline

**Files:**
- Modify: `requirements.txt`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_initial_schema.py`

- [x] **Step 1: Add the pinned Alembic dependency.**
- [x] **Step 2: Configure Alembic to read `DATABASE_URL` and the existing SQLAlchemy metadata.**
- [x] **Step 3: Create an initial revision matching the current models.**
- [x] **Step 4: Verify the migration can upgrade a fresh SQLite database to the current schema.**

### Task 4: Record and verify the completed step

**Files:**
- Modify: `开发总结.md`

- [x] **Step 1: Record the exact changed files, why they changed, test commands, results, interview explanation, and remaining risks.**
- [x] **Step 2: Run `pytest -q` and the migration verification command.**
