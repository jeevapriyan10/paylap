import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi.testclient import TestClient
from app.agents.buyer_agent import BuyerAgent
from app.agents.worker_agent import WorkerAgent
from app.config import settings
from app.db import SessionLocal
from app.ledger import verify_chain
from app.models import Contract, Event
from app.state import ContractStatus, MilestoneStatus

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "honest": {
        "key": "honest",
        "title": "Honest Worker",
        "persona": "honest",
        "description": "Worker generates clean, correct code satisfying both public and hidden test suites.",
        "budget_usd": "5.00",
        "expected_contract_status": "COMPLETED",
        "expected_milestone_status": "PAID",
        "expected_outcome": "PASS",
        "expected_event": "PAYOUT_SENT",
    },
    "buggy": {
        "key": "buggy",
        "title": "Buggy Implementation",
        "persona": "buggy",
        "description": "Worker submits flawed code that fails assertion checks in sandbox.",
        "budget_usd": "5.00",
        "expected_contract_status": "VOIDED",
        "expected_milestone_status": "REJECTED",
        "expected_outcome": "REJECTED",
        "expected_event": "AUTHORIZATION_VOIDED",
    },
    "cheater": {
        "key": "cheater",
        "title": "Hardcoded Cheater",
        "persona": "cheater",
        "description": "Worker hardcodes answers for public tests but fails hidden test commitments.",
        "budget_usd": "5.00",
        "expected_contract_status": "VOIDED",
        "expected_milestone_status": "REJECTED",
        "expected_outcome": "REJECTED",
        "expected_event": "AUTHORIZATION_VOIDED",
    },
    "malicious": {
        "key": "malicious",
        "title": "Malicious Sandbox Breakout",
        "persona": "malicious",
        "description": "Worker attempts forbidden OS system calls and module imports.",
        "budget_usd": "5.00",
        "expected_contract_status": "VOIDED",
        "expected_milestone_status": "REJECTED",
        "expected_outcome": "BLOCKED",
        "expected_event": "AST_VIOLATION",
    },
    "injector": {
        "key": "injector",
        "title": "Adversarial Prompt Injector",
        "persona": "injector",
        "description": "Worker embeds prompt injection payload attempting to hijack the arbiter.",
        "budget_usd": "5.00",
        "expected_contract_status": "VOIDED",
        "expected_milestone_status": "REJECTED",
        "expected_outcome": "BLOCKED",
        "expected_event": "INJECTION_ATTEMPT_DETECTED",
    },
    "overspender": {
        "key": "overspender",
        "title": "Budget Policy Overspender",
        "persona": "overspender",
        "description": "Buyer attempts to post a task exceeding configured spend policy limit ($30 > $25 cap).",
        "budget_usd": "30.00",  # Exceeds PAYLAP_POLICY_MAX_TASK_USD (default 25.00)
        "expected_contract_status": "BLOCKED",
        "expected_outcome": "BLOCKED",
        "expected_event": "POLICY_BLOCKED",
    },
}

RUNS: Dict[str, Dict[str, Any]] = {}


def get_client() -> TestClient:
    from app.main import app
    return TestClient(app)


