import concurrent.futures
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import get_db
from app.ids import generate_id
from app.main import app
from app.models import ApiKey, Contract, Event, Membership, Milestone, Organization, User
from app.routers.auth import Principal, get_current_principal
from app.services.auth import generate_api_key, hash_password
from app.services.clock import FakeClock
from app.services.expiry import expire_due_contracts
from app.services.settlement import settle_milestone
from app.state import ContractStatus, MilestoneStatus

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
def auth_org(db_session):
    """Fixture providing a verified test organization and developer API key."""
    org_id = generate_id("org")
    user_id = generate_id("usr")

    org = Organization(
        id=org_id,
        name="Test Org P5",
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
            "receipts:read",
            "policy:read",
        ],
        created_by=user_id,
    )
    db_session.add(api_key_record)
    db_session.commit()

    return {
        "org_id": org_id,
        "user_id": user_id,
        "api_key": full_key,
    }


@pytest.fixture
def client(db_session, auth_org):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_current_principal():
        return Principal(
            user_id=auth_org["user_id"],
            org_id=auth_org["org_id"],
            role="developer",
            api_key_id="test_key",
            scopes=["contracts:read", "contracts:write", "receipts:read"],
            env_class="test",
            is_api_key=True,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_principal] = override_get_current_principal

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_full_milestone_lifecycle_simulated(client, db_session, auth_org):
    """
    Simulated provider drives full milestone lifecycle:
    Contract created -> auto-funded -> milestone 1 settled -> milestone 2 settled -> contract COMPLETED.
    """
    create_payload = {
        "title": "Data Processing Engine",
        "worker_id": "worker-1",
        "worker_email": "worker1@example.com",
        "environment": "simulated",
        "capture_strategy": "partial",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "Parse JSON",
                "amount_minor": 200,
                "spec": "Implement parse_count(s) returning item count",
                "verifier_type": "python_code",
                "public_tests": "from solution import parse_count\ndef test_parse(): assert parse_count('[1, 2, 3]') == 3\n",
                "hidden_tests": "from solution import parse_count\ndef test_hidden(): assert parse_count('[]') == 0\n",
            },
            {
                "title": "Sum Items",
                "amount_minor": 300,
                "spec": "Implement sum_items(s) returning sum",
                "verifier_type": "python_code",
                "public_tests": "from solution import sum_items\ndef test_sum(): assert sum_items([10, 20]) == 30\n",
                "hidden_tests": "from solution import sum_items\ndef test_hidden(): assert sum_items([]) == 0\n",
            },
        ],
    }

    # 1. Create contract
    res = client.post("/v1/contracts", json=create_payload)
    assert res.status_code == 201, res.text
    contract_data = res.json()
    contract_id = contract_data["id"]

    assert contract_data["status"] == "FUNDED"
    assert contract_data["total_cents"] == 500
    assert len(contract_data["milestones"]) == 2
    assert contract_data["milestones"][0]["status"] == "PENDING"
    assert contract_data["milestones"][1]["status"] == "PENDING"

    # 2. Submit solution for Milestone 1
    m1_code = "import json\ndef parse_count(s):\n    return len(json.loads(s))\n"
    m1_res = client.post(
        f"/v1/contracts/{contract_id}/milestones/1/submit",
        json={"code": m1_code},
    )
    assert m1_res.status_code == 200, m1_res.text
    m1_outcome = m1_res.json()
    assert m1_outcome["passed"] is True
    assert m1_outcome["status"] == "PAID"
    assert m1_outcome["capture_id"] is not None

    # Check contract detail: milestone 1 PAID, contract still FUNDED
    detail1 = client.get(f"/v1/contracts/{contract_id}").json()["contract"]
    assert detail1["milestones"][0]["status"] == "PAID"
    assert detail1["status"] == "FUNDED"

    # 3. Submit solution for Milestone 2 (Final capture)
    m2_code = "def sum_items(items):\n    return sum(items)\n"
    m2_res = client.post(
        f"/v1/contracts/{contract_id}/milestones/2/submit",
        json={"code": m2_code},
    )
    assert m2_res.status_code == 200, m2_res.text
    m2_outcome = m2_res.json()
    assert m2_outcome["passed"] is True
    assert m2_outcome["status"] == "PAID"

    # Contract must now be COMPLETED
    detail2 = client.get(f"/v1/contracts/{contract_id}").json()["contract"]
    assert detail2["milestones"][1]["status"] == "PAID"
    assert detail2["status"] == "COMPLETED"


