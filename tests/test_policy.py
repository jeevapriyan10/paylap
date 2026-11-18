from datetime import datetime, timezone

from app.ids import generate_id
from app.models import Contract, Policy
from app.state import ContractStatus


def test_policy_endpoint(client):
    res = client.get("/v1/system/policy")
    assert res.status_code == 200
    data = res.json()
    assert data["max_task_cents"] == 2500
    assert data["daily_cap_cents"] == 10000
    assert data["max_milestones"] == 5


def test_policy_per_task_cap(client, auth_org, db_session):
    # Set org policy for simulated environment to $25.00 max task
    pol = (
        db_session.query(Policy).filter(Policy.org_id == auth_org["org_id"], Policy.environment == "simulated").first()
    )
    if not pol:
        pol = Policy(
            id=generate_id("pol"),
            org_id=auth_org["org_id"],
            environment="simulated",
            max_task_cents=2500,
            daily_cap_cents=10000,
            max_milestones=5,
            worker_allowlist=None,
            require_hidden_tests=False,
            max_contract_days=28,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(pol)
    else:
        pol.max_task_cents = 2500
    db_session.commit()

    # Budget $30.00 > $25.00 limit -> 422
    payload = {
        "title": "Expensive Task",
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "M1",
                "amount": "30.00",
                "spec": "do something",
                "public_tests": "def test_ok(): pass",
            }
        ],
    }
    res = client.post("/v1/contracts", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "Policy violation" in str(data) or "exceeds" in str(data)

    # Verify contract is recorded as BLOCKED
    contract = (
        db_session.query(Contract)
        .filter(Contract.org_id == auth_org["org_id"], Contract.title == "Expensive Task")
        .first()
    )
    assert contract is not None
    assert contract.status == ContractStatus.BLOCKED.value


def test_policy_daily_rolling_cap(client, auth_org, db_session):
    pol = (
        db_session.query(Policy).filter(Policy.org_id == auth_org["org_id"], Policy.environment == "simulated").first()
    )
    if not pol:
        pol = Policy(
            id=generate_id("pol"),
            org_id=auth_org["org_id"],
            environment="simulated",
            max_task_cents=5000,
            daily_cap_cents=6000,  # $60.00 cap
            max_milestones=5,
            worker_allowlist=None,
            require_hidden_tests=False,
            max_contract_days=28,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(pol)
    else:
        pol.max_task_cents = 5000
        pol.daily_cap_cents = 6000
    db_session.commit()

    # Task 1: $40.00 (allowed, cumulative = $40)
    p1 = {
        "title": "Daily Task 1",
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "environment": "simulated",
        "milestones": [{"title": "M1", "amount": "40.00", "spec": "m1", "public_tests": "def test_ok(): pass"}],
    }
    r1 = client.post("/v1/contracts", json=p1)
    assert r1.status_code == 201

    # Task 2: $30.00 (projected = $70 > $60 limit -> BLOCKED)
    p2 = {
        "title": "Daily Task 2",
        "worker_id": "worker_1",
        "worker_email": "worker1@test.com",
        "environment": "simulated",
        "milestones": [{"title": "M1", "amount": "30.00", "spec": "m1", "public_tests": "def test_ok(): pass"}],
    }
    r2 = client.post("/v1/contracts", json=p2)
    assert r2.status_code == 422
    assert "exceeds remaining daily spend cap" in r2.text or "Policy violation" in r2.text


def test_policy_allowlist(client, auth_org, db_session):
    pol = (
        db_session.query(Policy).filter(Policy.org_id == auth_org["org_id"], Policy.environment == "simulated").first()
    )
    if not pol:
        pol = Policy(
            id=generate_id("pol"),
            org_id=auth_org["org_id"],
            environment="simulated",
            max_task_cents=5000,
            daily_cap_cents=20000,
            max_milestones=5,
            worker_allowlist=["allowed@test.com", "vip@corp.org"],
            require_hidden_tests=False,
            max_contract_days=28,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(pol)
    else:
        pol.worker_allowlist = ["allowed@test.com", "vip@corp.org"]
        pol.require_hidden_tests = False
    db_session.commit()

    # Disallowed email
    bad_payload = {
        "title": "Allowlist Check Fail",
        "worker_id": "worker_bad",
        "worker_email": "hacker@evil.com",
        "environment": "simulated",
        "milestones": [{"title": "M1", "amount": "10.00", "spec": "m1", "public_tests": "def test_ok(): pass"}],
    }
    r_bad = client.post("/v1/contracts", json=bad_payload)
    assert r_bad.status_code == 422
    assert "approved worker allowlist" in r_bad.text or "Policy violation" in r_bad.text

    # Allowed email (case insensitive)
    good_payload = {
        "title": "Allowlist Check Pass",
        "worker_id": "worker_good",
        "worker_email": "  Allowed@TEST.com  ",
        "environment": "simulated",
        "milestones": [{"title": "M1", "amount": "10.00", "spec": "m1", "public_tests": "def test_ok(): pass"}],
    }
    r_good = client.post("/v1/contracts", json=good_payload)
    assert r_good.status_code == 201


def test_policy_milestone_count(client, auth_org, db_session):
    # 6 milestones > 5 allowed
    payload_6 = {
        "title": "Too Many Milestones",
        "worker_id": "worker_1",
        "worker_email": "worker@test.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": f"M{i}",
                "amount": "2.00",
                "spec": f"m{i}",
                "public_tests": "def test_ok(): pass",
            }
            for i in range(1, 7)
        ],
    }
    r6 = client.post("/v1/contracts", json=payload_6)
    assert r6.status_code == 422
    assert "at most 5 items" in r6.text or "violates policy" in r6.text
