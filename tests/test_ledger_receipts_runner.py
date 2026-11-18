import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import get_db
from app.ids import generate_id
from app.ledger import append_event, append_org_audit_log, verify_chain, verify_org_audit_chain
from app.main import app
from app.models import ApiKey, Contract, Event, Membership, Milestone, OrgAuditLog, Organization, ShareToken, User
from app.routers.auth import Principal, get_current_principal
from app.services.auth import generate_api_key, hash_password
from app.services.receipts import generate_receipt, verify_receipt
from app.services.runner import ProcessRunner, RunnerResult

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
    org_id = generate_id("org")
    user_id = generate_id("usr")

    org = Organization(
        id=org_id,
        name="P6 Test Org",
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
        scopes=["contracts:read", "contracts:write", "receipts:read"],
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
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

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


def test_50_concurrent_appends_produce_gapless_chain(db_session, auth_org):
    """
    Exit Gate: 50 concurrent appends on one contract produce a valid, gapless chain.
    PostgreSQL transaction advisory locks serialize concurrent appends cleanly.
    """
    contract_id = generate_id("ctr")
    contract = Contract(
        id=contract_id,
        org_id=auth_org["org_id"],
        title="Concurrent Append Contract",
        worker_id="worker-c",
        worker_email="c@example.com",
        environment="simulated",
        total_cents=1000,
        currency="USD",
        status="FUNDED",
    )
    db_session.add(contract)
    db_session.commit()

    def append_worker(step_idx: int):
        thread_db = TestingSessionLocal()
        try:
            append_event(
                thread_db,
                event_type="STEP_PROGRESS",
                payload={"step": step_idx, "random_data": f"data_{step_idx}"},
                contract_id=contract_id,
                org_id=auth_org["org_id"],
                simulated=True,
            )
            thread_db.commit()
        finally:
            thread_db.close()

    # Launch 50 concurrent appends across 10 threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(append_worker, i) for i in range(1, 51)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # Verify chain integrity
    is_valid, err, broken_seq = verify_chain(db_session, contract_id=contract_id)
    assert is_valid is True, f"Chain broken: {err} at seq {broken_seq}"

    # Verify exactly 50 events, sequence 1 through 50 with no gaps
    events = db_session.scalars(
        select(Event).where(Event.contract_id == contract_id).order_by(Event.seq.asc())
    ).all()

    assert len(events) == 50
    assert [e.seq for e in events] == list(range(1, 51))


def test_tampering_with_historical_event_is_detected(db_session, auth_org):
    """
    Exit Gate: Tampering with a historical event is detected by verify_chain.
    """
    contract_id = generate_id("ctr")
    contract = Contract(
        id=contract_id,
        org_id=auth_org["org_id"],
        title="Tamper Test Contract",
        worker_id="worker-t",
        worker_email="t@example.com",
        environment="simulated",
        total_cents=500,
        currency="USD",
        status="FUNDED",
    )
    db_session.add(contract)
    db_session.commit()

    # Append 3 events
    append_event(db_session, "EVENT_1", {"msg": "hello"}, contract_id=contract_id, org_id=auth_org["org_id"])
    append_event(db_session, "EVENT_2", {"msg": "world"}, contract_id=contract_id, org_id=auth_org["org_id"])
    append_event(db_session, "EVENT_3", {"msg": "finish"}, contract_id=contract_id, org_id=auth_org["org_id"])
    db_session.commit()

    # Initial state is valid
    is_valid, err, seq = verify_chain(db_session, contract_id)
    assert is_valid is True

    # Tamper with event seq 2 payload
    evt2 = db_session.scalar(
        select(Event).where(Event.contract_id == contract_id, Event.seq == 2)
    )
    evt2.payload = {"msg": "TAMPERED_DATA"}
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session, contract_id)
    assert is_valid is False
    assert broken_seq == 2
    assert "Corrupted hash at seq 2" in err


def test_org_audit_log_hash_chain_and_tampering(db_session, auth_org):
    """
    Verify per-org org_audit_log hash chain for sensitive operations.
    """
    org_id = auth_org["org_id"]

    e1 = append_org_audit_log(db_session, org_id, "KEY_CREATED", actor_id="user_1", details={"key_prefix": "pl_test"})
    e2 = append_org_audit_log(db_session, org_id, "POLICY_UPDATED", actor_id="user_1", details={"max_task_cents": 5000})
    e3 = append_org_audit_log(db_session, org_id, "CREDENTIAL_UPDATED", actor_id="user_1", details={"env": "sandbox"})
    db_session.commit()

    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3

    is_valid, err, broken = verify_org_audit_chain(db_session, org_id)
    assert is_valid is True

    # Tamper with seq 2
    e2_db = db_session.scalar(select(OrgAuditLog).where(OrgAuditLog.org_id == org_id, OrgAuditLog.seq == 2))
    e2_db.action = "TAMPERED_ACTION"
    db_session.commit()

    is_valid, err, broken = verify_org_audit_chain(db_session, org_id)
    assert is_valid is False
    assert broken == 2


