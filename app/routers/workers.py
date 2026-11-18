from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.auth import Principal, require_principal
from app.db import get_db
from app.models import Contract, Event, Milestone
from app.services.policy import mask_email
from app.services.reputation import compute_worker_reputation, list_worker_reputations

router = APIRouter(prefix="/v1/workers", tags=["Workers"])


@router.get("", response_model=List[Dict[str, Any]])
def get_workers(
    principal: Principal = Depends(require_principal("workers:read")),
    db: Session = Depends(get_db),
):
    """List reputation scores and statistics for all workers."""
    return list_worker_reputations(db)


@router.get("/{worker_id}/stats")
def get_worker_stats(
    worker_id: str,
    principal: Principal = Depends(require_principal("workers:read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get detailed statistics for a worker:
    total contracts, completion rate, avg attempts per milestone, dispute rate, masked email.
    """
    contracts = db.scalars(
        select(Contract).where(Contract.worker_id == worker_id)
    ).all()

    if not contracts:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found")

    total_contracts = len(contracts)
    completed_contracts = sum(1 for c in contracts if c.status == "COMPLETED")
    voided_contracts = sum(1 for c in contracts if c.status == "VOIDED")
    completion_rate = round((completed_contracts / total_contracts) * 100.0, 2) if total_contracts > 0 else 0.0

    raw_email = contracts[0].worker_email if contracts[0].worker_email else ""
    worker_masked_email = mask_email(raw_email)

    contract_ids = [c.id for c in contracts]
    milestones = db.scalars(
        select(Milestone).where(Milestone.contract_id.in_(contract_ids))
    ).all()

    total_milestones = len(milestones)
    total_attempts = sum(m.attempts_count for m in milestones)
    avg_attempts = round(total_attempts / total_milestones, 2) if total_milestones > 0 else 0.0

    # Dispute / veto events
    events = db.scalars(
        select(Event).where(
            Event.contract_id.in_(contract_ids),
            Event.event_type.in_(["ARBITER_VETO", "DISCREPANCY_DETECTED", "CONTRADICTION_DETECTED"]),
        )
    ).all()
    disputes_count = len(events)
    dispute_rate = round((disputes_count / total_contracts) * 100.0, 2) if total_contracts > 0 else 0.0

    rep = compute_worker_reputation(db, worker_id)

    return {
        "worker_id": worker_id,
        "masked_email": worker_masked_email,
        "total_contracts": total_contracts,
        "completed_contracts": completed_contracts,
        "voided_contracts": voided_contracts,
        "completion_rate": completion_rate,
        "avg_attempts_per_milestone": avg_attempts,
        "dispute_rate": dispute_rate,
        "reputation_score": rep.get("score", 0),
    }


@router.get("/{worker_id}")
def get_worker(
    worker_id: str,
    principal: Principal = Depends(require_principal("workers:read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get reputation details and security penalty breakdown for a specific worker."""
    return compute_worker_reputation(db, worker_id)
