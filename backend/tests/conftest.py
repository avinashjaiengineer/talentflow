import os
import tempfile

# Configure before the app is imported: offline LLM, and by default a throwaway SQLite
# database with hash embeddings. Set TEST_DATABASE_URL to run the suite against Postgres.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = os.environ.get("TEST_EMBEDDING_PROVIDER", "hash")
os.environ["EMBEDDED_WORKER"] = "false"  # tests drive the worker explicitly
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "admin-password-123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import login_limiter  # noqa: E402
from app.worker import drain  # noqa: E402

ADMIN = {"email": "admin@example.com", "password": "admin-password-123"}


def _reset_db() -> None:
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        else:
            Base.metadata.drop_all(conn)
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture()
def anon():
    """A client with a fresh, migrated database and nobody signed in."""
    _reset_db()
    login_limiter._failures.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(anon):
    """Signed in as the bootstrap admin."""
    assert anon.post("/api/auth/login", json=ADMIN).status_code == 200
    return anon


@pytest.fixture()
def work():
    """Run the background worker until the queue is empty."""
    return drain
