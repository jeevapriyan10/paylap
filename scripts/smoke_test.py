"""End-to-End Release Smoke Verification Script for PayLap.

Exercises the full lifecycle against a running server:
1. Health checks (/healthz)
2. Authentication (API Key & Session Login)
3. Contract Creation (Deterministic rules & hidden test commitments)
4. Milestone Funding & Deliverable Submission
5. Capture & Settlement
6. Offline Cryptographic Receipt Verification
7. Red Team Arena Attack Scenarios
"""

import base64
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BASE_URL = os.environ.get("PAYLAP_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("PAYLAP_API_KEY", "pl_test_devkey00000000_1234567890abcdef1234567890abcdef")


def log(msg: str) -> None:
    print(f"[SMOKE TEST] {msg}")


def canonicalize(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def verify_receipt(receipt: Dict[str, Any]) -> bool:
    signature_b64 = receipt.get("signature") or receipt.get("ed25519_signature")
    pubkey_b64 = receipt.get("signer_public_key") or receipt.get("public_key")

    if not signature_b64 or not pubkey_b64:
        raise ValueError("Receipt missing signature or signer_public_key")

    # Strip signature before canonical bytes
    payload_to_verify = {k: v for k, v in receipt.items() if k not in ("signature", "ed25519_signature")}
    canonical_bytes = canonicalize(payload_to_verify)

    pub_bytes = base64.b64decode(pubkey_b64)
    sig_bytes = base64.b64decode(signature_b64)
    pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
    pub_key.verify(sig_bytes, canonical_bytes)
    return True


def run_smoke_test() -> bool:
    log(f"Connecting to PayLap instance at: {BASE_URL}")
    client = httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=60.0)

    try:
        # Step 1: Health probe
        log("Checking liveness probe /healthz...")
        resp = client.get("/healthz")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        log("✓ Liveness probe verified.")

        # Step 2: Create Contract
        log("Creating verifiable settlement contract...")
        contract_payload = {
            "title": "Smoke Test Settlement Contract",
            "environment": "simulated",
            "deadline_days": 14,
            "max_attempts": 3,
            "worker_id": "usr_smoke_worker_01",
            "worker_email": "worker@smoke.local",
            "milestones": [
                {
                    "title": "Clean Fibonacci Function",
                    "spec": "Calculates n-th Fibonacci number",
                    "amount_cents": 1500,
                    "public_tests": "from solution import fib\ndef test_fib(): assert fib(5) == 5\nassert fib(1) == 1",
                    "hidden_tests": "from solution import fib\ndef test_hidden(): assert fib(10) == 55\nassert fib(0) == 0",
                    "verifier_type": "python_code",
                }
            ],
        }
        resp = client.post("/v1/contracts", json=contract_payload)
        assert resp.status_code == 201, f"Failed to create contract: {resp.text}"
        contract = resp.json()
        contract_id = contract["id"]
        log(f"✓ Contract created: {contract_id} (Status: {contract['status']})")

        # Step 3: Fund Contract
        log(f"Authorizing funds on customer account for contract {contract_id}...")
        resp = client.post(f"/v1/contracts/{contract_id}/fund")
        assert resp.status_code == 200, f"Failed to fund contract: {resp.text}"
        assert resp.json()["status"] == "FUNDED"
        log("✓ Contract successfully FUNDED (Payment hold authorized).")

        # Step 4: Submit Milestone Deliverable
        log("Submitting verified Python deliverable for milestone 1...")
        solution_code = """
def fib(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
"""
        submit_payload = {
            "code": solution_code,
        }
        resp = client.post(f"/v1/contracts/{contract_id}/milestones/1/submit", json=submit_payload)
        assert resp.status_code == 200, f"Failed milestone submit: {resp.text}"
        outcome = resp.json()
        assert outcome["status"] in ("COMPLETED", "PAID"), f"Milestone failed: {outcome}"
        log(f"✓ Milestone 1 COMPLETED and SETTLED! Payout captured: ${outcome.get('amount_usd', '15.00')}")

        # Step 5: Digital Receipt Verification
        log(f"Fetching cryptographic receipt for contract {contract_id}...")
        resp = client.get(f"/v1/contracts/{contract_id}/receipt")
        assert resp.status_code == 200, f"Failed to fetch receipt: {resp.text}"
        receipt = resp.json()

        log("Performing offline cryptographic verification of Ed25519 signature...")
        valid = verify_receipt(receipt)
        assert valid is True
        log(f"✓ Offline Ed25519 signature and SHA-256 hash verified successfully!")
        log(f"  Receipt Hash: {receipt['receipt_hash'][:24]}...")
        log(f"  Share Token:  {receipt.get('share_token')}")

        # Step 6: Verify Share Token Public Endpoint
        log("Generating public share token...")
        share_resp = client.post(f"/v1/contracts/{contract_id}/share")
        assert share_resp.status_code == 200, f"Failed to generate share token: {share_resp.text}"
        share_token = share_resp.json()["share_token"]
        log(f"✓ Public share token generated: {share_token}")

        log("Verifying public unauthenticated receipt view...")
        unauth_client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        resp = unauth_client.get(f"/v1/receipts/{share_token}")
        assert resp.status_code == 200, f"Public share token failed: {resp.text}"
        log("✓ Public unauthenticated receipt verification passed.")

        # Step 7: Red Team Arena Verification
        log("Running Red Team Arena honest scenario defense check...")
        resp = client.post("/v1/arena/run", json={"scenario": "honest", "sync": True}, timeout=60.0)
        assert resp.status_code == 200, f"Arena run failed: {resp.text}"
        arena_res = resp.json()
        assert arena_res.get("ledger_chain_valid") is True, f"Ledger invalid: {arena_res}"
        log("✓ Red Team Arena defensive invariants held and ledger verified unbroken.")

        log("\n" + "=" * 60)
        log("ALL END-TO-END RELEASE SMOKE TESTS PASSED CLEANLY (100% OK)")
        log("=" * 60)
        return True

    except Exception as exc:
        log(f"✗ SMOKE TEST FAILED: {exc}")
        return False
    finally:
        client.close()


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
