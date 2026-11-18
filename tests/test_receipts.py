import copy
import hashlib
import json


def test_receipt_generation_and_valid_signature(client):
    # 1. Create a contract with hidden_tests to satisfy default policy
    create_payload = {
        "title": "Receipt Test Contract",
        "worker_id": "worker_rec",
        "worker_email": "worker_secret@corp.com",
        "environment": "simulated",
        "milestones": [
            {
                "title": "Milestone 1",
                "amount": "5.00",
                "spec": "def add(a, b): return a + b",
                "public_tests": "from solution import add\ndef test_add(): assert add(2, 3) == 5",
                "hidden_tests": "from solution import add\ndef test_h(): assert add(1, 1) == 2",
            }
        ],
    }
    create_res = client.post("/v1/contracts", json=create_payload)
    assert create_res.status_code == 201
    contract = create_res.json()
    contract_id = contract["id"]

    # 2. Submit milestone solution to verify & settle
    sub_payload = {"code": "def add(a, b):\n    return a + b\n"}
    sub_res = client.post(
        f"/v1/contracts/{contract_id}/milestones/1/submit",
        json=sub_payload,
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "PAID"

    # 3. Retrieve receipt
    rec_res = client.get(f"/v1/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()

    assert receipt["contract_id"] == contract_id
    assert receipt["schema_version"] in ("1.0", "2.0")
    assert receipt["total_usd"] == "5.00"
    assert receipt["status"] == "COMPLETED"
    assert "signature" in receipt
    assert "signer_public_key" in receipt or "key_id" in receipt

    # Email must be masked
    assert receipt["worker_email"] == "w***@corp.com"
    assert "worker_secret" not in receipt["worker_email"]

    # 4. Verify receipt via verify endpoint
    ver_res = client.post("/v1/system/receipts/verify", json=receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is True


def test_receipt_field_tampering_detected(client):
    # Create contract
    c_res = client.post(
        "/v1/contracts",
        json={
            "title": "Tamper Test",
            "worker_id": "w1",
            "worker_email": "w1@corp.com",
            "environment": "simulated",
            "milestones": [
                {
                    "title": "M1",
                    "amount": "2.00",
                    "spec": "return 1",
                    "public_tests": "def test_1(): pass",
                    "hidden_tests": "def test_h(): pass",
                }
            ],
        },
    )
    assert c_res.status_code == 201
    contract_id = c_res.json()["id"]

    # Get legitimate receipt
    rec_res = client.get(f"/v1/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()

    # Tamper with total amount
    tampered_receipt = copy.deepcopy(receipt)
    tampered_receipt["total_usd"] = "9999.00"

    ver_res = client.post("/v1/system/receipts/verify", json=tampered_receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is False


def test_receipt_event_payload_tampering_detected(client):
    # Create contract
    c_res = client.post(
        "/v1/contracts",
        json={
            "title": "Event Tamper Test",
            "worker_id": "w2",
            "worker_email": "w2@corp.com",
            "environment": "simulated",
            "milestones": [
                {
                    "title": "M1",
                    "amount": "2.00",
                    "spec": "return 1",
                    "public_tests": "def test_1(): pass",
                    "hidden_tests": "def test_h(): pass",
                }
            ],
        },
    )
    assert c_res.status_code == 201
    contract_id = c_res.json()["id"]

    # Get receipt
    rec_res = client.get(f"/v1/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()
    assert len(receipt["events"]) > 0

    # Tamper with the first event payload
    tampered_receipt = copy.deepcopy(receipt)
    tampered_receipt["events"][0]["payload"]["title"] = "HACKED_TITLE"

    ver_res = client.post("/v1/system/receipts/verify", json=tampered_receipt)
    assert ver_res.status_code == 200
    ver_data = ver_res.json()
    assert ver_data["valid"] is False


def test_receipt_no_leak_of_hidden_tests(client):
    secret_canary = "SUPER_SECRET_CANARY_VALUE_987654"
    hidden_suite = f"def test_canary(): assert check() == '{secret_canary}'"

    c_res = client.post(
        "/v1/contracts",
        json={
            "title": "Hidden Leak Test",
            "worker_id": "w3",
            "worker_email": "w3@corp.com",
            "environment": "simulated",
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

    rec_res = client.get(f"/v1/contracts/{contract_id}/receipt")
    assert rec_res.status_code == 200
    receipt = rec_res.json()
    receipt_str = json.dumps(receipt)

    # Secret canary must never appear anywhere in the receipt
    assert secret_canary not in receipt_str

    # Commitment must be present in hidden_test_commitments
    h1 = hashlib.sha256(hidden_suite.encode("utf-8")).hexdigest()
    commitments = receipt.get("hidden_test_commitments") or [
        m.get("hidden_commitment_hash") for m in receipt.get("milestones", [])
    ]
    assert h1 in commitments
