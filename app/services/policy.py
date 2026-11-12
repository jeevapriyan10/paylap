from datetime import timedelta
from typing import List, Tuple
from sqlalchemy.orm import Session
from app.config import settings
from app.models import Contract, utc_now
from app.state import ContractStatus


def mask_email(email: str) -> str:
    """Mask email address for privacy (e.g. alice@example.com -> a***@example.com)."""
    if not email or "@" not in email:
        return "***"
    parts = email.split("@", 1)
    username = parts[0]
    domain = parts[1]
    if len(username) > 1:
        masked_user = username[0] + "***"
    else:
        masked_user = "***"
    return f"{masked_user}@{domain}"


def validate_spend_policy(
    db: Session,
    buyer_id: str,
    worker_email: str,
    total_cents: int,
    milestone_count: int
) -> Tuple[bool, List[str]]:
    """
    Evaluates spend policy rules before any escrow order is initiated:
    1. Per-task budget cap (PAYLAP_POLICY_MAX_TASK_USD).
    2. Per-buyer rolling 24-hour committed budget cap (PAYLAP_POLICY_DAILY_USD).
    3. Worker email allowlist check (if allowlist is configured).
    4. Milestone count limits (1 to 3).
    """
    violations = []

    # 1. Milestone count check
    if not (1 <= milestone_count <= 3):
        violations.append(f"Milestone count {milestone_count} violates policy (must be 1 to 3).")

    # 2. Per-task budget cap
    max_task_cents = settings.PAYLAP_POLICY_MAX_TASK_USD * 100
    if total_cents > max_task_cents:
        task_usd = total_cents / 100.0
        violations.append(
            f"Task budget ${task_usd:.2f} exceeds maximum task policy limit of ${settings.PAYLAP_POLICY_MAX_TASK_USD:.2f}."
        )

    # 3. Rolling 24-hour committed budget cap per buyer
    since_24h = utc_now() - timedelta(hours=24)
    past_contracts = (
        db.query(Contract)
        .filter(
            Contract.buyer_id == buyer_id,
            Contract.created_at >= since_24h,
            Contract.status.notin_([
                ContractStatus.CANCELLED.value,
                ContractStatus.BLOCKED.value,
                ContractStatus.ERROR.value,
            ])
        )
        .all()
    )
    past_committed_cents = sum(c.total_cents for c in past_contracts)
    projected_daily_cents = past_committed_cents + total_cents
    max_daily_cents = settings.PAYLAP_POLICY_DAILY_USD * 100

    if projected_daily_cents > max_daily_cents:
        projected_usd = projected_daily_cents / 100.0
        violations.append(
            f"Buyer 24-hour committed budget ${projected_usd:.2f} exceeds daily policy limit of ${settings.PAYLAP_POLICY_DAILY_USD:.2f}."
        )

    # 4. Worker email allowlist check (if configured)
    allowlist = settings.policy_allowlist_set
    if allowlist:
        clean_email = worker_email.strip().lower()
        if clean_email not in allowlist:
            violations.append(
                f"Worker recipient email '{worker_email}' is not in the authorized recipient allowlist."
            )

    return (len(violations) == 0, violations)


def get_policy_summary() -> dict:
    """Return configured policy limits with masked emails."""
    allowlist = [mask_email(e) for e in sorted(settings.policy_allowlist_set)]
    return {
        "max_task_usd": settings.PAYLAP_POLICY_MAX_TASK_USD,
        "daily_usd": settings.PAYLAP_POLICY_DAILY_USD,
        "allowlist": allowlist,
    }
