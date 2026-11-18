from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, require_principal
from app.db import get_db
from app.models import ReconciliationRun
from app.services.reconciliation import run_reconciliation

router = APIRouter(prefix="/v1/reconcile", tags=["Reconciliation"])


class ReconcileRequest(BaseModel):
    environment: str = "simulated"


@router.post("")
def trigger_reconciliation(
    payload: Optional[ReconcileRequest] = None,
    principal: Principal = Depends(require_principal("policy:read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Trigger on-demand reconciliation of local contract ledger against PayPal provider.
    Flags discrepancies and returns summary report.
    """
    env = payload.environment if payload else "simulated"
    if env not in ("simulated", "sandbox", "live"):
        raise HTTPException(status_code=400, detail="Invalid environment")

    run_record = run_reconciliation(db, org_id=principal.org_id, environment=env)

    return {
        "run_id": run_record.id,
        "org_id": run_record.org_id,
        "environment": run_record.environment,
        "contracts_checked": run_record.contracts_checked,
        "discrepancies_found": run_record.discrepancies_found,
        "details": run_record.details,
        "run_at": run_record.run_at.isoformat(),
    }


@router.get("/runs")
def list_reconciliation_runs(
    limit: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(require_principal("policy:read")),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List historical reconciliation audit records."""
    runs = db.scalars(
        select(ReconciliationRun)
        .where(ReconciliationRun.org_id == principal.org_id)
        .order_by(ReconciliationRun.run_at.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": r.id,
            "org_id": r.org_id,
            "environment": r.environment,
            "contracts_checked": r.contracts_checked,
            "discrepancies_found": r.discrepancies_found,
            "details": r.details,
            "run_at": r.run_at.isoformat(),
        }
        for r in runs
    ]
