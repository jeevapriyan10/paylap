import pytest
from fastapi.testclient import TestClient
from app.db import get_db
from app.ledger import append_event
from app.main import app
from app.models import Contract, Milestone
from app.services.reputation import compute_worker_reputation, list_worker_reputations
from app.state import MilestoneStatus


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


def test_reputation_empty(db_session):
    rep = compute_worker_reputation(db_session, "non_existent_worker")
    assert rep["score"] == 0
    assert rep["attempted_milestones"] == 0
    assert rep["paid_milestones"] == 0
    assert rep["total_earned_usd"] == "0.00"


def test_reputation_honest_high_volume(db_session):
    worker_id = "honest_worker_1"
    # Create contract with 5 paid milestones
    c = Contract(
        id="c_honest",
        title="Honest Work",
        buyer_id="buyer_h",
        worker_id=worker_id,
        worker_email="honest@corp.com",
        total_cents=1000,
        currency="USD",
        status="COMPLETED",
        mode="demo",
        max_attempts=2,
    )
    db_session.add(c)

    for i in range(1, 6):
        m = Milestone(
            id=f"m_honest_{i}",
            contract_id=c.id,
            idx=i,
            title=f"M{i}",
            amount_cents=200,
            spec="s",
            public_tests="t",
            status=MilestoneStatus.PAID.value,
            attempts=1,
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
    worker_id = "junior_worker_1"
    # 1 paid milestone: dampener = 1/5 = 0.2
    c = Contract(
        id="c_junior",
        title="Junior Work",
        buyer_id="buyer_j",
        worker_id=worker_id,
        worker_email="junior@corp.com",
        total_cents=200,
        currency="USD",
        status="COMPLETED",
        mode="demo",
        max_attempts=2,
    )
    db_session.add(c)
    m = Milestone(
        id="m_junior_1",
        contract_id=c.id,
        idx=1,
        title="M1",
        amount_cents=200,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.PAID.value,
        attempts=1,
    )
    db_session.add(m)
    db_session.commit()

    rep = compute_worker_reputation(db_session, worker_id)
    # pass_rate = 100%, dampener = 0.2 -> score = 20
    assert rep["score"] == 20
    assert rep["volume_dampener"] == 0.2


def test_reputation_security_penalties(db_session):
    worker_id = "malicious_worker_1"
    # 5 attempted, 4 paid, but had 1 injection (-30), 1 AST violation (-15), 1 arbiter veto (-10)
    c = Contract(
        id="c_mal",
        title="Malicious Work",
        buyer_id="buyer_m",
        worker_id=worker_id,
        worker_email="bad@corp.com",
        total_cents=1000,
        currency="USD",
        status="COMPLETED",
        mode="demo",
        max_attempts=2,
    )
    db_session.add(c)

    for i in range(1, 5):
        m = Milestone(
            id=f"m_mal_{i}",
            contract_id=c.id,
            idx=i,
            title=f"M{i}",
            amount_cents=200,
            spec="s",
            public_tests="t",
            status=MilestoneStatus.PAID.value,
            attempts=1,
        )
        db_session.add(m)

    # 1 rejected milestone
    m_fail = Milestone(
        id="m_mal_5",
        contract_id=c.id,
        idx=5,
        title="M5",
        amount_cents=200,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.REJECTED.value,
        attempts=2,
    )
    db_session.add(m_fail)
    db_session.commit()

    # Append penalty events
    append_event(db_session, "INJECTION_ATTEMPT_DETECTED", {"reason": "test"}, contract_id=c.id)
    append_event(db_session, "AST_VIOLATION", {"reason": "import os"}, contract_id=c.id)
    append_event(db_session, "ARBITER_VETO", {"reason": "cheating"}, contract_id=c.id)

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


def test_reputation_api_endpoints(client, db_session):
    # Setup worker via contract
    c = Contract(
        id="c_api_w",
        title="API Worker Contract",
        buyer_id="buyer_api",
        worker_id="api_worker_99",
        worker_email="api_worker@corp.com",
        total_cents=500,
        currency="USD",
        status="COMPLETED",
        mode="demo",
        max_attempts=1,
    )
    db_session.add(c)
    m = Milestone(
        id="m_api_w",
        contract_id=c.id,
        idx=1,
        title="M1",
        amount_cents=500,
        spec="s",
        public_tests="t",
        status=MilestoneStatus.PAID.value,
        attempts=1,
    )
    db_session.add(m)
    db_session.commit()

    # GET /api/workers
    res_list = client.get("/api/workers")
    assert res_list.status_code == 200
    workers = res_list.json()
    assert any(w["worker_id"] == "api_worker_99" for w in workers)

    # GET /api/workers/{worker_id}
    res_single = client.get("/api/workers/api_worker_99")
    assert res_single.status_code == 200
    single = res_single.json()
    assert single["worker_id"] == "api_worker_99"
    assert single["total_earned_usd"] == "5.00"
