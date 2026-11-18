import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.testclient import TestClient

from app.arena import RUNS, SCENARIOS, run_arena
from app.auth import Principal, get_current_principal

router = APIRouter(prefix="/v1/arena", tags=["Red Team Arena"])


class ArenaRunRequest(BaseModel):
    scenario: Optional[str] = None  # None or "all" to run all 6, or scenario key
    sync: bool = True  # Default True for immediate response


@router.get("/scenarios")
def get_scenarios() -> List[Dict[str, Any]]:
    """List all 6 Red Team Arena attack scenarios and expected defensive invariants."""
    return list(SCENARIOS.values())


@router.post("/run")
def start_arena_run(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: Optional[ArenaRunRequest] = None,
    principal: Principal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """
    Run Red Team Arena attack scenarios.
    If sync=True, executes scenarios synchronously and returns complete results.
    If sync=False, launches background execution and returns run_id.
    """
    principal.require_scope("playground:run")

    target = None
    sync = True
    if payload:
        target = payload.scenario
        sync = payload.sync

    scenarios = [target] if (target and target != "all") else list(SCENARIOS.keys())

    auth_header = request.headers.get("authorization")
    client_headers = {"Authorization": auth_header} if auth_header else {}
    runner_client = TestClient(request.app, headers=client_headers)

    if sync:
        return run_arena(scenarios=scenarios, client=runner_client)

    # Background async run
    import uuid

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    RUNS[run_id] = {"run_id": run_id, "status": "running", "scenarios": []}

    def _async_worker():
        run_record = run_arena(scenarios=scenarios, client=runner_client)
        RUNS[run_id] = run_record

    thread = threading.Thread(target=_async_worker, daemon=True)
    thread.start()

    return {"run_id": run_id, "status": "running"}


@router.get("/runs/{run_id}")
def get_arena_run(run_id: str) -> Dict[str, Any]:
    """Get status, results, and ledger integrity for a specific arena run."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Arena run '{run_id}' not found.")
    return run
