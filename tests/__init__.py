"""Testes unitarios do CotaSync."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = (
    "postgresql+psycopg://cotasync_test:cotasync_test_password@cotasync_test_postgres:5432/cotasync_pytest"
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def _bootstrap_test_database() -> None:
    if os.environ.get("COTASYNC_TEST_DB_BOOTSTRAPPED") == "1":
        return
    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    subprocess.run(["alembic", "upgrade", "head"], cwd=str(ROOT), env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["python", "scripts/migrate_json_to_postgres.py", "--apply"],
        cwd=str(ROOT),
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    from backend.db import SessionLocal, User
    from backend.services.auth import hash_password

    with SessionLocal.begin() as session:
        session.query(User).delete()
        session.add(
            User(
                id="test-admin",
                username="admin",
                password_hash=hash_password("admin-password"),
                role="admin",
                active=True,
            )
        )
        session.add(
            User(
                id="test-operator",
                username="operator",
                password_hash=hash_password("operator-password"),
                role="operator",
                active=True,
            )
        )
    os.environ["COTASYNC_TEST_DB_BOOTSTRAPPED"] = "1"


_bootstrap_test_database()
