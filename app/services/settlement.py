from typing import Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.ledger import append_event
from app.models import Contract, Milestone, utc_now
from app.schemas import MilestoneOutcome
from app.services.paypal_base import PayPalBase, PayPalError
from app.services.paypal_client import PayPalClient
from app.services.paypal_fake import FakePayPal
from app.services.sandbox import run_python_tests
from app.state import (
    ContractStatus,
    MilestoneStatus,
    transition_contract,
    transition_milestone,
    InvalidStateTransitionError,
)

# Global or reusable singleton providers
_fake_provider = FakePayPal()
_live_client: Optional[PayPalClient] = None


def get_paypal_provider(mode: str) -> PayPalBase:
    global _live_client
    if mode == "live":
        if _live_client is None:
            _live_client = PayPalClient()
        return _live_client
    return _fake_provider


def settle_milestone(
    db: Session,
    contract_id: str,
    milestone_idx: int,
    code: str,
    custom_provider: Optional[PayPalBase] = None
) -> MilestoneOutcome:
    """
    Orchestrates milestone submission, sandbox evaluation, PayPal capture,
    worker payout, state transitions, and ledger logging.
    """
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise ValueError(f"Contract '{contract_id}' not found.")

    milestone = (
        db.query(Milestone)
        .filter(Milestone.contract_id == contract_id, Milestone.idx == milestone_idx)
        .first()
    )
    if not milestone:
        raise ValueError(f"Milestone {milestone_idx} for contract '{contract_id}' not found.")

    is_simulated = (contract.mode == "demo")
    provider = custom_provider or get_paypal_provider(contract.mode)

    # Idempotency check: If already paid, return recorded outcome without double-paying
    if milestone.status == MilestoneStatus.PAID.value:
        return MilestoneOutcome(
            contract_id=contract.id,
            milestone_idx=milestone.idx,
            status=milestone.status,
            passed=True,
            sandbox_summary={"note": "Milestone was already verified and paid."},
            capture_id=milestone.capture_id,
            payout_batch_id=milestone.payout_batch_id,
            payout_status=milestone.payout_status,
            simulated=is_simulated
        )

    # Contract must be FUNDED
    if contract.status != ContractStatus.FUNDED.value:
        raise InvalidStateTransitionError(
            f"Cannot submit milestone for contract in state '{contract.status}'. Contract must be FUNDED."
        )

    # Check if attempts exhausted
    if milestone.status == MilestoneStatus.REJECTED.value and milestone.attempts >= contract.max_attempts:
        raise InvalidStateTransitionError(
            f"Milestone {milestone_idx} has exhausted maximum attempts ({contract.max_attempts})."
        )

    # State transition: PENDING/REJECTED -> SUBMITTED -> VERIFYING
    transition_milestone(milestone.status, MilestoneStatus.SUBMITTED)
    milestone.status = MilestoneStatus.SUBMITTED.value
    append_event(
        db,
        event_type="MILESTONE_SUBMITTED",
        payload={"milestone_idx": milestone.idx, "attempt": milestone.attempts + 1},
        contract_id=contract.id,
        simulated=is_simulated
    )

    transition_milestone(milestone.status, MilestoneStatus.VERIFYING)
    milestone.status = MilestoneStatus.VERIFYING.value
    append_event(
        db,
        event_type="MILESTONE_VERIFYING",
        payload={"milestone_idx": milestone.idx},
        contract_id=contract.id,
        simulated=is_simulated
    )
    db.commit()

    # Run code sandbox
    sandbox_res = run_python_tests(code=code, tests=milestone.public_tests)
    sandbox_dict = sandbox_res.to_dict()

    if sandbox_res.passed:
        # Milestone PASS: Capture + Payout + Complete milestone
        append_event(
            db,
            event_type="MILESTONE_VERIFIED_SUCCESS",
            payload={
                "milestone_idx": milestone.idx,
                "duration_ms": sandbox_res.duration_ms,
            },
            contract_id=contract.id,
            simulated=is_simulated
        )

        # Check if this is the last unpaid milestone
        other_unpaid = (
            db.query(Milestone)
            .filter(
                Milestone.contract_id == contract.id,
                Milestone.id != milestone.id,
                Milestone.status != MilestoneStatus.PAID.value
            )
            .count()
        )
        final_capture = (other_unpaid == 0)

        capture_req_id = f"capture-{contract.id}-{milestone.idx}"
        payout_req_id = f"payout-{contract.id}-{milestone.idx}"

        try:
            # 1. Capture from authorization
            cap_res = provider.capture(
                authorization_id=contract.paypal_authorization_id or f"DEMO-AUTH-{contract.id}",
                amount_cents=milestone.amount_cents,
                final_capture=final_capture,
                request_id=capture_req_id
            )
            append_event(
                db,
                event_type="CAPTURE_COMPLETED",
                payload={
                    "milestone_idx": milestone.idx,
                    "capture_id": cap_res.get("capture_id"),
                    "amount_cents": milestone.amount_cents,
                    "final_capture": final_capture,
                    "request_id": capture_req_id,
                },
                contract_id=contract.id,
                simulated=cap_res.get("simulated", is_simulated)
            )

            # 2. Dispatch Payout
            # Honor PAYLAP_PAYOUT_MODE=simulated even in live mode
            payout_is_simulated = is_simulated or (settings.PAYLAP_PAYOUT_MODE == "simulated")
            payout_provider = _fake_provider if payout_is_simulated else provider

            payout_res = payout_provider.send_payout(
                recipient_email=contract.worker_email,
                amount_cents=milestone.amount_cents,
                request_id=payout_req_id,
                note=f"Payment for milestone {milestone.idx}: {milestone.title}"
            )
            append_event(
                db,
                event_type="PAYOUT_INITIATED",
                payload={
                    "milestone_idx": milestone.idx,
                    "payout_batch_id": payout_res.get("payout_batch_id"),
                    "recipient_email": contract.worker_email,
                    "amount_cents": milestone.amount_cents,
                    "request_id": payout_req_id,
                },
                contract_id=contract.id,
                simulated=payout_is_simulated
            )

            # 3. Update milestone to PAID
            milestone.capture_id = cap_res.get("capture_id")
            milestone.payout_batch_id = payout_res.get("payout_batch_id")
            milestone.payout_status = payout_res.get("status", "SUCCESS")
            milestone.paid_at = utc_now()
            transition_milestone(milestone.status, MilestoneStatus.PAID)
            milestone.status = MilestoneStatus.PAID.value

            append_event(
                db,
                event_type="MILESTONE_PAID",
                payload={
                    "milestone_idx": milestone.idx,
                    "amount_cents": milestone.amount_cents,
                    "capture_id": milestone.capture_id,
                    "payout_batch_id": milestone.payout_batch_id,
                },
                contract_id=contract.id,
                simulated=is_simulated
            )

            # 4. Check if all milestones are paid -> COMPLETED
            if final_capture:
                transition_contract(contract.status, ContractStatus.COMPLETED)
                contract.status = ContractStatus.COMPLETED.value
                append_event(
                    db,
                    event_type="CONTRACT_COMPLETED",
                    payload={"contract_id": contract.id, "total_cents": contract.total_cents},
                    contract_id=contract.id,
                    simulated=is_simulated
                )

            db.commit()

            return MilestoneOutcome(
                contract_id=contract.id,
                milestone_idx=milestone.idx,
                status=milestone.status,
                passed=True,
                sandbox_summary=sandbox_dict,
                capture_id=milestone.capture_id,
                payout_batch_id=milestone.payout_batch_id,
                payout_status=milestone.payout_status,
                simulated=is_simulated
            )

        except (PayPalError, Exception) as exc:
            append_event(
                db,
                event_type="SETTLEMENT_ERROR",
                payload={
                    "milestone_idx": milestone.idx,
                    "error": str(exc),
                    "debug_id": getattr(exc, "debug_id", None),
                },
                contract_id=contract.id,
                simulated=is_simulated
            )
            db.commit()
            raise

    else:
        # Milestone FAIL: increment attempts, reject, or void
        milestone.attempts += 1
        transition_milestone(milestone.status, MilestoneStatus.REJECTED)
        milestone.status = MilestoneStatus.REJECTED.value

        append_event(
            db,
            event_type="MILESTONE_REJECTED",
            payload={
                "milestone_idx": milestone.idx,
                "attempt": milestone.attempts,
                "max_attempts": contract.max_attempts,
                "violations": sandbox_res.violations,
                "timed_out": sandbox_res.timed_out,
                "output_preview": sandbox_res.output[:200],
            },
            contract_id=contract.id,
            simulated=is_simulated
        )

        if milestone.attempts >= contract.max_attempts:
            # Attempts exhausted -> Void remaining authorization and mark contract VOIDED
            void_req_id = f"void-{contract.id}"
            try:
                if contract.paypal_authorization_id:
                    provider.void_authorization(
                        authorization_id=contract.paypal_authorization_id,
                        request_id=void_req_id
                    )
                    append_event(
                        db,
                        event_type="AUTHORIZATION_VOIDED",
                        payload={"authorization_id": contract.paypal_authorization_id, "request_id": void_req_id},
                        contract_id=contract.id,
                        simulated=is_simulated
                    )
            except Exception as void_err:
                append_event(
                    db,
                    event_type="VOID_ERROR",
                    payload={"error": str(void_err)},
                    contract_id=contract.id,
                    simulated=is_simulated
                )

            transition_contract(contract.status, ContractStatus.VOIDED)
            contract.status = ContractStatus.VOIDED.value
            append_event(
                db,
                event_type="CONTRACT_VOIDED",
                payload={
                    "contract_id": contract.id,
                    "reason": f"Milestone {milestone.idx} exhausted {contract.max_attempts} attempts."
                },
                contract_id=contract.id,
                simulated=is_simulated
            )

        db.commit()

        return MilestoneOutcome(
            contract_id=contract.id,
            milestone_idx=milestone.idx,
            status=milestone.status,
            passed=False,
            sandbox_summary=sandbox_dict,
            capture_id=None,
            payout_batch_id=None,
            payout_status=None,
            simulated=is_simulated,
            error="Sandbox tests failed or policy violations detected."
        )
