import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import get_db
from app.main import app
from app.models import ApiKey, Base, LoginAttempt, Membership, Organization, Session as UserSession, User
from app.routers.auth import Principal
from app.services.auth import (
    ROLE_PERMISSIONS,
    has_permission,
    hash_password,
    validate_password_strength,
)

# Test PostgreSQL engine
TEST_PG_URL = "postgresql+psycopg://paylap_owner:paylap_owner_pass@localhost:5432/paylap_test"
test_engine = create_engine(TEST_PG_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_password_strength_validation():
    # Less than 12 characters
    assert validate_password_strength("short123") is not None
    # Common password
    assert validate_password_strength("password1234") is not None
    # Valid strong password
    assert validate_password_strength("CorrectHorseBatteryStaple2026!") is None


def test_signup_closed_mode_requires_invite_code(client, monkeypatch):
    monkeypatch.setattr(settings, "PAYLAP_SIGNUP_MODE", "closed")
    monkeypatch.setattr(settings, "PAYLAP_SIGNUP_CODE", "SECRET_INVITE_123")

    # Attempt without invite code -> 403
    res = client.post("/v1/auth/signup", json={
        "email": "test_invite@example.com",
        "password": "SecurePassword1234!",
    })
    assert res.status_code == 403
    assert "Valid invite code required" in res.text

    # Attempt with valid invite code -> 201
    res2 = client.post("/v1/auth/signup", json={
        "email": "test_invite@example.com",
        "password": "SecurePassword1234!",
        "signup_code": "SECRET_INVITE_123",
    })
    assert res2.status_code == 201
    assert "paylap_session" in res2.cookies
    assert "paylap_csrf" in res2.cookies


def test_login_throttling_and_anti_enumeration(client, monkeypatch):
    monkeypatch.setattr(settings, "PAYLAP_SIGNUP_MODE", "open")
    email = f"throttle_{int(time.time())}@example.com"
    pwd = "ValidPassword1234!"

    # Signup user
    res = client.post("/v1/auth/signup", json={"email": email, "password": pwd})
    assert res.status_code == 201

    # 4 failed attempts with wrong password
    for _ in range(4):
        res_fail = client.post("/v1/auth/login", json={"email": email, "password": "WrongPassword123!"})
        assert res_fail.status_code == 401
        assert res_fail.json()["detail"] == "Invalid email or password"

    # Attempt for non-existent email -> identical status and detail
    res_non_existent = client.post("/v1/auth/login", json={"email": "non_existent@example.com", "password": "WrongPassword123!"})
    assert res_non_existent.status_code == 401
    assert res_non_existent.json()["detail"] == "Invalid email or password"

    # 5th failed attempt -> still 401
    res_5th = client.post("/v1/auth/login", json={"email": email, "password": "WrongPassword123!"})
    assert res_5th.status_code == 401

    # 6th attempt -> Throttled! HTTP 429 Too Many Requests with Retry-After header
    res_throttled = client.post("/v1/auth/login", json={"email": email, "password": "WrongPassword123!"})
    assert res_throttled.status_code == 429
    assert "Retry-After" in res_throttled.headers
    assert res_throttled.headers["Retry-After"] == "900"


def test_csrf_double_submit_protection(client, monkeypatch):
    monkeypatch.setattr(settings, "PAYLAP_SIGNUP_MODE", "open")
    email = f"csrf_{int(time.time())}@example.com"
    res = client.post("/v1/auth/signup", json={"email": email, "password": "SecurePassword1234!"})
    assert res.status_code == 201
    csrf_token = res.json()["csrf_token"]
    session_cookie = res.cookies["paylap_session"]

    # 1. Unsafe POST with cookie but NO X-CSRF-Token header -> 403 Forbidden
    res_no_csrf = client.post(
        "/v1/auth/keys",
        json={"scopes": ["contracts:read"], "environment_class": "test"},
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
    )
    assert res_no_csrf.status_code == 403
    assert "CSRF" in res_no_csrf.text

    # 2. Unsafe POST with mismatched X-CSRF-Token header -> 403 Forbidden
    res_bad_csrf = client.post(
        "/v1/auth/keys",
        json={"scopes": ["contracts:read"], "environment_class": "test"},
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
        headers={"X-CSRF-Token": "wrong_csrf_token"},
    )
    assert res_bad_csrf.status_code == 403

    # 3. Unsafe POST with matching X-CSRF-Token header -> 201 Created
    res_valid_csrf = client.post(
        "/v1/auth/keys",
        json={"scopes": ["contracts:read"], "environment_class": "test"},
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert res_valid_csrf.status_code == 201
    created_key = res_valid_csrf.json()["key"]

    # 4. Bearer Authentication -> CSRF Exempt
    res_bearer = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {created_key}"},
    )
    assert res_bearer.status_code == 200
    assert res_bearer.json()["type"] == "api_key"


def test_rbac_permission_matrix():
    # Viewer
    assert has_permission("viewer", "contracts:read") is True
    assert has_permission("viewer", "contracts:write") is False
    assert has_permission("viewer", "credentials:manage") is False
    assert has_permission("viewer", "live:enable") is False

    # Developer
    assert has_permission("developer", "contracts:read") is True
    assert has_permission("developer", "contracts:write") is True
    assert has_permission("developer", "playground:run") is True
    assert has_permission("developer", "api_keys:own") is True
    assert has_permission("developer", "credentials:manage") is False
    assert has_permission("developer", "live:enable") is False

    # Admin
    assert has_permission("admin", "contracts:write") is True
    assert has_permission("admin", "credentials:manage") is True
    assert has_permission("admin", "webhooks:manage") is True
    assert has_permission("admin", "api_keys:manage") is True
    assert has_permission("admin", "live:enable") is False

    # Owner
    assert has_permission("owner", "live:enable") is True
    assert has_permission("owner", "org:manage") is True
    assert has_permission("owner", "credentials:manage") is True


def test_api_key_scopes_and_environment_class(client, monkeypatch):
    monkeypatch.setattr(settings, "PAYLAP_SIGNUP_MODE", "open")
    email = f"keyenv_{int(time.time())}@example.com"
    res = client.post("/v1/auth/signup", json={"email": email, "password": "SecurePassword1234!"})
    assert res.status_code == 201
    csrf_token = res.json()["csrf_token"]
    session_cookie = res.cookies["paylap_session"]

    # 1. Attempt to create live key when org.live_enabled is False -> 403 Forbidden
    res_live_blocked = client.post(
        "/v1/auth/keys",
        json={"scopes": ["contracts:read"], "environment_class": "live"},
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert res_live_blocked.status_code == 403
    assert "live_enabled" in res_live_blocked.text

    # 2. Create test key with specific scopes
    res_key = client.post(
        "/v1/auth/keys",
        json={"scopes": ["contracts:read", "receipts:read"], "environment_class": "test"},
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert res_key.status_code == 201
    data = res_key.json()
    full_key = data["key"]
    key_id = data["id"]
    assert full_key.startswith("pl_test_")

    # 3. Test Principal scope enforcement
    principal = Principal(
        user_id=None,
        org_id="org_test",
        api_key_id=key_id,
        scopes=["contracts:read", "receipts:read"],
        env_class="test",
        is_api_key=True,
    )
    assert principal.has_scope("contracts:read") is True
    assert principal.has_scope("contracts:write") is False
    with pytest.raises(Exception) as exc:
        principal.require_scope("contracts:write")
    assert "Missing required permission" in str(exc.value)

    # 4. Revoke key
    res_revoke = client.delete(
        f"/v1/auth/keys/{key_id}",
        cookies={"paylap_session": session_cookie, "paylap_csrf": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert res_revoke.status_code == 200

    # 5. Revoked key is rejected
    res_rejected = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {full_key}"},
    )
    assert res_rejected.status_code == 401
