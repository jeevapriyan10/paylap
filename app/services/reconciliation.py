from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract, Organization, ReconciliationRun
from app.services.paypal_factory import get_provider
from app.state import ContractStatus

logger = logging.getLogger("paylap.reconciliation")


def run_reconciliation(
    db: Session,
    org_id: str,
    environment: str = "simulated",
) -> ReconciliationRun:
    """
    Executes a reconciliation run for an organization and environment.
    Compares local contract state against PayPal provider state.
    Flags discrepancies and sets needs_attention = True on affected contracts.
    """
    now = datetime.now(timezone.utc)
    org = db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise ValueError(f"Organization '{org_id}' not found")

    provider = get_provider(org, environment, db)

    # Active or recently updated contracts to check
    contracts = db.scalars(
        select(Contract).where(
            Contract.org_id == org_id,
            Contract.environment == environment,
            Contract.status.in_([
                ContractStatus.AWAITING_FUNDING.value,
                ContractStatus.FUNDED.value,
                ContractStatus.COMPLETED.value,
            ]),
        )
    ).all()

    checked_count = 0
    discrepancies: List[Dict[str, Any]] = []

    for ctr in contracts:
        checked_count += 1
        discrepancy_reasons: List[str] = []

        # If simulated provider, get order / auth state
        if hasattr(provider, "get_order") and ctr.paypal_order_id:
            try:
                pp_order = provider.get_order(ctr.paypal_order_id)
                pp_order_status = pp_order.get("status")

                if ctr.status == ContractStatus.FUNDED.value and pp_order_status in ("VOIDED", "EXPIRED"):
                    discrepancy_reasons.append(
                        f"Local contract is FUNDED but PayPal Order is {pp_order_status}"
                    )
            except Exception as exc:
                logger.warning(f"Failed to query PayPal order for contract {ctr.id}: {exc}")

        if hasattr(provider, "get_authorization") and ctr.paypal_authorization_id:
            try:
                pp_auth = provider.get_authorization(ctr.paypal_authorization_id)
                pp_auth_status = pp_auth.get("status")

                if ctr.status == ContractStatus.FUNDED.value and pp_auth_status in ("VOIDED", "DENIED", "EXPIRED"):
                    discrepancy_reasons.append(
                        f"Local contract is FUNDED but PayPal Authorization is {pp_auth_status}"
                    )
                elif ctr.status == ContractStatus.COMPLETED.value and pp_auth_status == "CREATED":
                    discrepancy_reasons.append(
                        "Local contract is COMPLETED but PayPal Authorization is still CREATED/open"
                    )
            except Exception as exc:
                logger.warning(f"Failed to query PayPal authorization for contract {ctr.id}: {exc}")

        if discrepancy_reasons:
            ctr.needs_attention = True
            ctr.updated_at = now
            discrepancy_entry = {
                "contract_id": ctr.id,
                "reasons": discrepancy_reasons,
                "local_status": ctr.status,
                "checked_at": now.isoformat(),
            }
            discrepancies.append(discrepancy_entry)

            append_event(
                db,
                event_type="DISCREPANCY_DETECTED",
                payload=discrepancy_entry,
                contract_id=ctr.id,
                org_id=ctr.org_id,
                simulated=(ctr.environment == "simulated"),
            )

    run_record = ReconciliationRun(
        id=generate_id("rec"),
        org_id=org_id,
        environment=environment,
        contracts_checked=checked_count,
        discrepancies_found=len(discrepancies),
        details={"discrepancies": discrepancies},
        run_at=now,
    )
    db.add(run_record)
    db.commit()

    return run_record
