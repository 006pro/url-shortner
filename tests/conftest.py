import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import settings
from app.database import Base, SessionLocal
from app.main import app
from app.models import ApiKey
from app.security import generate_api_key, hash_api_key

if not settings.test_database_url:
    raise RuntimeError("TEST_DATABASE_URL must be set to run the test suite")

# Point the app's session factory at the test database instead of the dev one.
# Both routes (via the get_db dependency) and the redirect background task
# (which opens its own SessionLocal()) go through this same sessionmaker, so
# rebinding it here is enough to redirect *all* DB access in tests.
test_engine = create_engine(settings.test_database_url, pool_pre_ping=True)
SessionLocal.configure(bind=test_engine)

TABLES_IN_FK_ORDER = ("clicks", "rate_limit_windows", "links", "api_keys")


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all tables before every test so tests don't leak state into
    each other. Truncation (rather than a shared rolled-back transaction) is
    used because the redirect background task opens its own session/connection,
    which wouldn't see an uncommitted outer transaction anyway."""
    with test_engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in TABLES_IN_FK_ORDER:
            conn.execute(text(f"TRUNCATE TABLE {table}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def api_key() -> str:
    raw_key = generate_api_key()
    db = SessionLocal()
    try:
        db.add(ApiKey(key_hash=hash_api_key(raw_key), label="test"))
        db.commit()
    finally:
        db.close()
    return raw_key


@pytest.fixture
def auth_headers(api_key: str) -> dict:
    return {"X-API-Key": api_key}


@pytest.fixture
def other_api_key() -> str:
    raw_key = generate_api_key()
    db = SessionLocal()
    try:
        db.add(ApiKey(key_hash=hash_api_key(raw_key), label="other"))
        db.commit()
    finally:
        db.close()
    return raw_key
