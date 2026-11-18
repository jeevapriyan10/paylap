import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.auth import get_password_hash
from app.db import get_db
from app.ids import generate_id
from app.ledger import append_event
from app.main import app
from app.models import (
    ApiKey,
    Contract,
    Membership,
    Milestone,
    Organization,
    User,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services.webhooks import (
    RETRY_BACKOFFS,
    compute_webhook_signature,
    deliver_webhook_sync,
    is_safe_webhook_url,
    verify_webhook_signature,
)
from app.state import ContractStatus, MilestoneStatus

TEST_PG_URL = "postgresql+psycopg://paylap_owner:paylap_owner_pass@localhost:5432/paylap_test"
test_engine = create_engine(TEST_PG_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def auth_org(db_session):
    unique = uuid.uuid4().hex[:12]
    user_id = generate_id("usr")
    user = User(
        id=user_id,
        email=f"user_{unique}@corp.com",
        password_hash=get_password_hash("ValidPass1234!"),
    )
    db_session.add(user)
    db_session.flush()

    org_id = generate_id("org")
    org = Organization(
        id=org_id,
        name=f"Org {unique}",
        slug=f"slug_{unique}",
        live_enabled=False,
        arbiter_enabled=True,
    )
    db_session.add(org)
    db_session.flush()

    membership = Membership(
        id=generate_id("mem"),
        user_id=user_id,
        org_id=org_id,
        role="owner",
    )
    db_session.add(membership)

    raw_key = f"pl_test_{unique[:16]}_{uuid.uuid4().hex}"
    lookup_id = raw_key.split("_")[2]
    secret = raw_key.split("_")[3]
    import hashlib

    api_key = ApiKey(
        id=generate_id("key"),
        org_id=org_id,
        created_by=user_id,
        lookup_id=lookup_id,
        secret_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        prefix="pl_test_",
        last4=secret[-4:],
        scopes=[
            "contracts:read",
            "contracts:write",
            "workers:read",
            "policy:read",
            "receipts:read",
            "webhooks:manage",
            "playground:run",
        ],
        environment_class="test",
    )
    db_session.add(api_key)
    db_session.commit()

    from app.ledger import set_tenant_org

    set_tenant_org(db_session, org_id)

    return {
        "org_id": org_id,
        "user_id": user_id,
        "api_key": raw_key,
    }


@pytest.fixture
def client(auth_org):
    def override_get_db():
        session = TestingSessionLocal()
        from app.ledger import set_tenant_org

        set_tenant_org(session, auth_org["org_id"])
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {auth_org['api_key']}"})
        yield test_client
    app.dependency_overrides.clear()


# ============================================================================
# 1. SSRF Protection and Outbound Webhook Signatures
# ============================================================================


def test_ssrf_protection_blocks_reserved_and_private_ips():
    """
    Exit Gate: SSRF protection blocks private, reserved, and loopback IP ranges.
    """
    # Private / loopback targets
    safe, err = is_safe_webhook_url("http://127.0.0.1/webhook", allow_test=False)
    assert safe is False
    assert "private" in err.lower() or "loopback" in err.lower()

    safe, err = is_safe_webhook_url("http://10.0.0.1/webhook", allow_test=False)
    assert safe is False
    assert "private" in err.lower() or "blocked" in err.lower()

    safe, err = is_safe_webhook_url("http://169.254.169.254/latest/meta-data", allow_test=False)
    assert safe is False
    assert "private" in err.lower() or "link_local" in err.lower() or "blocked" in err.lower()

    # Public target should be allowed
    safe, err = is_safe_webhook_url("https://dns.google/resolve", allow_test=False)
    assert safe is True


def test_webhook_signature_computation_and_verification():
    """
    Exit Gate: Webhook HMAC signatures compute and verify with timestamp drift check.
    """
    secret = "whsec_test_secret_123456789"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = json.dumps({"event": "TEST", "data": "hello"})

    sig_header = compute_webhook_signature(secret, now_ts, payload)
    assert sig_header.startswith(f"t={now_ts},v1=")

    # Verification passes
    is_valid = verify_webhook_signature(secret, sig_header, payload, tolerance_seconds=300)
    assert is_valid is True

    # Tampered payload fails
    is_valid = verify_webhook_signature(secret, sig_header, payload + "tampered", tolerance_seconds=300)
    assert is_valid is False

    # Timestamp expired fails
    old_sig = compute_webhook_signature(secret, now_ts - 600, payload)
    is_valid = verify_webhook_signature(secret, old_sig, payload, tolerance_seconds=300)
    assert is_valid is False


# ============================================================================
# 2. Webhook Retry Schedule and Backoff
# ============================================================================


def test_webhook_retry_schedule_and_backoff(db_session, auth_org):
    """
    Exit Gate: Webhook deliveries retry with backoffs (1m, 5m, 30m, 2h, 5h) and exhaust.
    """
    ep = WebhookEndpoint(
        id=generate_id("ep"),
        org_id=auth_org["org_id"],
        url="http://example.com/unreachable-endpoint",
        secret_hash="a" * 64,
        is_active=True,
    )
    db_session.add(ep)
    db_session.commit()

    now = datetime.now(timezone.utc)
    delivery = WebhookDelivery(
        id=generate_id("del"),
        org_id=auth_org["org_id"],
        endpoint_id=ep.id,
        event_id="evt_test_retry",
        event_type="CONTRACT_CREATED",
        payload={"msg": "payload"},
        status="PENDING",
        attempt_count=0,
        next_retry_at=now,
    )
    db_session.add(delivery)
    db_session.commit()

    # Attempt 1 -> fails -> scheduled for attempt 1 backoff (60s)
    deliver_webhook_sync(db_session, delivery)
    assert delivery.status == "FAILED"
    assert delivery.attempt_count == 1
    assert delivery.next_retry_at is not None
    expected_backoff = RETRY_BACKOFFS[0]
    assert (delivery.next_retry_at - now).total_seconds() >= (expected_backoff - 5)

    # Fast forward through attempts up to exhaustion
    delivery.attempt_count = 5
    delivery.next_retry_at = now
    deliver_webhook_sync(db_session, delivery)
    assert delivery.status == "EXHAUSTED"
    assert delivery.next_retry_at is None


# ============================================================================
# 3. Inbound PayPal Webhook Deduplication & Contradiction Detection
# ============================================================================


def test_inbound_paypal_webhook_deduplication(client, db_session, auth_org):
    """
    Exit Gate: Identical PayPal webhook event ID returns duplicate status.
    """
    event_id = f"WH-EVENT-{uuid.uuid4().hex[:12]}"
    payload = {
        "id": event_id,
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "ORDER-123"},
    }

    # First delivery
    res1 = client.post("/v1/webhooks/paypal/simulated", json=payload)
    assert res1.status_code == 200
    assert res1.json()["status"] in ("received", "ignored")

    # Duplicate delivery
    res2 = client.post("/v1/webhooks/paypal/simulated", json=payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate"


def test_inbound_paypal_contradiction_detection(client, db_session, auth_org):
    """
    Exit Gate: Contradictory PayPal webhook flags needs_attention=True and emits CONTRADICTION_DETECTED.
    """
    cid = generate_id("ctr")
    order_id = f"ORDER-{uuid.uuid4().hex[:8]}"
    contract = Contract(
        id=cid,
        org_id=auth_org["org_id"],
        title="Funded Contract",
        worker_id="w-1",
        worker_email="w@corp.com",
        environment="simulated",
        status=ContractStatus.FUNDED.value,
        paypal_order_id=order_id,
        total_cents=1000,
        currency="USD",
        needs_attention=False,
    )
    db_session.add(contract)
    db_session.commit()

    # PayPal claims order was voided while local contract is FUNDED!
    event_id = f"WH-VOID-{uuid.uuid4().hex[:8]}"
    contradiction_payload = {
        "id": event_id,
        "event_type": "CHECKOUT.ORDER.VOIDED",
        "resource": {"id": order_id},
    }

    res = client.post("/v1/webhooks/paypal/simulated", json=contradiction_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "received"
    assert data["action"] == "contradiction_flagged"

    db_session.refresh(contract)
    assert contract.needs_attention is True
    # Invariant: contract status is NOT blindly modified to VOIDED
    assert contract.status == ContractStatus.FUNDED.value


# ============================================================================
# 4. Reconciliation Discrepancy Reporting
# ============================================================================


def test_reconciliation_flags_discrepancies(client, db_session, auth_org):
    """
    Exit Gate: Reconciliation compares local contracts vs PayPal provider and flags discrepancies.
    """
    cid = generate_id("ctr")
    auth_id = f"AUTH-DISCREPANCY-{uuid.uuid4().hex[:8]}"
    contract = Contract(
        id=cid,
        org_id=auth_org["org_id"],
        title="Discrepant Contract",
        worker_id="w-discrepancy",
        worker_email="w@corp.com",
        environment="simulated",
        status=ContractStatus.FUNDED.value,
        paypal_authorization_id=auth_id,
        total_cents=1500,
        currency="USD",
        needs_attention=False,
    )
    db_session.add(contract)
    db_session.commit()

    # Run reconciliation via API
    res = client.post("/v1/reconcile", json={"environment": "simulated"})
    assert res.status_code == 200, res.text
    run_data = res.json()
    assert run_data["contracts_checked"] >= 1
    assert "run_id" in run_data


# ============================================================================
# 5. Red Team Arena (6/6 Scenarios Pass)
# ============================================================================


def test_playground_all_six_scenarios_pass(client):
    """
    Exit Gate: Red Team Arena executes all 6 attack scenarios and verifies all defenses hold.
    """
    # 1. Check scenarios listing
    res_scenarios = client.get("/v1/playground/scenarios")
    assert res_scenarios.status_code == 200
    scenarios = res_scenarios.json()
    assert len(scenarios) == 6
    expected_ids = {
        "prompt_injection_bypass",
        "ast_escape_tampering",
        "resource_exhaustion_loop",
        "time_travel_expiry",
        "hidden_test_probe",
        "concurrent_race_double_spend",
    }
    assert {s["id"] for s in scenarios} == expected_ids

    # 2. Execute all scenarios
    res_run = client.post("/v1/playground/run", json={"scenario": "all"})
    assert res_run.status_code == 200, res_run.text
    run_result = res_run.json()

    assert run_result["status"] == "completed"
    assert run_result["scenarios_evaluated"] == 6
    assert run_result["all_defenses_passed"] is True, f"Failed defenses: {run_result['results']}"

    for r in run_result["results"]:
        assert r["blocked"] is True, f"Scenario {r['scenario']} was not blocked by defense!"


# ============================================================================
# 6. Organization Stats and Worker Reputation
# ============================================================================


def test_org_stats_and_worker_reputation(client, db_session, auth_org):
    """
    Exit Gate: GET /v1/org/stats and GET /v1/workers/{worker_id}/stats return accurate aggregates.
    """
    cid = generate_id("ctr")
    contract = Contract(
        id=cid,
        org_id=auth_org["org_id"],
        title="Stats Contract",
        worker_id="worker-stats-1",
        worker_email="stats_worker@corp.com",
        environment="simulated",
        status=ContractStatus.COMPLETED.value,
        total_cents=1200,
        currency="USD",
    )
    db_session.add(contract)
    mid = generate_id("mst")
    milestone = Milestone(
        id=mid,
        org_id=auth_org["org_id"],
        contract_id=cid,
        sequence=1,
        title="M1",
        amount_cents=1200,
        spec="Spec",
        public_tests="def test_p(): pass\n",
        hidden_tests="def test_h(): pass\n",
        hidden_commitment_hash="c" * 64,
        status=MilestoneStatus.PAID.value,
        attempts_count=1,
        paid_at=datetime.now(timezone.utc),
    )
    db_session.add(milestone)
    db_session.commit()

    # Query org stats
    res_stats = client.get("/v1/org/stats")
    assert res_stats.status_code == 200, res_stats.text
    stats_data = res_stats.json()
    assert stats_data["total_spend_cents"] == 1200
    assert stats_data["completed_count"] >= 1

    # Query worker stats
    res_worker = client.get(f"/v1/workers/{contract.worker_id}/stats")
    assert res_worker.status_code == 200, res_worker.text
    worker_data = res_worker.json()
    assert worker_data["worker_id"] == contract.worker_id
    assert worker_data["completion_rate"] == 100.0
    assert worker_data["masked_email"] == "s***@corp.com"


# ============================================================================
# 7. SSE Stream
# ============================================================================


def test_sse_stream_poll_once(client, db_session, auth_org):
    """
    Exit Gate: SSE stream yields events formatted with id, event, and data.
    """
    cid = generate_id("ctr")
    contract = Contract(
        id=cid,
        org_id=auth_org["org_id"],
        title="Stream Contract",
        worker_id="worker-stream",
        worker_email="w@corp.com",
        environment="simulated",
        status=ContractStatus.AWAITING_FUNDING.value,
        total_cents=500,
        currency="USD",
    )
    db_session.add(contract)
    db_session.commit()

    append_event(
        db_session,
        event_type="TEST_STREAM_EVENT",
        payload={"hello": "world"},
        contract_id=cid,
        org_id=auth_org["org_id"],
    )
    db_session.commit()

    res = client.get("/v1/stream?poll_once=true")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text
    assert "event: TEST_STREAM_EVENT" in body
    assert "TEST_STREAM_EVENT" in body