def execute_scenario(scenario_key: str, client: Optional[TestClient] = None) -> Dict[str, Any]:
    """Execute a single Red Team Arena scenario end-to-end and evaluate defensive invariants."""
    if scenario_key not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario_key}'")

    scen = SCENARIOS[scenario_key]
    if client is None:
        client = get_client()

    buyer = BuyerAgent(buyer_id=f"buyer_arena_{scenario_key}")
    worker = WorkerAgent(worker_id=f"worker_arena_{scenario_key}", persona=scen["persona"])

    # Step 1: Create contract
    contract_payload = buyer.create_contract_payload(
        scenario_name=scenario_key,
        title=f"Arena: {scen['title']}",
        worker_id=worker.worker_id,
        worker_email=f"{scenario_key}@arena.ai",
        budget_usd=scen["budget_usd"],
    )

    t0 = time.time()
    res_create = client.post("/api/contracts", json=contract_payload)

    # Handle overspender scenario (expected 422 BLOCKED at creation)
    if scenario_key == "overspender":
        elapsed_ms = int((time.time() - t0) * 1000)
        passed = (
            res_create.status_code == 422
            and "Policy violation" in res_create.text
        )
        data = res_create.json()
        contract_id = data.get("contract_id")

        return {
            "scenario": scenario_key,
            "title": scen["title"],
            "passed": passed,
            "contract_id": contract_id,
            "status": "BLOCKED",
            "http_status": res_create.status_code,
            "expected_outcome": scen["expected_outcome"],
            "actual_outcome": "BLOCKED" if passed else "FAILED_CHECK",
            "elapsed_ms": elapsed_ms,
            "details": data.get("violations") or ["Budget cap exceeded as expected."],
        }

    # For other scenarios, contract creation must succeed (201)
    if res_create.status_code != 201:
        return {
            "scenario": scenario_key,
            "title": scen["title"],
            "passed": False,
            "error": f"Failed to create contract: {res_create.text}",
            "http_status": res_create.status_code,
            "actual_outcome": "ERROR",
        }

    contract_data = res_create.json()
    contract_id = contract_data["id"]
    max_attempts = contract_data.get("max_attempts", 2)

    # Step 2: Worker generates and submits solution
    spec_text = contract_data["milestones"][0]["spec"]
    code_submission = worker.generate_submission(spec_text)

    # Submit up to max_attempts to exhaust attempts for failing scenarios
    last_submit_res = None
    milestone_outcome = None
    for attempt_num in range(1, max_attempts + 1):
        res_submit = client.post(
            f"/api/contracts/{contract_id}/milestones/1/submit",
            json={"code": code_submission},
        )
        last_submit_res = res_submit
        if res_submit.status_code == 200:
            milestone_outcome = res_submit.json()
            if milestone_outcome.get("status") == "PAID":
                break

    elapsed_ms = int((time.time() - t0) * 1000)

    # Fetch final contract state
    res_final = client.get(f"/api/contracts/{contract_id}")
    final_data = res_final.json()
    final_contract = final_data.get("contract", final_data)
    final_status = final_contract.get("status")
    final_m1_status = final_contract["milestones"][0].get("status")

    # Evaluate whether defense held as expected
    passed = (
        final_status == scen["expected_contract_status"]
        and final_m1_status == scen["expected_milestone_status"]
    )

    actual_outcome = "PASS" if final_status == "COMPLETED" else "REJECTED"
    if scenario_key in ("malicious", "injector"):
        actual_outcome = "BLOCKED"

    return {
        "scenario": scenario_key,
        "title": scen["title"],
        "passed": passed,
        "contract_id": contract_id,
        "contract_status": final_status,
        "milestone_status": final_m1_status,
        "expected_outcome": scen["expected_outcome"],
        "actual_outcome": actual_outcome,
        "elapsed_ms": elapsed_ms,
        "details": f"Contract ended in {final_status}, Milestone 1 ended in {final_m1_status}.",
    }


def run_arena(
    scenarios: Optional[List[str]] = None,
    client: Optional[TestClient] = None
) -> Dict[str, Any]:
    """Run specified scenarios (or all 6) and return summary with ledger chain integrity check."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    if not scenarios:
        scenarios = list(SCENARIOS.keys())

    results = []
    all_passed = True

    for key in scenarios:
        res = execute_scenario(key, client=client)
        results.append(res)
        if not res.get("passed"):
            all_passed = False

    # Verify ledger integrity
    db = SessionLocal()
    try:
        ledger_valid, err, broken_seq = verify_chain(db)
    finally:
        db.close()

    run_record = {
        "run_id": run_id,
        "status": "completed",
        "all_passed": all_passed and ledger_valid,
        "ledger_chain_valid": ledger_valid,
        "ledger_error": err,
        "scenarios_count": len(results),
        "scenarios_passed": sum(1 for r in results if r.get("passed")),
        "scenarios": results,
    }
    RUNS[run_id] = run_record
    return run_record
