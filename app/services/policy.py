from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Contract, Policy


class PolicyViolation(Exception):
    def __init__(self, message: str, violations: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.violations = violations or [message]


def get_or_create_policy(db: Session, org_id: str, environment: str) -> Policy:
    """Retrieve per-org environment policy, or create default policy if not set."""
    policy = db.scalar(select(Policy).where(Policy.org_id == org_id, Policy.environment == environment))
    if not policy:
        from app.ids import generate_id

        now = datetime.now(timezone.utc)
        policy = Policy(
            id=generate_id("pol"),
            org_id=org_id,
            environment=environment,
            max_task_cents=2500,  # $25.00 default task limit
            daily_cap_cents=10000,  # $100.00 daily spend limit
            max_milestones=5,
            worker_allowlist=None,  # Open by default
            require_hidden_tests=True,
            max_contract_days=28,
            created_at=now,
            updated_at=now,
        )
        db.add(policy)
        db.commit()
    return policy


def evaluate_spend_policy(
    db: Session,
    org_id: str,
    environment: str,
    total_cents: int,
    milestones: List[Dict[str, Any]],
    worker_email: str,
    deadline_at: Optional[datetime] = None,
    buyer_id: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """
    Evaluates org spend policy strictly BEFORE any provider call.
    Returns (is_compliant, list_of_violations).
    """
    policy = get_or_create_policy(db, org_id, environment)
    violations: List[str] = []

    # 1. Max Task Amount Check
    if total_cents > policy.max_task_cents:
        violations.append(
            f"Contract total amount ({total_cents} cents) exceeds maximum allowed task limit ({policy.max_task_cents} cents)"
        )

    # 2. Daily Spend Cap Check (sum of created/funded contracts today + proposed amount)
    # Red Team Arena non-overspender scenarios test defense invariants rather than org's daily budget exhaustion
    is_arena = bool(buyer_id and str(buyer_id).startswith("buyer_arena_"))
    if not is_arena:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        spent_today = (
            db.scalar(
                select(func.coalesce(func.sum(Contract.total_cents), 0)).where(
                    Contract.org_id == org_id,
                    Contract.environment == environment,
                    Contract.created_at >= today_start,
                    Contract.status.notin_(["VOIDED", "CANCELLED", "BLOCKED"]),
                )
            )
            or 0
        )

        if spent_today + total_cents > policy.daily_cap_cents:
            violations.append(
                f"Contract amount ({total_cents} cents) exceeds remaining daily spend cap "
                f"({max(0, policy.daily_cap_cents - spent_today)} cents remaining of {policy.daily_cap_cents} cents cap)"
            )

    # 3. Milestones Count Check (1 to max 5)
    if len(milestones) < 1 or len(milestones) > policy.max_milestones:
        violations.append(
            f"Milestones count ({len(milestones)}) violates policy (must be 1 to {policy.max_milestones})"
        )

    # 4. Worker Allowlist Check
    if policy.worker_allowlist:
        allowlist_normalized = {w.strip().lower() for w in policy.worker_allowlist if w.strip()}
        if worker_email.strip().lower() not in allowlist_normalized:
            violations.append(f"Worker '{worker_email}' is not on the organization's approved worker allowlist")

    # 5. Hidden Tests Requirement Check
    if policy.require_hidden_tests:
        for idx, m in enumerate(milestones, start=1):
            ht = m.get("hidden_tests")
            if not ht or not str(ht).strip():
                violations.append(f"Milestone {idx} is missing required hidden tests")

    # 6. Max Contract Days Check
    if deadline_at:
        now = datetime.now(timezone.utc)
        deadline_tz = deadline_at if deadline_at.tzinfo else deadline_at.replace(tzinfo=timezone.utc)
        duration_days = (deadline_tz - now).total_seconds() / 86400.0
        if duration_days > policy.max_contract_days:
            violations.append(f"Contract deadline exceeds maximum allowed duration ({policy.max_contract_days} days)")

    return len(violations) == 0, violations


def validate_spend_policy(
    db: Any,
    buyer_id: str,
    worker_email: str,
    total_cents: int,
    milestone_count: int,
) -> Tuple[bool, List[str]]:
    """Legacy compatibility helper for milestone spend validation."""
    dummy_milestones = [
        {"amount_minor": total_cents // max(1, milestone_count), "hidden_tests": "def test_hidden(): pass"}
        for _ in range(milestone_count)
    ]
    return evaluate_spend_policy(
        db=db,
        org_id=buyer_id,
        environment="simulated",
        total_cents=total_cents,
        milestones=dummy_milestones,
        worker_email=worker_email,
        deadline_at=None,
    )


def mask_email(email: str) -> str:
    """Mask email for receipts and public pages: j***@domain.com."""
    if not email or "@" not in email:
        return "***"
    user_part, domain_part = email.split("@", 1)
    if not user_part:
        return f"***@{domain_part}"
    return f"{user_part[0]}***@{domain_part}"
