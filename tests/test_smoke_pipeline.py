"""Test wrapper for scripts/smoke_test.py execution against in-memory FastAPI app."""

from scripts.smoke_test import verify_receipt


def test_full_pipeline_smoke(client, auth_org):
    headers = auth_org["headers"]

    # 1. Health check
    h_res = client.get("/healthz")
    assert h_res.status_code == 200

    # 2. Create contract
    create_res = client.post(
        "/v1/contracts",
        json={
            "title": "Smoke Contract Pipeline",
            "environment": "simulated",
            "deadline_days": 7,
            "max_attempts": 3,
            "worker_id": "usr_pipe_worker",
            "worker_email": "worker@pipeline.local",
            "milestones": [
                {
                    "title": "Square Function",
                    "spec": "Function that returns the square of an integer",
                    "amount_cents": 2000,
                    "public_tests": "from solution import sq\ndef test_sq(): assert sq(4) == 16",
                    "hidden_tests": "from solution import sq\ndef test_hidden(): assert sq(-3) == 9",
                    "verifier_type": "python_code",
                }
            ],
        },
        headers=headers,
    )
    assert create_res.status_code == 201, f"Create contract failed: {create_res.text}"
    contract_data = create_res.json()
    contract_id = contract_data["id"]
    assert contract_data["status"] == "FUNDED"

    # 3. Submit
    sub_res = client.post(
        f"/v1/contracts/{contract_id}/milestones/1/submit",
        json={"code": "def sq(n): return n * n"},
        headers=headers,
    )
    assert sub_res.status_code == 200, f"Submit milestone failed: {sub_res.text}"
    assert sub_res.json()["status"] in ("COMPLETED", "PAID")

    # 5. Receipt
    rcpt_res = client.get(f"/v1/contracts/{contract_id}/receipt", headers=headers)
    assert rcpt_res.status_code == 200
    receipt = rcpt_res.json()
    assert verify_receipt(receipt) is True

    # 6. Public share token
    share_res = client.post(f"/v1/contracts/{contract_id}/share", headers=headers)
    assert share_res.status_code == 200
    share_token = share_res.json()["share_token"]
    pub_res = client.get(f"/v1/receipts/{share_token}")
    assert pub_res.status_code == 200
    assert pub_res.json()["contract_id"] == contract_id