def test_structural_invariant_failing_verifier_never_reaches_arbiter(client, db_session, auth_org):
    """
    Structural Invariant: When deterministic tests fail, the LLM Arbiter MUST NOT be called.
    """
    create_payload = {
        "title": "Strict Logic Contract",
        "worker_id": "worker-2",
        "worker_email": "worker2@example.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Math Milestone",
                "amount_minor": 100,
                "spec": "Implement add(a, b)",
                "verifier_type": "python_code",
                "public_tests": "from solution import add\ndef test_add(): assert add(2, 3) == 5\n",
                "hidden_tests": "from solution import add\ndef test_hidden(): assert add(1, 1) == 2\n",
            }
        ],
    }

    res = client.post("/v1/contracts", json=create_payload)
    assert res.status_code == 201
    contract_id = res.json()["id"]

    # Failing submission
    failing_code = "def add(a, b):\n    return a - b\n"

    with patch("app.services.settlement.review_submission") as mock_arbiter:
        submit_res = client.post(
            f"/v1/contracts/{contract_id}/milestones/1/submit",
            json={"code": failing_code},
        )
        assert submit_res.status_code == 200
        outcome = submit_res.json()
        assert outcome["passed"] is False
        assert outcome["status"] == "REJECTED"

        # STRUCTURAL CHECK: Arbiter was NEVER invoked
        mock_arbiter.assert_not_called()


def test_concurrency_double_spend_prevention(client, db_session, auth_org):
    """
    Concurrency test: Concurrent submissions for the same milestone cannot produce double capture/payout.
    """
    create_payload = {
        "title": "Concurrent Race Contract",
        "worker_id": "worker-race",
        "worker_email": "race@example.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Race Milestone",
                "amount_minor": 150,
                "spec": "Fast logic",
                "verifier_type": "python_code",
                "public_tests": "from solution import compute\ndef test_c(): assert compute() == 1\n",
                "hidden_tests": "from solution import compute\ndef test_hidden(): assert compute() == 1\n",
            }
        ],
    }

    res = client.post("/v1/contracts", json=create_payload)
    assert res.status_code == 201
    contract_id = res.json()["id"]

    valid_code = "def compute(): return 1\n"

    # Spawn 5 concurrent threads attempting settlement
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                client.post,
                f"/v1/contracts/{contract_id}/milestones/1/submit",
                json={"code": valid_code},
            )
            for _ in range(5)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # All calls should return HTTP 200 (processed) or 400/409 (rejected concurrent attempts)
    for r in results:
        assert r.status_code in (200, 400, 409), r.text

    # At least one succeeded
    success_results = [r for r in results if r.status_code == 200]
    assert len(success_results) >= 1
    assert success_results[0].json()["passed"] is True
    assert success_results[0].json()["status"] == "PAID"

    # Verify ledger has exactly ONE CAPTURE_COMPLETED and ONE PAYOUT_INITIATED event for this milestone
    db_events = db_session.scalars(
        select(Event).where(Event.contract_id == contract_id)
    ).all()

    capture_events = [e for e in db_events if e.event_type == "CAPTURE_COMPLETED"]
    payout_events = [e for e in db_events if e.event_type == "PAYOUT_INITIATED"]

    assert len(capture_events) == 1, f"Expected exactly 1 capture event, got {len(capture_events)}"
    assert len(payout_events) == 1, f"Expected exactly 1 payout event, got {len(payout_events)}"


def test_fake_clock_deadline_expiry(client, db_session, auth_org):
    """
    Fake clock test: expire_due_contracts voids remaining hold and transitions status to EXPIRED.
    """
    initial_now = datetime.now(timezone.utc)
    fake_clock = FakeClock(initial_now)

    # 2 days in the future
    deadline = initial_now + timedelta(days=2)

    create_payload = {
        "title": "Time-sensitive Contract",
        "worker_id": "worker-time",
        "worker_email": "time@example.com",
        "environment": "simulated",
        "deadline_at": deadline.isoformat(),
        "milestones": [
            {
                "title": "Task A",
                "amount_minor": 250,
                "spec": "Fast work",
                "verifier_type": "python_code",
                "public_tests": "def test_ok(): pass\n",
                "hidden_tests": "def test_hidden(): pass\n",
            }
        ],
    }

    res = client.post("/v1/contracts", json=create_payload)
    assert res.status_code == 201
    contract_id = res.json()["id"]

    # At initial_now, not expired
    expired_ids = expire_due_contracts(db_session, clock=fake_clock)
    assert contract_id not in expired_ids

    # Advance clock by 3 days (past deadline)
    fake_clock.advance(timedelta(days=3))

    expired_ids = expire_due_contracts(db_session, clock=fake_clock)
    assert contract_id in expired_ids

    # Refresh contract from DB
    ctr = db_session.scalar(select(Contract).where(Contract.id == contract_id))
    assert ctr.status == ContractStatus.EXPIRED.value

    # Verify event recorded
    expiry_event = db_session.scalar(
        select(Event).where(Event.contract_id == contract_id, Event.event_type == "CONTRACT_EXPIRED")
    )
    assert expiry_event is not None


