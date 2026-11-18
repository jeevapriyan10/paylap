from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.ledger import append_event
from app.models import Contract
from app.services.clock import Clock, get_clock
from app.services.paypal_factory import get_provider
from app.state import ContractStatus, transition_contract


def expire_due_contracts(
    db: Session,
    clock: Optional[Clock] = None,
) -> List[str]:
    """
    Finds active contracts that have passed their deadline or safety margin
    before PayPal authorization expires, voids any remaining holds, and sets status to EXPIRED.
    """
    clk = clock or get_clock()
    now = clk.now()
    safety_margin = timedelta(hours=settings.PAYLAP_AUTH_SAFETY_MARGIN_HOURS)

    # Find candidate contracts
    candidates = db.scalars(
        select(Contract).where(
            Contract.status.in_([ContractStatus.AWAITING_FUNDING.value, ContractStatus.FUNDED.value])
        )
    ).all()

    expired_ids = []
    for ctr in candidates:
        is_due = False

        # 1. Deadline check
        if ctr.deadline_at and now >= ctr.deadline_at:
            is_due = True

        # 2. Authorization expiry safety margin check
        if ctr.authorization_expires_at and now >= (ctr.authorization_expires_at - safety_margin):
            is_due = True

        if is_due:
            # Void hold if funded and auth id exists
            if ctr.status == ContractStatus.FUNDED.value and ctr.paypal_authorization_id:
                try:
                    from app.models import Organization
                    org = db.scalar(select(Organization).where(Organization.id == ctr.org_id))
                    if org:
                        provider = get_provider(org, ctr.environment, db)
                        provider.void_authorization(
                            authorization_id=ctr.paypal_authorization_id,
                            request_id=f"expire-void-{ctr.id}",
                        )
                except Exception as exc:
                    append_event(
                        db,
                        event_type="EXPIRY_VOID_ERROR",
                        payload={"error": str(exc)},
                        contract_id=ctr.id,
                        org_id=ctr.org_id,
                        simulated=(ctr.environment == "simulated"),
                    )

            # Transition to EXPIRED
            transition_contract(ctr.status, ContractStatus.EXPIRED)
            ctr.status = ContractStatus.EXPIRED.value
            ctr.updated_at = now

            append_event(
                db,
                event_type="CONTRACT_EXPIRED",
                payload={
                    "contract_id": ctr.id,
                    "reason": "Contract passed deadline or authorization safety margin window",
                    "expired_at": now.isoformat(),
                },
                contract_id=ctr.id,
                org_id=ctr.org_id,
                simulated=(ctr.environment == "simulated"),
            )
            expired_ids.append(ctr.id)

    if expired_ids:
        db.commit()

    return expired_ids
