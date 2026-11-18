from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Principal, require_principal
from app.db import get_db
from app.models import Contract, Event, Milestone
from app.state import ContractStatus, MilestoneStatus

router = APIRouter(prefix="/v1/org/stats", tags=["Organization Statistics"])


@router.get("")
def get_org_stats(
    principal: Principal = Depends(require_principal("contracts:read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get aggregated platform statistics for the current organization:
    total spend, active holds, completed count, voided count, and arbiter veto count.
    """
    org_id = principal.org_id

    # Total spend: sum of paid milestones in this org
    total_spend_cents = (
        db.scalar(
            select(func.coalesce(func.sum(Milestone.amount_cents), 0)).where(
                Milestone.org_id == org_id,
                Milestone.status == MilestoneStatus.PAID.value,
            )
        )
        or 0
    )

    # Active holds: sum of contract total_cents where status is FUNDED
    active_holds_cents = (
        db.scalar(
            select(func.coalesce(func.sum(Contract.total_cents), 0)).where(
                Contract.org_id == org_id,
                Contract.status == ContractStatus.FUNDED.value,
            )
        )
        or 0
    )

    # Contract status breakdown
    contracts = db.scalars(select(Contract).where(Contract.org_id == org_id)).all()

    total_contracts = len(contracts)
    completed_count = sum(1 for c in contracts if c.status == ContractStatus.COMPLETED.value)
    voided_count = sum(1 for c in contracts if c.status in (ContractStatus.VOIDED.value, ContractStatus.EXPIRED.value))
    needs_attention_count = sum(1 for c in contracts if c.needs_attention)

    # Arbiter veto events count
    arbiter_veto_count = (
        db.scalar(
            select(func.count(Event.id)).where(
                Event.org_id == org_id,
                Event.event_type == "ARBITER_VETO",
            )
        )
        or 0
    )

    return {
        "org_id": org_id,
        "total_spend_cents": total_spend_cents,
        "active_holds_cents": active_holds_cents,
        "total_contracts": total_contracts,
        "completed_count": completed_count,
        "voided_count": voided_count,
        "needs_attention_count": needs_attention_count,
        "arbiter_veto_count": arbiter_veto_count,
    }
