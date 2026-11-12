import threading
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from app.arena import RUNS, SCENARIOS, run_arena

router = APIRouter(prefix="/api/arena", tags=["Red Team Arena"])


class ArenaRunRequest(BaseModel):
    scenario: Optional[str] = None  # None or "all" to run all 6, or scenario key
    sync: bool = True  # Default True for immediate response


@router.get("/scenarios")
def get_scenarios() -> List[Dict[str, Any]]:
    """List all 6 Red Team Arena attack scenarios and expected defensive invariants."""
    return list(SCENARIOS.values())


@router.post("/run")
def start_arena_run(
    payload: Optional[ArenaRunRequest] = None,
    background_tasks: BackgroundTasks = None
) -> Dict[str, Any]:
    """
    Run Red Team Arena attack scenarios.
    If sync=True, executes scenarios synchronously and returns complete results.
    If sync=False, launches background execution and returns run_id.
    """
    target = None
    sync = True
    if payload:
        target = payload.scenario
        sync = payload.sync

    scenarios = [target] if (target and target != "all") else list(SCENARIOS.keys())

    if sync:
        return run_arena(scenarios=scenarios)

    # Background async run
    import uuid
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    RUNS[run_id] = {"run_id": run_id, "status": "running", "scenarios": []}

    def _async_worker():
        run_record = run_arena(scenarios=scenarios)
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
