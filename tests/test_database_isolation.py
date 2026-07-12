from pathlib import Path

from backend.database.connection import engine


def test_tests_use_a_separate_sqlite_database():
    project_database = Path(__file__).resolve().parents[1] / "hair_salon.db"

    assert engine.url.get_backend_name() == "sqlite"
    configured_database = engine.url.database
    assert configured_database in {None, "", ":memory:"}
    if configured_database:
        assert Path(configured_database).resolve() != project_database.resolve()
