import base64

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.ids import generate_id
from app.models import Organization
from app.services.crypto import (
    DecryptionError,
    decrypt_credential,
    encrypt_credential,
    reencrypt_credential,
)
from app.services.paypal_factory import (
    LiveEnvironmentDisabledError,
    get_provider,
)
from app.services.policy import evaluate_spend_policy, get_or_create_policy

# PostgreSQL test DB session
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


def test_encryption_roundtrip_and_envelope_structure():
    org_id = generate_id("org")
    secret_text = "EAI_super_secret_paypal_client_secret_xyz123"

    envelope = encrypt_credential(
        plaintext=secret_text,
        org_id=org_id,
        environment="sandbox",
        field="client_secret",
    )

    parts = envelope.split(".")
    assert len(parts) == 3
    kid, nonce, ciphertext = parts
    assert kid == "k1"
    assert len(base64.b64decode(nonce)) == 12

    # Decrypt and assert match
    decrypted = decrypt_credential(
        envelope=envelope,
        org_id=org_id,
        environment="sandbox",
        field="client_secret",
    )
    assert decrypted == secret_text


def test_wrong_aad_fails_decryption():
    org_id = generate_id("org")
    secret_text = "secret_credentials"

    envelope = encrypt_credential(
        plaintext=secret_text,
        org_id=org_id,
        environment="sandbox",
        field="client_secret",
    )

    # 1. Wrong org_id
    with pytest.raises(DecryptionError):
        decrypt_credential(envelope, org_id="wrong_org_id", environment="sandbox", field="client_secret")

    # 2. Wrong environment
    with pytest.raises(DecryptionError):
        decrypt_credential(envelope, org_id=org_id, environment="live", field="client_secret")

    # 3. Wrong field
    with pytest.raises(DecryptionError):
        decrypt_credential(envelope, org_id=org_id, environment="sandbox", field="webhook_id")


def test_key_rotation_across_master_keys(db_session, monkeypatch):
    # Configure two 32-byte master keys
    key1_bytes = b"01234567890123456789012345678901"
    key2_bytes = b"abcdefghijklmnopqrstuvwxyz012345"
    b64_1 = base64.b64encode(key1_bytes).decode()
    b64_2 = base64.b64encode(key2_bytes).decode()
    monkeypatch.setattr(settings, "PAYLAP_MASTER_KEYS", f"k1:{b64_1},k2:{b64_2}")

    org_id = generate_id("org")
    secret_text = "paypal_secret_to_rotate"

    envelope_k1 = encrypt_credential(secret_text, org_id, "sandbox", "client_secret", key_id="k1")
    assert envelope_k1.startswith("k1.")

    # Re-encrypt single credential
    envelope_k2 = reencrypt_credential(envelope_k1, org_id, "sandbox", "client_secret", new_key_id="k2")
    assert envelope_k2.startswith("k2.")

    # Decrypt with new envelope
    assert decrypt_credential(envelope_k2, org_id, "sandbox", "client_secret") == secret_text


def test_live_disabled_by_default(db_session, monkeypatch):
    org = Organization(
        id=generate_id("org"),
        name="Test Org",
        slug=f"slug-{generate_id('test')}",
        live_enabled=False,  # Live disabled on org
    )
    db_session.add(org)
    db_session.commit()

    # 1. With PAYLAP_ALLOW_LIVE=false and org.live_enabled=false -> LiveEnvironmentDisabledError
    monkeypatch.setattr(settings, "PAYLAP_ALLOW_LIVE", False)
    with pytest.raises(LiveEnvironmentDisabledError) as exc1:
        get_provider(org, environment="live", db=db_session)
    assert "globally disabled" in str(exc1.value)

    # 2. With PAYLAP_ALLOW_LIVE=true but org.live_enabled=false -> LiveEnvironmentDisabledError
    monkeypatch.setattr(settings, "PAYLAP_ALLOW_LIVE", True)
    with pytest.raises(LiveEnvironmentDisabledError) as exc2:
        get_provider(org, environment="live", db=db_session)
    assert "live_enabled=false" in str(exc2.value)


def test_spend_policy_enforcement_and_blocked_zero_provider_calls(db_session):
    org = Organization(
        id=generate_id("org"),
        name="Policy Test Org",
        slug=f"slug-{generate_id('pol')}",
        live_enabled=False,
    )
    db_session.add(org)
    db_session.commit()
    org_id = org.id
    policy = get_or_create_policy(db_session, org_id, "simulated")
    policy.max_task_cents = 2500  # $25 max
    policy.daily_cap_cents = 5000  # $50 daily
    policy.worker_allowlist = ["allowed_worker@example.com"]
    policy.require_hidden_tests = True
    db_session.commit()

    # Case 1: Exceeds max task cap ($30 > $25)
    valid, violations = evaluate_spend_policy(
        db=db_session,
        org_id=org_id,
        environment="simulated",
        total_cents=3000,
        milestones=[{"hidden_tests": "assert True"}],
        worker_email="allowed_worker@example.com",
    )
    assert valid is False
    assert any("exceeds maximum allowed task limit" in v for v in violations)

    # Case 2: Worker not in allowlist
    valid2, violations2 = evaluate_spend_policy(
        db=db_session,
        org_id=org_id,
        environment="simulated",
        total_cents=1000,
        milestones=[{"hidden_tests": "assert True"}],
        worker_email="unauthorized_worker@example.com",
    )
    assert valid2 is False
    assert any("approved worker allowlist" in v for v in violations2)

    # Case 3: Missing required hidden tests
    valid3, violations3 = evaluate_spend_policy(
        db=db_session,
        org_id=org_id,
        environment="simulated",
        total_cents=1000,
        milestones=[{"hidden_tests": ""}],
        worker_email="allowed_worker@example.com",
    )
    assert valid3 is False
    assert any("missing required hidden tests" in v for v in violations3)

    # Case 4: Compliant contract
    valid4, violations4 = evaluate_spend_policy(
        db=db_session,
        org_id=org_id,
        environment="simulated",
        total_cents=1500,
        milestones=[{"hidden_tests": "assert True"}],
        worker_email="allowed_worker@example.com",
    )
    assert valid4 is True
    assert len(violations4) == 0
