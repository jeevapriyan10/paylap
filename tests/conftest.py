import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
from app.db import Base
from app.models import Contract, Milestone, Event


@pytest.fixture(autouse=True)
def set_default_test_settings():
    orig_arbiter = settings.PAYLAP_ARBITER_MODE
    orig_worker_source = settings.ARENA_WORKER_SOURCE
    settings.PAYLAP_ARBITER_MODE = "mock"
    settings.ARENA_WORKER_SOURCE = "canned"
    yield
    settings.PAYLAP_ARBITER_MODE = orig_arbiter
    settings.ARENA_WORKER_SOURCE = orig_worker_source


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite session for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