def test_ed25519_receipt_generation_and_offline_verification(db_session, auth_org):
    """
    Exit Gate: scripts/verify_receipt.py verifies a real Ed25519 digital receipt offline.
    """
    contract_id = generate_id("ctr")
    contract = Contract(
        id=contract_id,
        org_id=auth_org["org_id"],
        title="Offline Receipt Contract",
        worker_id="worker-receipt",
        worker_email="secret_worker@corp.com",
        environment="simulated",
        total_cents=450,
        currency="USD",
        status="COMPLETED",
    )
    db_session.add(contract)

    milestone = Milestone(
        id=generate_id("mst"),
        org_id=auth_org["org_id"],
        contract_id=contract_id,
        sequence=1,
        title="Complete Task",
        amount_cents=450,
        spec="Specification",
        public_tests="def test_pass(): pass\n",
        hidden_tests="def test_hidden(): pass\n",
        hidden_commitment_hash="a"*64,
        status="PAID",
        attempts_count=1,
        paid_at=datetime.now(timezone.utc),
    )
    db_session.add(milestone)
    db_session.commit()

    append_event(db_session, "CONTRACT_CREATED", {"title": contract.title}, contract_id=contract_id, org_id=auth_org["org_id"])
    append_event(db_session, "CONTRACT_FUNDED", {"auth_id": "AUTH-1"}, contract_id=contract_id, org_id=auth_org["org_id"])
    append_event(db_session, "MILESTONE_PAID", {"amount_cents": 450}, contract_id=contract_id, org_id=auth_org["org_id"])
    db_session.commit()

    # Generate receipt v2
    receipt = generate_receipt(contract, db_session)

    # In-process verification
    is_valid, err = verify_receipt(receipt)
    assert is_valid is True, f"Receipt verification failed: {err}"
    assert receipt["worker_email_masked"] == "s***@corp.com"
    assert "secret_worker" not in receipt["worker_email_masked"]

    # Test standalone offline script verification via subprocess
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(receipt, f)
        temp_path = f.name

    try:
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "verify_receipt.py")

        # 1. Genuine receipt verification succeeds
        proc = subprocess.run(
            [sys.executable, script_path, temp_path],
            capture_output=True,
            text=True,
            check=False
        )
        assert proc.returncode == 0, f"verify_receipt.py failed: {proc.stderr}"
        assert "PayLap Cryptographic Receipt Verification: SUCCESS" in proc.stdout
        assert "Ed25519 Verified OK" in proc.stdout

        # 2. Tampered receipt fails offline verification
        tampered_receipt = dict(receipt)
        tampered_receipt["total_amount_minor"] = 999999
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(tampered_receipt, f)

        proc_tampered = subprocess.run(
            [sys.executable, script_path, temp_path],
            capture_output=True,
            text=True,
            check=False
        )
        assert proc_tampered.returncode != 0
        assert "FAILED" in proc_tampered.stderr

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_share_token_and_public_receipt_endpoint(client, db_session, auth_org):
    """
    Verify public receipt share token generation and unauthenticated public verification.
    """
    contract_id = generate_id("ctr")
    contract = Contract(
        id=contract_id,
        org_id=auth_org["org_id"],
        title="Shared Receipt Contract",
        worker_id="worker-share",
        worker_email="shared_worker@corp.com",
        environment="simulated",
        total_cents=300,
        currency="USD",
        status="COMPLETED",
    )
    db_session.add(contract)
    db_session.commit()

    append_event(db_session, "CONTRACT_CREATED", {"title": contract.title}, contract_id=contract_id, org_id=auth_org["org_id"])
    db_session.commit()

    # 1. Create share token (authenticated)
    res = client.post(f"/v1/contracts/{contract_id}/share")
    assert res.status_code == 200, res.text
    share_data = res.json()
    share_token = share_data["share_token"]
    assert share_token.startswith("shr_")

    # 2. Fetch public receipt (unauthenticated)
    pub_res = client.get(f"/v1/receipts/{share_token}", headers={"Authorization": ""})
    assert pub_res.status_code == 200, pub_res.text
    pub_receipt = pub_res.json()

    assert pub_receipt["contract_id"] == contract_id
    assert pub_receipt["worker_email_masked"] == "s***@corp.com"
    assert pub_receipt["signature"] is not None

    # Non-existent token returns 404
    bad_res = client.get("/v1/receipts/shr_nonexistent12345", headers={"Authorization": ""})
    assert bad_res.status_code == 404


def test_runner_refuses_dangerous_code_and_times_out():
    """
    Exit Gate: Runner refuses dangerous code and times out an infinite loop.
    """
    runner = ProcessRunner()

    # 1. Dangerous code construct (forbidden import / call)
    dangerous_code = "import os\nos.system('echo dangerous')\n"
    res_dangerous = runner.run(
        code=dangerous_code,
        tests="def test_dummy(): pass\n",
    )
    assert res_dangerous.passed is False
    assert len(res_dangerous.violations) > 0
    assert any("os" in v for v in res_dangerous.violations)
    assert "Security Policy Violation" in res_dangerous.output

    # 2. Infinite loop timeout
    infinite_loop_code = "def loop_forever():\n    while True:\n        pass\n"
    infinite_loop_test = "from solution import loop_forever\ndef test_hang(): loop_forever()\n"

    res_timeout = runner.run(
        code=infinite_loop_code,
        tests=infinite_loop_test,
        timeout_seconds=1.5,
    )
    assert res_timeout.passed is False
    assert res_timeout.timed_out is True
    assert "timed out" in res_timeout.output.lower()

