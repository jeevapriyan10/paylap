import pytest
from fastapi.testclient import TestClient
from app.db import get_db
from app.main import app
from app.models import Event


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


def test_e2e_two_milestone_success_path(client, db_session):
    payload = {
        "title": "Build Data Pipeline",
        "buyer_id": "buyer-123",
        "worker_id": "worker-456",
        "worker_email": "worker@test.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "Parse Data",
                "amount": "2.00",
                "spec": "Implement parse(s) returning int",
                "public_tests": "from solution import parse\ndef test_p(): assert parse('42') == 42",
                "hidden_tests": "def test_hidden(): pass",
            },
            {
                "title": "Aggregate Data",
                "amount": "3.00",
                "spec": "Implement aggregate(nums) returning sum",
                "public_tests": "from solution import aggregate\ndef test_a(): assert aggregate([1, 2, 3]) == 6",
            },
        ],
    }

    # 1. Create contract (demo mode auto-funds)
    res = client.post("/api/contracts", json=payload)
    assert res.status_code == 201
    contract = res.json()
    contract_id = contract["id"]
    assert contract["status"] == "FUNDED"
    assert contract["total_usd"] == "5.00"
    assert contract["total_cents"] == 500
    assert len(contract["milestones"]) == 2

    # 2. Submit solution for Milestone 1
    m1_code = "def parse(s):\n    return int(s)\n"
    res_m1 = client.post(
        f"/api/contracts/{contract_id}/milestones/1/submit",
        json={"code": m1_code},
    )
    assert res_m1.status_code == 200
    out_m1 = res_m1.json()
    assert out_m1["passed"] is True
    assert out_m1["status"] == "PAID"
    assert out_m1["capture_id"].startswith("DEMO-CAP-")
    assert out_m1["payout_batch_id"].startswith("DEMO-BATCH-")
    assert out_m1["simulated"] is True

    # Check contract still FUNDED because Milestone 2 is pending
    res_c1 = client.get(f"/api/contracts/{contract_id}")
    assert res_c1.status_code == 200
    assert res_c1.json()["contract"]["status"] == "FUNDED"

    # 3. Submit solution for Milestone 2 (the final milestone)
    m2_code = "def aggregate(nums):\n    return sum(nums)\n"
    res_m2 = client.post(
        f"/api/contracts/{contract_id}/milestones/2/submit",
        json={"code": m2_code},
    )
    assert res_m2.status_code == 200
    out_m2 = res_m2.json()
    assert out_m2["passed"] is True
    assert out_m2["status"] == "PAID"

    # Contract should now be COMPLETED
    res_c2 = client.get(f"/api/contracts/{contract_id}")
    assert res_c2.status_code == 200
    c_final = res_c2.json()["contract"]
    assert c_final["status"] == "COMPLETED"

    # Verify event logs for final capture
    cap_events = (
        db_session.query(Event)
        .filter(Event.contract_id == contract_id, Event.type == "CAPTURE_COMPLETED")
        .order_by(Event.seq.asc())
        .all()
    )
    assert len(cap_events) == 2
    # First capture had final_capture=False, second had final_capture=True
    assert cap_events[0].payload["final_capture"] is False
    assert cap_events[0].payload["amount_cents"] == 200
    assert cap_events[1].payload["final_capture"] is True
    assert cap_events[1].payload["amount_cents"] == 300


def test_e2e_reject_then_void_path(client):
    payload = {
        "title": "Strict Single Attempt Contract",
        "buyer_id": "buyer-1",
        "worker_id": "worker-1",
        "worker_email": "worker@test.com",
        "max_attempts": 1,
        "milestones": [
            {
                "title": "Compute Factorial",
                "amount": "10.00",
                "spec": "Implement factorial(n)",
                "public_tests": "from solution import factorial\ndef test_f(): assert factorial(3) == 6",
            }
        ],
    }

    create_res = client.post("/api/contracts", json=payload)
    contract_id = create_res.json()["id"]

    # Submit deliberately buggy code
    bad_code = "def factorial(n):\n    return 0\n"
    sub_res = client.post(
        f"/api/contracts/{contract_id}/milestones/1/submit",
        json={"code": bad_code},
    )
    assert sub_res.status_code == 200
    outcome = sub_res.json()
    assert outcome["passed"] is False
    assert outcome["status"] == "REJECTED"

    # Since max_attempts was 1 and it failed, contract should be VOIDED
    detail_res = client.get(f"/api/contracts/{contract_id}")
    c = detail_res.json()["contract"]
    assert c["status"] == "VOIDED"


