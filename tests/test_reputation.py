import uuid

from app.db import set_tenant_org
from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract, Milestone, Organization
from app.services.reputation import compute_worker_reputation
from app.state import MilestoneStatus


def _create_rep_org(db_session):
    org_id = generate_id("org")
    org = Organization(id=org_id, name="Reputation Org", slug=f"slug_{org_id}", live_enabled=False)
    db_session.add(org)
    db_session.commit()
    set_tenant_org(db_session, org_id)
    return org_id


def test_reputation_empty(db_session):
    rep = compute_worker_reputation(db_session, f"non_existent_{uuid.uuid4().hex[:8]}")
    assert rep["score"] == 0
    assert rep["attempted_milestones"] == 0
    assert rep["paid_milestones"] == 0
    assert rep["total_earned_usd"] == "0.00"


def test_reputation_honest_high_volume(db_session):
    org_id = _create_rep_org(db_session)
    worker_id = f"honest_worker_{uuid.uuid4().hex[:8]}"
    # Create contract with 5 paid milestones
    c = Contract(
        id=generate_id("ctr"),
        org_id=org_id,
        title="Honest Work",
        worker_id=worker_id,
        worker_email=f"{worker_id}@corp.com",
        total_cents=1000,
        currency="USD",
        status="COMPLETED",
        environment="simulated",
    )
    db_session.add(c)

    for i in range(1, 6):
        m = Milestone(
            id=generate_id("mst"),
            org_id=org_id,
            contract_id=c.id,
            sequence=i,
            title=f"M{i}",
            amount_cents=200,
            spec="s",
            public_tests="t",
            status=MilestoneStatus.PAID.value,
            attempts_count=1,
        )
        db_session.add(m)

    db_session.commit()

    rep = compute_worker_reputation(db_session, worker_id)
    # 5/5 paid = 100% pass rate, dampener = min(1.0, 5/5) = 1.0, penalties = 0 -> score = 100
    assert rep["score"] == 100
    assert rep["attempted_milestones"] == 5
    assert rep["paid_milestones"] == 5
    assert rep["volume_dampener"] == 1.0
    assert rep["total_earned_usd"] == "10.00"


def test_reputation_dampener_low_attempts(db_session):
    org_id = _create_rep_org(db_session)
    worker_id = f"junior_worker_{uuid.uuid4().hex[:8]}"
    # 1 paid milestone: dampener = 1/5 = 0.2
    c = Contract(
        id=generate_id("ctr"),
        org_id=org_id,
        title="Junior Work",
        worker_id=worker_id,
        worker_email=f"{worker_id}@corp.com",
        total_cents=200,
        currency="USD",
        status="COMPLETED",
        environment="simulated",
    )
    db_session.add(c)
    m = Milestone(
        id=generate_id("mst"),
        org_id=org_id,
        contract_id=c.id,
        sequence=1,
        title="M1",
        amount_cents=200,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.PAID.value,
        attempts_count=1,
    )
    db_session.add(m)
    db_session.commit()

    rep = compute_worker_reputation(db_session, worker_id)
    # pass_rate = 100%, dampener = 0.2 -> score = 20
    assert rep["score"] == 20
    assert rep["volume_dampener"] == 0.2


def test_reputation_security_penalties(db_session):
    org_id = _create_rep_org(db_session)
    worker_id = f"malicious_worker_{uuid.uuid4().hex[:8]}"
    # 5 attempted, 4 paid, but had 1 injection (-30), 1 AST violation (-15), 1 arbiter veto (-10)
    c = Contract(
        id=generate_id("ctr"),
        org_id=org_id,
        title="Malicious Work",
        worker_id=worker_id,
        worker_email=f"{worker_id}@corp.com",
        total_cents=1000,
        currency="USD",
        status="COMPLETED",
        environment="simulated",
    )
    db_session.add(c)

    for i in range(1, 5):
        m = Milestone(
            id=generate_id("mst"),
            org_id=org_id,
            contract_id=c.id,
            sequence=i,
            title=f"M{i}",
            amount_cents=200,
            spec="s",
            public_tests="t",
            status=MilestoneStatus.PAID.value,
            attempts_count=1,
        )
        db_session.add(m)

    # 1 rejected milestone
    m_fail = Milestone(
        id=generate_id("mst"),
        org_id=org_id,
        contract_id=c.id,
        sequence=5,
        title="M5",
        amount_cents=200,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.REJECTED.value,
        attempts_count=2,
    )
    db_session.add(m_fail)
    db_session.commit()

    # Append penalty events
    append_event(db_session, "INJECTION_ATTEMPT_DETECTED", {"reason": "test"}, contract_id=c.id, org_id=org_id)
    append_event(db_session, "AST_VIOLATION", {"reason": "import os"}, contract_id=c.id, org_id=org_id)
    append_event(db_session, "ARBITER_VETO", {"reason": "cheating"}, contract_id=c.id, org_id=org_id)
    db_session.commit()

    rep = compute_worker_reputation(db_session, worker_id)
    # pass_rate = 4/5 * 100 = 80.0
    # penalties = 30 + 15 + 10 = 55.0
    # dampener = min(1.0, 5/5) = 1.0
    # raw_score = (80.0 - 55.0) * 1.0 = 25.0 -> score = 25
    assert rep["attempted_milestones"] == 5
    assert rep["paid_milestones"] == 4
    assert rep["penalties"]["injection_attempts"] == 1
    assert rep["penalties"]["ast_policy_violations"] == 1
    assert rep["penalties"]["arbiter_vetoes"] == 1
    assert rep["score"] == 25


def test_reputation_api_endpoints(client, db_session, auth_org):
    worker_id = f"api_worker_{uuid.uuid4().hex[:8]}"
    # Setup worker via contract
    c = Contract(
        id=generate_id("ctr"),
        org_id=auth_org["org_id"],
        title="API Worker Contract",
        worker_id=worker_id,
        worker_email=f"{worker_id}@corp.com",
        total_cents=500,
        currency="USD",
        status="COMPLETED",
        environment="simulated",
    )
    db_session.add(c)
    m = Milestone(
        id=generate_id("mst"),
        org_id=auth_org["org_id"],
        contract_id=c.id,
        sequence=1,
        title="M1",
        amount_cents=500,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.PAID.value,
        attempts_count=1,
    )
    db_session.add(m)
    db_session.commit()

    # GET /v1/workers
    res_list = client.get("/v1/workers")
    assert res_list.status_code == 200
    workers = res_list.json()
    assert any(w["worker_id"] == worker_id for w in workers)

    # GET /v1/workers/{worker_id}
    res_single = client.get(f"/v1/workers/{worker_id}")
    assert res_single.status_code == 200
    single = res_single.json()
    assert single["worker_id"] == worker_id
    assert single["total_earned_usd"] == "5.00"