def test_planted_hidden_test_sentinel_never_leaks(client, db_session, auth_org):
    """
    Leak-sentinel test:
    Planted hidden test secret MUST NEVER leak into responses, events, receipts, or public payloads.
    """
    PLANTED_SENTINEL = "TOP_SECRET_PLANTED_SENTINEL_TOKEN_XYZ999"

    create_payload = {
        "title": "Confidential Tests Contract",
        "worker_id": "worker-secret",
        "worker_email": "worker_secret@corp.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Secret Milestone",
                "amount_minor": 100,
                "spec": "Check secret logic",
                "verifier_type": "python_code",
                "public_tests": "from solution import run\ndef test_run(): assert run() == 42\n",
                "hidden_tests": f"from solution import run\ndef test_hidden(): assert '{PLANTED_SENTINEL}' != ''\n",
            }
        ],
    }

    # 1. Create contract response check
    create_res = client.post("/v1/contracts", json=create_payload)
    assert create_res.status_code == 201
    create_text = create_res.text
    assert PLANTED_SENTINEL not in create_text, "Planted sentinel leaked in POST /v1/contracts response!"
    contract_id = create_res.json()["id"]

    # 2. GET /v1/contracts (list) check
    list_res = client.get("/v1/contracts")
    assert list_res.status_code == 200
    assert PLANTED_SENTINEL not in list_res.text, "Planted sentinel leaked in GET /v1/contracts response!"

    # 3. GET /v1/contracts/{id} (detail) check
    detail_res = client.get(f"/v1/contracts/{contract_id}")
    assert detail_res.status_code == 200
    assert PLANTED_SENTINEL not in detail_res.text, "Planted sentinel leaked in contract detail response!"

    # 4. Submit solution and check submit outcome
    submit_res = client.post(
        f"/v1/contracts/{contract_id}/milestones/1/submit",
        json={"code": "def run(): return 42\n"},
    )
    assert submit_res.status_code == 200
    assert PLANTED_SENTINEL not in submit_res.text, "Planted sentinel leaked in submit response!"

    # 5. GET /v1/contracts/{id}/receipt check
    receipt_res = client.get(f"/v1/contracts/{contract_id}/receipt")
    assert receipt_res.status_code == 200
    assert PLANTED_SENTINEL not in receipt_res.text, "Planted sentinel leaked in receipt!"

    # 6. Check all DB events for this contract
    events = db_session.scalars(select(Event).where(Event.contract_id == contract_id)).all()
    for e in events:
        import json
        payload_str = json.dumps(e.payload)
        assert PLANTED_SENTINEL not in payload_str, f"Planted sentinel leaked in event seq {e.seq} payload!"


def test_idempotency_key_replay_and_conflict(client, db_session, auth_org):
    """
    Idempotency-Key support:
    Replaying identical payload returns cached response with Idempotent-Replayed: true.
    Reusing key with different payload returns 422.
    """
    idem_key = f"idem-{generate_id('tst')}"
    payload_a = {
        "title": "Idempotent Contract",
        "worker_id": "worker-idem",
        "worker_email": "idem@example.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Milestone 1",
                "amount_minor": 100,
                "spec": "Spec",
                "verifier_type": "python_code",
                "public_tests": "def test_ok(): pass\n",
                "hidden_tests": "def test_hidden(): pass\n",
            }
        ],
    }

    # Initial request
    res1 = client.post("/v1/contracts", json=payload_a, headers={"Idempotency-Key": idem_key})
    assert res1.status_code == 201
    contract_id1 = res1.json()["id"]

    # Replay with same payload
    res2 = client.post("/v1/contracts", json=payload_a, headers={"Idempotency-Key": idem_key})
    assert res2.status_code == 201
    assert res2.headers.get("Idempotent-Replayed") == "true"
    assert res2.json()["id"] == contract_id1

    # Replay with DIFFERENT payload -> 422 Unprocessable Entity
    payload_b = dict(payload_a)
    payload_b["title"] = "Different Contract Title"
    res3 = client.post("/v1/contracts", json=payload_b, headers={"Idempotency-Key": idem_key})
    assert res3.status_code == 422


def test_arbiter_fail_closed_on_unavailable(client, db_session, auth_org):
    """
    Fail-closed policy:
    When Arbiter is unavailable, milestone resets to PENDING without consuming an attempt.
    """
    from app.services.arbiter import ArbiterResult

    create_payload = {
        "title": "Fail Closed Test",
        "worker_id": "worker-fc",
        "worker_email": "fc@example.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Milestone A",
                "amount_minor": 100,
                "spec": "Spec A",
                "verifier_type": "python_code",
                "public_tests": "def test_ok(): pass\n",
                "hidden_tests": "def test_hidden(): pass\n",
            }
        ],
    }

    res = client.post("/v1/contracts", json=create_payload)
    assert res.status_code == 201
    contract_id = res.json()["id"]

    # Mock arbiter returning unavailable
    unavailable_result = ArbiterResult(
        verdict="unavailable",
        reasons=["LLM upstream timeout"],
        risk_flags=[],
        source="gemini",
    )

    with patch("app.services.settlement.review_submission", return_value=unavailable_result):
        submit_res = client.post(
            f"/v1/contracts/{contract_id}/milestones/1/submit",
            json={"code": "pass\n"},
        )
        assert submit_res.status_code == 200
        outcome = submit_res.json()
        assert outcome["passed"] is False
        assert outcome["status"] == "PENDING"

        # Check detail: attempt NOT consumed
        detail = client.get(f"/v1/contracts/{contract_id}").json()["contract"]
        assert detail["milestones"][0]["status"] == "PENDING"
        assert detail["milestones"][0]["attempts"] == 0
