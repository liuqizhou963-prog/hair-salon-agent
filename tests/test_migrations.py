import os
import subprocess
import sys
from pathlib import Path


def test_fresh_sqlite_database_can_upgrade_to_head(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
