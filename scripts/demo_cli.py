#!/usr/bin/env python3
"""
PayLap Multi-Contract Demonstration CLI.

Runs end-to-end demonstrations against an active PayLap server:
- Contract A: 2 milestones with valid exponential backoff solutions -> both PAID -> COMPLETED.
- Contract B: 1 milestone with buggy solution -> REJECTED -> attempts exhausted -> VOIDED.
- Table summary of results.
- Cryptographic ledger verification.

Usage:
  python scripts/demo_cli.py [--url http://localhost:8000]
"""

import argparse
import sys
import time
import httpx


def print_banner(msg: str):
    print("\n" + "=" * 70)
    print(f" {msg}")
    print("=" * 70)


def print_sub_banner(msg: str):
    print(f"\n--- {msg} ---")


def run_demo(base_url: str):
    base_url = base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=30.0)

    print_banner("PayLap AI Agent Escrow - Demonstration CLI")

    # Step 0: Check Health
    try:
        health_res = client.get("/api/health")
        if health_res.status_code != 200:
            print(f"[!] Server returned HTTP {health_res.status_code}: {health_res.text}")
            sys.exit(1)
        health = health_res.json()
    except Exception as exc:
        print(f"[!] Could not connect to PayLap API at {base_url}: {exc}")
        print("Please start the API server first: uvicorn app.main:app --reload")
        sys.exit(1)

    mode = health.get("mode")
    payout_mode = health.get("payout_mode")
    print(f"Server Target       : {base_url}")
    print(f"Operating Mode      : {mode.upper()} (payout_mode: {payout_mode})")
    print(f"PayPal Configured   : {health.get('paypal_configured')}")
    print(f"Ledger Chain Status : {'VALID' if health.get('ledger_chain_valid') else 'INVALID'}")

    results_table = []

    # =========================================================================
    # CONTRACT A: Success Scenario (2 Milestones -> PAID -> COMPLETED)
    # =========================================================================
    print_banner("Contract A: 2 Milestones | Exponential Backoff (Success Flow)")

    payload_a = {
        "title": "Exponential Backoff Agent Service",
        "buyer_id": "buyer-agent-alpha",
        "worker_id": "worker-agent-beta",
        "worker_email": "worker-beta@example.com",
        "max_attempts": 2,
        "milestones": [
            {
                "title": "Core Exponential Backoff Calculation",
                "amount": "2.50",
                "spec": "calculate_backoff(attempt: int, base: float = 1.0, max_backoff: float = 30.0) -> float",
                "public_tests": """from solution import calculate_backoff

def test_backoff_zero():
    assert calculate_backoff(0) == 1.0

def test_backoff_exponential():
    assert calculate_backoff(1) == 2.0
    assert calculate_backoff(2) == 4.0
    assert calculate_backoff(3) == 8.0

def test_backoff_capped():
    assert calculate_backoff(10) == 30.0
""",
                "hidden_tests": "def test_hidden(): pass",
            },
            {
                "title": "Backoff Jitter Modifier",
                "amount": "2.50",
                "spec": "apply_jitter(backoff: float, jitter_ratio: float = 0.1) -> float",
                "public_tests": """from solution import apply_jitter

def test_jitter_zero():
    assert apply_jitter(10.0, 0.0) == 10.0

def test_jitter_positive():
    assert apply_jitter(10.0, 0.2) == 11.0
""",
            },
        ],
    }

    create_a = client.post("/api/contracts", json=payload_a).json()
    contract_a_id = create_a["id"]
    print(f"Contract A Created   : {contract_a_id}")
    print(f"Status               : {create_a['status']}")
    print(f"Budget               : ${create_a['total_usd']} ({len(create_a['milestones'])} milestones)")

    # If in live mode and awaiting funding, prompt for approval
    if create_a["status"] == "AWAITING_FUNDING":
        print(f"\n[ACTION REQUIRED] Please open approval URL:\n{create_a['approve_url']}")
        input("Press [Enter] after completing PayPal approval in browser...")

    # Milestone 1 submission
    print_sub_banner("Submitting Milestone 1: Core Backoff")
    code_m1 = """
def calculate_backoff(attempt: int, base: float = 1.0, max_backoff: float = 30.0) -> float:
    return min(max_backoff, base * (2 ** attempt))
"""
    m1_res = client.post(f"/api/contracts/{contract_a_id}/milestones/1/submit", json={"code": code_m1}).json()
    print(f"Result               : Passed={m1_res['passed']} | Status={m1_res['status']}")
    print(f"Capture ID           : {m1_res.get('capture_id')}")
    print(f"Payout Batch ID      : {m1_res.get('payout_batch_id')}")
    print(f"Simulated            : {m1_res.get('simulated')}")

    # Milestone 2 submission (final milestone)
    print_sub_banner("Submitting Milestone 2: Jitter Modifier (Final Milestone)")
    code_m2 = """
def apply_jitter(backoff: float, jitter_ratio: float = 0.1) -> float:
    return backoff + (backoff * jitter_ratio * 0.5)
"""
    m2_res = client.post(f"/api/contracts/{contract_a_id}/milestones/2/submit", json={"code": code_m2}).json()
    print(f"Result               : Passed={m2_res['passed']} | Status={m2_res['status']}")
    print(f"Capture ID           : {m2_res.get('capture_id')}")
    print(f"Payout Batch ID      : {m2_res.get('payout_batch_id')}")

    # Verify final Contract A status
    final_a = client.get(f"/api/contracts/{contract_a_id}").json()["contract"]
    print(f"Final Contract State : \033[92m{final_a['status']}\033[0m")
    results_table.append({
        "contract_id": contract_a_id,
        "title": final_a["title"],
        "total_usd": f"${final_a['total_usd']}",
        "milestones": f"{sum(1 for m in final_a['milestones'] if m['status'] == 'PAID')}/{len(final_a['milestones'])} PAID",
        "status": final_a["status"]
    })

    # =========================================================================
    # CONTRACT B: Failure Scenario (1 Milestone -> Buggy -> REJECTED -> VOIDED)
    # =========================================================================
    print_banner("Contract B: 1 Milestone | Deliberate Bug (Rejection & Void Flow)")

    payload_b = {
        "title": "Strict Array Sorter",
        "buyer_id": "buyer-agent-alpha",
        "worker_id": "worker-agent-gamma",
        "worker_email": "worker-gamma@example.com",
        "max_attempts": 1,
        "milestones": [
            {
                "title": "Sort Integer Array",
                "amount": "5.00",
                "spec": "sort_ints(arr: list[int]) -> list[int]",
                "public_tests": """from solution import sort_ints

def test_sort_simple():
    assert sort_ints([3, 1, 2]) == [1, 2, 3]

def test_sort_already_sorted():
    assert sort_ints([10, 20]) == [10, 20]
""",
            }
        ],
    }

    create_b = client.post("/api/contracts", json=payload_b).json()
    contract_b_id = create_b["id"]
    print(f"Contract B Created   : {contract_b_id}")
    print(f"Status               : {create_b['status']}")
    print(f"Budget               : ${create_b['total_usd']}")

    if create_b["status"] == "AWAITING_FUNDING":
        print(f"\n[ACTION REQUIRED] Please open approval URL:\n{create_b['approve_url']}")
        input("Press [Enter] after completing PayPal approval in browser...")

    print_sub_banner("Submitting Milestone 1: Deliberately Buggy Code")
    buggy_code = """
def sort_ints(arr):
    # Deliberate failure: does not sort
    return arr
"""
    m_bug_res = client.post(f"/api/contracts/{contract_b_id}/milestones/1/submit", json={"code": buggy_code}).json()
    print(f"Result               : Passed={m_bug_res['passed']} | Status={m_bug_res['status']}")
    print(f"Sandbox Summary      : {m_bug_res.get('error')}")

    final_b = client.get(f"/api/contracts/{contract_b_id}").json()["contract"]
    print(f"Final Contract State : \033[93m{final_b['status']}\033[0m (Attempts exhausted -> Hold voided)")
    results_table.append({
        "contract_id": contract_b_id,
        "title": final_b["title"],
        "total_usd": f"${final_b['total_usd']}",
        "milestones": f"{sum(1 for m in final_b['milestones'] if m['status'] == 'PAID')}/{len(final_b['milestones'])} PAID",
        "status": final_b["status"]
    })

    # =========================================================================
    # SUMMARY TABLE & CRYPTOGRAPHIC LEDGER VERIFICATION
    # =========================================================================
    print_banner("Execution Summary Table")
    header_fmt = "{:<16} {:<32} {:<10} {:<16} {:<12}"
    print(header_fmt.format("Contract ID", "Title", "Amount", "Milestones", "Status"))
    print("-" * 88)
    for row in results_table:
        print(header_fmt.format(
            row["contract_id"],
            row["title"][:30],
            row["total_usd"],
            row["milestones"],
            row["status"]
        ))

    print_banner("Cryptographic Ledger Integrity Verification")
    ledger_res = client.get("/api/ledger/verify").json()
    if ledger_res.get("valid"):
        print("\033[92m[PASS] Cryptographic Event Hash Chain is 100% INTACT.\033[0m")
        print("All events are sequentially chained and un-tampered.")
    else:
        print(f"\033[91m[FAIL] Ledger broken link detected at seq {ledger_res.get('broken_seq')}: {ledger_res.get('error')}\033[0m")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PayLap Demonstration CLI")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of running PayLap instance")
    args = parser.parse_args()
    run_demo(args.url)
