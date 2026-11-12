import pytest
from fastapi.testclient import TestClient
from app.config import settings
from app.db import get_db
from app.ledger import verify_chain
from app.main import app
from app.models import Contract, Event
from app.state import ContractStatus


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_policy_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "PAYLAP_POLICY_MAX_TASK_USD", 35.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_DAILY_USD", 150.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_ALLOWLIST", "alice@test.com, bob@corp.org")

    res = client.get("/api/policy")
    assert res.status_code == 200
    data = res.json()
    assert data["max_task_usd"] == 35.0
    assert data["daily_usd"] == 150.0
    # Masked emails
    assert "a***@test.com" in data["allowlist"]
    assert "b***@corp.org" in data["allowlist"]


def test_policy_per_task_cap(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "PAYLAP_POLICY_MAX_TASK_USD", 25.0)

    # Budget $30.00 > $25.00 limit
    payload = {
        "title": "Expensive Task",
        "buyer_id": "buyer_policy_1",
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "M1",
                "amount": "30.00",
                "spec": "do something",
                "public_tests": "def test_ok(): pass",
            }
        ],
    }
    res = client.post("/api/contracts", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "Policy violation" in str(data)
    violations = data.get("violations") or data.get("detail", {}).get("violations")
    assert any("exceeds maximum task policy limit" in v for v in violations)

    # Verify contract is recorded as BLOCKED
    contract_id = data.get("contract_id")
    contract = db_session.query(Contract).filter(Contract.id == contract_id).first()
    assert contract is not None
    assert contract.status == ContractStatus.BLOCKED.value

    # Verify POLICY_BLOCKED event was recorded
    evt = (
        db_session.query(Event)
        .filter(Event.contract_id == contract_id, Event.type == "POLICY_BLOCKED")
        .first()
    )
    assert evt is not None
    assert "violations" in evt.payload

    # Verify ledger integrity
    valid, _, _ = verify_chain(db_session)
    assert valid is True


def test_policy_daily_rolling_cap(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "PAYLAP_POLICY_MAX_TASK_USD", 50.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_DAILY_USD", 60.0)

    buyer = "buyer_rolling_test"

    # Task 1: $40.00 (allowed, cumulative = $40)
    p1 = {
        "title": "Task 1",
        "buyer_id": buyer,
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "max_attempts": 2,
        "milestones": [
            {"title": "M1", "amount": "40.00", "spec": "m1", "public_tests": "def test_ok(): pass"}
        ],
    }
    r1 = client.post("/api/contracts", json=p1)
    assert r1.status_code == 201

    # Task 2: $30.00 (projected = $70 > $60 limit -> BLOCKED)
    p2 = {
        "title": "Task 2",
        "buyer_id": buyer,
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "max_attempts": 2,
        "milestones": [
            {"title": "M1", "amount": "30.00", "spec": "m1", "public_tests": "def test_ok(): pass"}
        ],
    }
    r2 = client.post("/api/contracts", json=p2)
    assert r2.status_code == 422
    data2 = r2.json()
    violations2 = data2.get("violations") or data2.get("detail", {}).get("violations")
    assert any("daily policy limit" in v for v in violations2)


def test_policy_allowlist(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "PAYLAP_POLICY_MAX_TASK_USD", 50.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_DAILY_USD", 200.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_ALLOWLIST", "allowed@test.com, vip@corp.org")

    # Disallowed email
    bad_payload = {
        "title": "Allowlist Check Fail",
        "buyer_id": "buyer_allowlist",
        "worker_id": "worker_bad",
        "worker_email": "hacker@evil.com",
        "max_attempts": 2,
        "milestones": [
            {"title": "M1", "amount": "10.00", "spec": "m1", "public_tests": "def test_ok(): pass"}
        ],
    }
    r_bad = client.post("/api/contracts", json=bad_payload)
    assert r_bad.status_code == 422
    data_bad = r_bad.json()
    violations_bad = data_bad.get("violations") or data_bad.get("detail", {}).get("violations")
    assert any("not in the authorized recipient allowlist" in v for v in violations_bad)

    # Allowed email (with case insensitivity and whitespace test)
    good_payload = {
        "title": "Allowlist Check Pass",
        "buyer_id": "buyer_allowlist",
        "worker_id": "worker_good",
        "worker_email": "  Allowed@TEST.com  ",
        "max_attempts": 2,
        "milestones": [
            {"title": "M1", "amount": "10.00", "spec": "m1", "public_tests": "def test_ok(): pass"}
        ],
    }
    r_good = client.post("/api/contracts", json=good_payload)
    assert r_good.status_code == 201


def test_policy_milestone_count(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "PAYLAP_POLICY_MAX_TASK_USD", 50.0)
    monkeypatch.setattr(settings, "PAYLAP_POLICY_DAILY_USD", 200.0)

    # 4 milestones > 3 allowed
    payload_4 = {
        "title": "Too Many Milestones",
        "buyer_id": "buyer_ms",
        "worker_id": "worker_1",
        "worker_email": "worker@test.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": f"M{i}",
                "amount": "2.00",
                "spec": f"m{i}",
                "public_tests": "def test_ok(): pass",
            }
            for i in range(1, 5)
        ],
    }
    r4 = client.post("/api/contracts", json=payload_4)
    assert r4.status_code == 422
    data4 = r4.json()
    violations4 = data4.get("violations") or data4.get("detail", {}).get("violations")
    assert any("violates policy (must be 1 to 3)" in v for v in violations4)
