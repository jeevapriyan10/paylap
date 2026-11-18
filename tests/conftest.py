import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import Principal, get_current_principal, require_principal
from app.config import settings
from app.db import get_db, set_tenant_org
from app.ids import generate_id
from app.main import app
from app.models import ApiKey, Membership, Organization, User
from app.services.auth import generate_api_key, hash_password

TEST_PG_URL = "postgresql+psycopg://paylap_owner:paylap_owner_pass@localhost:5432/paylap_test"
pg_test_engine = create_engine(TEST_PG_URL, pool_pre_ping=True)
PgTestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pg_test_engine)


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
def anyio_backend():
    return "asyncio"


@pytest.fixture
def db_session():
    """Create a fresh PostgreSQL test session connected as owner to paylap_test."""
    session = PgTestingSessionLocal()
    set_tenant_org(session, "org_default_test")
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_org(db_session):
    """Fixture providing a verified test organization and developer API key."""
    org_id = generate_id("org")
    user_id = generate_id("usr")

    org = Organization(
        id=org_id,
        name="Global Test Org",
        slug=f"slug_{org_id}",
        live_enabled=False,
        arbiter_enabled=True,
    )
    db_session.add(org)

    user = User(
        id=user_id,
        email=f"dev_{org_id}@test.com",
        password_hash=hash_password("ValidPassword123!"),
    )
    db_session.add(user)
    db_session.flush()

    membership = Membership(
        id=generate_id("mem"),
        user_id=user_id,
        org_id=org_id,
        role="developer",
    )
    db_session.add(membership)

    full_key, lookup_id, secret_hash, prefix, last4 = generate_api_key(env_class="test")
    api_key_record = ApiKey(
        id=generate_id("key"),
        org_id=org_id,
        prefix=prefix,
        lookup_id=lookup_id,
        secret_hash=secret_hash,
        last4=last4,
        environment_class="test",
        scopes=[
            "contracts:read",
            "contracts:write",
            "workers:read",
            "receipts:read",
            "policy:read",
            "webhooks:manage",
            "playground:run",
        ],
        created_by=user_id,
    )
    db_session.add(api_key_record)
    db_session.commit()

    set_tenant_org(db_session, org_id)

    return {
        "org_id": org_id,
        "user_id": user_id,
        "api_key": full_key,
        "headers": {"Authorization": f"Bearer {full_key}"},
    }


@pytest.fixture
def client(db_session, auth_org):
    def override_get_db():
        session = PgTestingSessionLocal()
        set_tenant_org(session, auth_org["org_id"])
        try:
            yield session
        finally:
            session.close()

    def override_require_principal():
        return Principal(
            user_id=auth_org["user_id"],
            org_id=auth_org["org_id"],
            role="developer",
            api_key_id="test_key",
            scopes=[
                "contracts:read",
                "contracts:write",
                "workers:read",
                "receipts:read",
                "policy:read",
                "webhooks:manage",
                "playground:run",
            ],
            env_class="test",
            is_api_key=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_principal] = override_require_principal
    app.dependency_overrides[get_current_principal] = override_require_principal

    with TestClient(app) as test_client:
        test_client.headers.update(auth_org["headers"])
        yield test_client
    app.dependency_overrides.clear()