def test_e2e_retry_path(client):
    payload = {
        "title": "Retry Allowed Contract",
        "buyer_id": "b-1",
        "worker_id": "w-1",
        "worker_email": "w@test.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "Square",
                "amount": "5.00",
                "spec": "Implement sq(n)",
                "public_tests": "from solution import sq\ndef test_sq(): assert sq(4) == 16",
            }
        ],
    }

    create_res = client.post("/api/contracts", json=payload)
    contract_id = create_res.json()["id"]

    # Attempt 1: Fail
    res1 = client.post(
        f"/api/contracts/{contract_id}/milestones/1/submit",
        json={"code": "def sq(n):\n    return n * 2\n"},
    )
    assert res1.status_code == 200
    assert res1.json()["passed"] is False

    # Contract remains FUNDED because attempts (1) < max_attempts (2)
    detail1 = client.get(f"/api/contracts/{contract_id}").json()["contract"]
    assert detail1["status"] == "FUNDED"
    assert detail1["milestones"][0]["attempts"] == 1

    # Attempt 2: Pass
    res2 = client.post(
        f"/api/contracts/{contract_id}/milestones/1/submit",
        json={"code": "def sq(n):\n    return n * n\n"},
    )
    assert res2.status_code == 200
    assert res2.json()["passed"] is True
    assert res2.json()["status"] == "PAID"

    # Contract is now COMPLETED
    detail2 = client.get(f"/api/contracts/{contract_id}").json()["contract"]
    assert detail2["status"] == "COMPLETED"


def test_idempotent_repeated_submit(client):
    payload = {
        "title": "Idempotent Contract",
        "buyer_id": "b-idemp",
        "worker_id": "w-idemp",
        "worker_email": "w@test.com",
        "milestones": [
            {
                "title": "Double",
                "amount": "3.50",
                "spec": "dbl",
                "public_tests": "from solution import dbl\ndef test_d(): assert dbl(5) == 10",
            }
        ],
    }
    create_res = client.post("/api/contracts", json=payload)
    contract_id = create_res.json()["id"]

    good_code = "def dbl(x):\n    return x * 2\n"

    # First submit -> PAID
    res1 = client.post(f"/api/contracts/{contract_id}/milestones/1/submit", json={"code": good_code})
    assert res1.status_code == 200
    out1 = res1.json()
    assert out1["passed"] is True
    cap_id_1 = out1["capture_id"]
    payout_id_1 = out1["payout_batch_id"]

    # Second submit of same milestone -> Idempotent response with identical IDs
    res2 = client.post(f"/api/contracts/{contract_id}/milestones/1/submit", json={"code": good_code})
    assert res2.status_code == 200
    out2 = res2.json()
    assert out2["passed"] is True
    assert out2["capture_id"] == cap_id_1
    assert out2["payout_batch_id"] == payout_id_1


def test_hidden_tests_never_appears_in_responses(client):
    secret_test = "def test_secret(): assert False, 'DO_NOT_LEAK'"
    payload = {
        "title": "Confidential Contract",
        "buyer_id": "b-priv",
        "worker_id": "w-priv",
        "worker_email": "w@test.com",
        "milestones": [
            {
                "title": "M1",
                "amount": "1.00",
                "spec": "spec",
                "public_tests": "def test_ok(): pass",
                "hidden_tests": secret_test,
            }
        ],
    }

    # 1. Create response check
    create_res = client.post("/api/contracts", json=payload)
    create_text = create_res.text
    assert "DO_NOT_LEAK" not in create_text
    assert "hidden_tests" not in create_res.json()["milestones"][0]

    contract_id = create_res.json()["id"]

    # 2. Detail response check
    detail_res = client.get(f"/api/contracts/{contract_id}")
    detail_text = detail_res.text
    assert "DO_NOT_LEAK" not in detail_text
    assert "hidden_tests" not in detail_res.json()["contract"]["milestones"][0]

    # 3. List response check
    list_res = client.get("/api/contracts")
    list_text = list_res.text
    assert "DO_NOT_LEAK" not in list_text
