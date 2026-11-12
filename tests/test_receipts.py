import copy
import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from app.db import get_db
from app.main import app
from app.schemas import cents_to_usd_str


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


def test_receipt_generation_and_valid_signature(client):
    # 1. Create a contract
    create_payload = {
        "title": "Receipt Test Contract",
        "buyer_id": "buyer_rec",
        "worker_id": "worker_rec",
        "worker_email": "worker_secret@corp.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "Milestone 1",
                "amount": "5.00",
                "spec": "def add(a, b): return a + b",
                "public_tests": "from solution import add\ndef test_add(): assert add(2, 3) == 5",
            }
        ],
    }
    create_res = client.post("/api/contracts", json=create_payload)
    assert create_res.status_code == 201
    contract = create_res.json()
    contract_id = contract["id"]
    milestone_id = contract["milestones"][0]["id"]

    # 2. Submit milestone solution to verify & settle
    sub_payload = {"code": "def add(a, b):\n    return a + b\n"}
    sub_res = client.post(
        f"/api/contracts/{contract_id}/milestones/1/submit",
        json=sub_payload,
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "PAID"

    # 3. Retrieve receipt
    rec_res = client.get(f"/api/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()

    assert receipt["contract_id"] == contract_id
    assert receipt["schema_version"] == "1.0"
    assert receipt["total_usd"] == "5.00"
    assert receipt["status"] == "COMPLETED"
    assert "signature" in receipt
    assert receipt["key_id"] in ("configured", "dev-ephemeral")
    assert receipt["event_hash_chain_valid"] is True
    # Email must be masked
    assert receipt["worker_email"] == "w***@corp.com"
    assert "worker_secret" not in receipt["worker_email"]

    # 4. Verify receipt via verify endpoint
    ver_res = client.post("/api/receipts/verify", json=receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is True
    assert ver_data["signature_valid"] is True
    assert ver_data["chain_valid"] is True


def test_receipt_field_tampering_detected(client):
    # Create contract
    c_res = client.post(
        "/api/contracts",
        json={
            "title": "Tamper Test",
            "buyer_id": "b1",
            "worker_id": "w1",
            "worker_email": "w1@corp.com",
            "max_attempts": 1,
            "milestones": [
                {
                    "title": "M1",
                    "amount": "2.00",
                    "spec": "return 1",
                    "public_tests": "def test_1(): pass",
                }
            ],
        },
    )
    contract_id = c_res.json()["id"]

    # Get legitimate receipt
    rec_res = client.get(f"/api/contracts/{contract_id}/receipt")
    receipt = rec_res.json()

    # Tamper with total amount
    tampered_receipt = copy.deepcopy(receipt)
    tampered_receipt["total_usd"] = "9999.00"

    ver_res = client.post("/api/receipts/verify", json=tampered_receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is False
    assert ver_data["signature_valid"] is False


def test_receipt_event_payload_tampering_detected(client):
    # Create contract
    c_res = client.post(
        "/api/contracts",
        json={
            "title": "Event Tamper Test",
            "buyer_id": "b2",
            "worker_id": "w2",
            "worker_email": "w2@corp.com",
            "max_attempts": 1,
            "milestones": [
                {
                    "title": "M1",
                    "amount": "2.00",
                    "spec": "return 1",
                    "public_tests": "def test_1(): pass",
                }
            ],
        },
    )
    contract_id = c_res.json()["id"]

    # Get receipt
    rec_res = client.get(f"/api/contracts/{contract_id}/receipt")
    receipt = rec_res.json()
    assert len(receipt["events"]) > 0

    # Tamper with the first event payload
    tampered_receipt = copy.deepcopy(receipt)
    tampered_receipt["events"][0]["payload"]["title"] = "HACKED_TITLE"

    ver_res = client.post("/api/receipts/verify", json=tampered_receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is False
    assert ver_data["chain_valid"] is False


def test_receipt_no_leak_of_hidden_tests(client):
    secret_canary = "SUPER_SECRET_CANARY_VALUE_987654"
    hidden_suite = f"def test_canary(): assert check() == '{secret_canary}'"

    c_res = client.post(
        "/api/contracts",
        json={
            "title": "Hidden Leak Test",
            "buyer_id": "b3",
            "worker_id": "w3",
            "worker_email": "w3@corp.com",
            "max_attempts": 1,
            "milestones": [
                {
                    "title": "M1",
                    "amount": "2.00",
                    "spec": "def check(): return '...' ",
                    "public_tests": "def test_pub(): pass",
                    "hidden_tests": hidden_suite,
                }
            ],
        },
    )
    assert c_res.status_code == 201
    contract_id = c_res.json()["id"]

    rec_res = client.get(f"/api/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()
    receipt_str = json.dumps(receipt)

    # Secret canary must never appear anywhere in the receipt
    assert secret_canary not in receipt_str

    # Commitment must be present and match sha256 of milestone hidden test commitments
    h1 = hashlib.sha256(hidden_suite.encode("utf-8")).hexdigest()
    expected_commitment = hashlib.sha256(h1.encode("utf-8")).hexdigest()
    assert receipt["hidden_commitment"] == expected_commitment
