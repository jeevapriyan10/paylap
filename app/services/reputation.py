from typing import Any, Dict, List
from sqlalchemy.orm import Session
from app.models import Contract, Event, Milestone
from app.schemas import cents_to_usd_str
from app.state import MilestoneStatus


def compute_worker_reputation(db: Session, worker_id: str) -> Dict[str, Any]:
    """
    Computes reputation score (0-100) and historical performance metrics for a worker agent.
    Formula:
      base_pass_rate = (paid_milestones / attempted_milestones) * 100
      penalties = (injection_attempts * 30) + (ast_policy_violations * 15) + (arbiter_vetoes * 10)
      volume_dampener = min(1.0, attempted_milestones / 5)
      score = clamp(int(round((base_pass_rate - penalties) * volume_dampener)), 0, 100)
    """
    contracts = db.query(Contract).filter(Contract.worker_id == worker_id).all()
    contract_ids = [c.id for c in contracts]

    contracts_total = len(contracts)
    contracts_completed = sum(1 for c in contracts if c.status == "COMPLETED")

    if not contract_ids:
        return {
            "worker_id": worker_id,
            "score": 0,
            "attempted_milestones": 0,
            "paid_milestones": 0,
            "base_pass_rate": 0.0,
            "volume_dampener": 0.0,
            "penalties": {
                "injection_attempts": 0,
                "ast_policy_violations": 0,
                "arbiter_vetoes": 0,
                "total_penalty_points": 0.0,
            },
            "contracts_count": 0,
            "contracts_completed": 0,
            "total_earned_usd": "0.00",
        }

    # Query milestones
    milestones = (
        db.query(Milestone)
        .filter(Milestone.contract_id.in_(contract_ids))
        .all()
    )

    attempted_milestones = sum(1 for m in milestones if m.attempts > 0 or m.status != MilestoneStatus.PENDING.value)
    paid_milestones = sum(1 for m in milestones if m.status == MilestoneStatus.PAID.value)
    total_earned_cents = sum(m.amount_cents for m in milestones if m.status == MilestoneStatus.PAID.value)

    # Query penalty events
    events = (
        db.query(Event)
        .filter(Event.contract_id.in_(contract_ids))
        .all()
    )

    injection_attempts = sum(1 for e in events if e.type == "INJECTION_ATTEMPT_DETECTED")
    ast_policy_violations = sum(1 for e in events if e.type == "AST_VIOLATION")
    arbiter_vetoes = sum(1 for e in events if e.type == "ARBITER_VETO")

    penalties = (injection_attempts * 30.0) + (ast_policy_violations * 15.0) + (arbiter_vetoes * 10.0)

    if attempted_milestones > 0:
        base_pass_rate = (paid_milestones / attempted_milestones) * 100.0
        volume_dampener = min(1.0, attempted_milestones / 5.0)
        raw_score = (base_pass_rate - penalties) * volume_dampener
        score = max(0, min(100, int(round(raw_score))))
    else:
        base_pass_rate = 0.0
        volume_dampener = 0.0
        score = 0

    return {
        "worker_id": worker_id,
        "score": score,
        "attempted_milestones": attempted_milestones,
        "paid_milestones": paid_milestones,
        "base_pass_rate": round(base_pass_rate, 2),
        "volume_dampener": round(volume_dampener, 2),
        "penalties": {
            "injection_attempts": injection_attempts,
            "ast_policy_violations": ast_policy_violations,
            "arbiter_vetoes": arbiter_vetoes,
            "total_penalty_points": penalties,
        },
        "contracts_count": contracts_total,
        "contracts_completed": contracts_completed,
        "total_earned_usd": cents_to_usd_str(total_earned_cents),
    }


def list_worker_reputations(db: Session) -> List[Dict[str, Any]]:
    """List reputation summaries for all registered worker agents, sorted by score descending."""
    worker_rows = db.query(Contract.worker_id).distinct().all()
    worker_ids = [w[0] for w in worker_rows if w[0]]

    reputations = [compute_worker_reputation(db, wid) for wid in worker_ids]
    reputations.sort(key=lambda r: (r["score"], r["paid_milestones"]), reverse=True)
    return reputations
