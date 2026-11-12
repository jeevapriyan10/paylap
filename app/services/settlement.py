from typing import Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.ledger import append_event
from app.models import Contract, Milestone, utc_now
from app.schemas import MilestoneOutcome
from app.services.arbiter import review_submission
from app.services.injection_scan import scan_for_injections
from app.services.paypal_base import PayPalBase, PayPalError
from app.services.paypal_client import PayPalClient
from app.services.paypal_fake import FakePayPal
from app.state import (
    ContractStatus,
    MilestoneStatus,
    InvalidStateTransitionError,
    transition_contract,
    transition_milestone,
)
from app.verifiers import get_verifier

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


def _execute_batch_capture_and_payouts(
    db: Session,
    contract: Contract,
    provider: PayPalBase,
    is_simulated: bool
):
    """
    Executes a single batch capture for all verified milestones,
    then dispatches individual payouts per verified milestone.
    """
    db.flush()
    to_settle = (
        db.query(Milestone)
        .filter(
            Milestone.contract_id == contract.id,
            Milestone.status == MilestoneStatus.VERIFIED_PENDING_SETTLEMENT.value
        )
        .order_by(Milestone.idx.asc())
        .all()
    )

    if not to_settle:
        return

    total_batch_cents = sum(m.amount_cents for m in to_settle)
    cap_req_id = f"batch-cap-{contract.id}"

    # 1. Single capture with final_capture=True for total verified
    cap_res = provider.capture(
        authorization_id=contract.paypal_authorization_id or f"DEMO-AUTH-{contract.id}",
        amount_cents=total_batch_cents,
        final_capture=True,
        request_id=cap_req_id
    )
    append_event(
        db,
        event_type="BATCH_CAPTURE_COMPLETED",
        payload={
            "contract_id": contract.id,
            "total_cents": total_batch_cents,
            "capture_id": cap_res.get("capture_id"),
            "request_id": cap_req_id,
            "milestone_indices": [m.idx for m in to_settle]
        },
        contract_id=contract.id,
        simulated=cap_res.get("simulated", is_simulated)
    )

    # 2. Dispatch payout per milestone
    payout_is_simulated = is_simulated or (settings.PAYLAP_PAYOUT_MODE == "simulated")
    payout_provider = provider if (is_simulated or settings.PAYLAP_PAYOUT_MODE != "simulated") else _fake_provider

    for m in to_settle:
        p_req_id = f"payout-{contract.id}-{m.idx}"
        payout_res = payout_provider.send_payout(
            recipient_email=contract.worker_email,
            amount_cents=m.amount_cents,
            request_id=p_req_id,
            note=f"Payment for milestone {m.idx}: {m.title}"
        )
        append_event(
            db,
            event_type="PAYOUT_INITIATED",
            payload={
                "milestone_idx": m.idx,
                "payout_batch_id": payout_res.get("payout_batch_id"),
                "recipient_email": contract.worker_email,
                "amount_cents": m.amount_cents,
                "request_id": p_req_id,
            },
            contract_id=contract.id,
            simulated=payout_is_simulated
        )

        m.capture_id = cap_res.get("capture_id")
        m.payout_batch_id = payout_res.get("payout_batch_id")
        m.payout_status = payout_res.get("status", "SUCCESS")
        m.paid_at = utc_now()
        transition_milestone(m.status, MilestoneStatus.PAID)
        m.status = MilestoneStatus.PAID.value

        append_event(
            db,
            event_type="MILESTONE_PAID",
            payload={
                "milestone_idx": m.idx,
                "amount_cents": m.amount_cents,
                "capture_id": m.capture_id,
                "payout_batch_id": m.payout_batch_id,
            },
            contract_id=contract.id,
            simulated=is_simulated
        )


def _handle_void_fallback(
    db: Session,
    contract: Contract,
    provider: PayPalBase,
    void_req_id: str,
    is_simulated: bool
):
    """
    Attempts to void authorization. If PayPal fails after partial captures,
    records error event with debug_id and notes that remainder expires at authorization expiry.
    """
    if not contract.paypal_authorization_id:
        return

    try:
        provider.void_authorization(
            authorization_id=contract.paypal_authorization_id,
            request_id=void_req_id
        )
        append_event(
            db,
            event_type="AUTHORIZATION_VOIDED",
            payload={
                "authorization_id": contract.paypal_authorization_id,
                "request_id": void_req_id
            },
            contract_id=contract.id,
            simulated=is_simulated
        )
    except Exception as void_err:
        debug_id = getattr(void_err, "debug_id", None)
        append_event(
            db,
            event_type="VOID_FALLBACK_ERROR",
            payload={
                "authorization_id": contract.paypal_authorization_id,
                "error": str(void_err),
                "debug_id": debug_id,
                "note": "Authorization voiding rejected or unsupported after captures; remainder will be released at authorization expiry."
            },
            contract_id=contract.id,
            simulated=is_simulated
        )


def settle_milestone(
    db: Session,
    contract_id: str,
    milestone_idx: int,
    code: str,
    custom_provider: Optional[PayPalBase] = None
) -> MilestoneOutcome:
    """
    Orchestrates milestone submission:
    1. Scan for adversarial injection patterns.
    2. Run deterministic verifier plugin (public then hidden).
    3. Structural enforcement: Arbiter is invoked ONLY if deterministic checks pass.
    4. Arbiter evaluation (ok/veto, fail-closed on unavailable).
    5. Settlement: partial capture or batch_at_end strategy.
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
            simulated=is_simulated,
            gate_decided="idempotent"
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

    # Step 1: Injection scan
    injection_flags = scan_for_injections(code)
    if injection_flags:
        append_event(
            db,
            event_type="INJECTION_PATTERNS_DETECTED",
            payload={"milestone_idx": milestone.idx, "risk_flags": injection_flags},
            contract_id=contract.id,
            simulated=is_simulated
        )

    # State transitions: PENDING/REJECTED -> SUBMITTED -> VERIFYING
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

    # Step 2: Deterministic Verifier Plugin
    verifier = get_verifier(milestone.verifier_type)
    verif_res = verifier.verify(milestone=milestone, submission=code)

    # Record private detail in backend logging if hidden tests failed
    sandbox_summary = verif_res.to_dict()

    # STRUCTURAL PRINCIPLE: THE LLM NEVER HOLDS PAYMENT AUTHORITY.
    # The arbiter is ONLY called if all deterministic gates passed!
    if not verif_res.passed:
        # Deterministic Gate FAILED
        gate_decided = "hidden" if any(c.get("name") == "hidden_tests" and not c.get("passed") for c in verif_res.checks) else "deterministic"

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
                "gate_decided": gate_decided,
                "public_summary": verif_res.public_summary,
                "violations": verif_res.violations,
                "risk_flags": injection_flags,
            },
            contract_id=contract.id,
            simulated=is_simulated
        )

        if milestone.attempts >= contract.max_attempts:
            # Attempts exhausted -> Settle any pending or void
            if settings.PAYLAP_CAPTURE_STRATEGY == "batch_at_end":
                _execute_batch_capture_and_payouts(db, contract, provider, is_simulated)

            void_req_id = f"void-{contract.id}"
            _handle_void_fallback(db, contract, provider, void_req_id, is_simulated)

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
            sandbox_summary=sandbox_summary,
            capture_id=None,
            payout_batch_id=None,
            payout_status=None,
            simulated=is_simulated,
            error=verif_res.public_summary,
            gate_decided=gate_decided,
            risk_flags=injection_flags
        )

    # Step 3: Deterministic Gate PASSED -> Invoke Arbiter (Veto Layer)
    arbiter_res = review_submission(
        spec=milestone.spec,
        submission=code,
        mode=settings.resolved_arbiter_mode
    )

    append_event(
        db,
        event_type="ARBITER_REVIEWED",
        payload={
            "milestone_idx": milestone.idx,
            "verdict": arbiter_res.verdict,
            "reasons": arbiter_res.reasons,
            "risk_flags": arbiter_res.risk_flags,
            "source": arbiter_res.source,
            "cached": arbiter_res.cached,
        },
        contract_id=contract.id,
        simulated=arbiter_res.simulated or is_simulated
    )

    # Step 4: Handle Fail-Closed policy on Arbiter UNAVAILABLE
    if arbiter_res.verdict == "unavailable":
        # Reset milestone back to PENDING without consuming an attempt!
        milestone.status = MilestoneStatus.PENDING.value
        append_event(
            db,
            event_type="ARBITER_UNAVAILABLE",
            payload={
                "milestone_idx": milestone.idx,
                "reasons": arbiter_res.reasons,
                "note": "Fail-closed policy enforced: no money moved, attempt not consumed."
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
            sandbox_summary={"error": "Arbiter is currently unavailable. Fail-closed policy applied."},
            capture_id=None,
            payout_batch_id=None,
            payout_status=None,
            simulated=is_simulated,
            error="Arbiter unavailable; submission reset to PENDING.",
            gate_decided="arbiter",
            risk_flags=arbiter_res.risk_flags
        )

    # Step 5: Arbiter VETO
    if arbiter_res.verdict == "veto":
        milestone.attempts += 1
        transition_milestone(milestone.status, MilestoneStatus.REJECTED)
        milestone.status = MilestoneStatus.REJECTED.value

        append_event(
            db,
            event_type="ARBITER_VETOED",
            payload={
                "milestone_idx": milestone.idx,
                "attempt": milestone.attempts,
                "reasons": arbiter_res.reasons,
                "risk_flags": arbiter_res.risk_flags,
            },
            contract_id=contract.id,
            simulated=arbiter_res.simulated or is_simulated
        )

        if milestone.attempts >= contract.max_attempts:
            if settings.PAYLAP_CAPTURE_STRATEGY == "batch_at_end":
                _execute_batch_capture_and_payouts(db, contract, provider, is_simulated)

            void_req_id = f"void-{contract.id}"
            _handle_void_fallback(db, contract, provider, void_req_id, is_simulated)

            transition_contract(contract.status, ContractStatus.VOIDED)
            contract.status = ContractStatus.VOIDED.value
            append_event(
                db,
                event_type="CONTRACT_VOIDED",
                payload={"contract_id": contract.id, "reason": "Arbiter veto exhausted attempts."},
                contract_id=contract.id,
                simulated=is_simulated
            )

        db.commit()

        return MilestoneOutcome(
            contract_id=contract.id,
            milestone_idx=milestone.idx,
            status=milestone.status,
            passed=False,
            sandbox_summary={"veto_reasons": arbiter_res.reasons},
            capture_id=None,
            payout_batch_id=None,
            payout_status=None,
            simulated=is_simulated,
            error=f"Arbiter Veto: {'; '.join(arbiter_res.reasons)}",
            gate_decided="arbiter",
            risk_flags=arbiter_res.risk_flags
        )

    # Step 6: Full PASS! Apply Capture Strategy
    strategy = settings.PAYLAP_CAPTURE_STRATEGY

    if strategy == "batch_at_end":
        transition_milestone(milestone.status, MilestoneStatus.VERIFIED_PENDING_SETTLEMENT)
        milestone.status = MilestoneStatus.VERIFIED_PENDING_SETTLEMENT.value
        db.flush()
        append_event(
            db,
            event_type="MILESTONE_VERIFIED_PENDING_SETTLEMENT",
            payload={"milestone_idx": milestone.idx, "amount_cents": milestone.amount_cents},
            contract_id=contract.id,
            simulated=is_simulated
        )

        # Check if all milestones are now verified
        all_unsettled = (
            db.query(Milestone)
            .filter(
                Milestone.contract_id == contract.id,
                Milestone.status.notin_([
                    MilestoneStatus.VERIFIED_PENDING_SETTLEMENT.value,
                    MilestoneStatus.PAID.value
                ])
            )
            .count()
        )

        if all_unsettled == 0:
            # All milestones verified! Execute single batch capture + payouts
            _execute_batch_capture_and_payouts(db, contract, provider, is_simulated)
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
            sandbox_summary=sandbox_summary,
            capture_id=milestone.capture_id,
            payout_batch_id=milestone.payout_batch_id,
            payout_status=milestone.payout_status,
            simulated=is_simulated,
            gate_decided="deterministic",
            risk_flags=arbiter_res.risk_flags
        )

    else:
        # Default Strategy: 'partial'
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

            payout_is_simulated = is_simulated or (settings.PAYLAP_PAYOUT_MODE == "simulated")
            payout_provider = provider if (is_simulated or settings.PAYLAP_PAYOUT_MODE != "simulated") else _fake_provider

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
                sandbox_summary=sandbox_summary,
                capture_id=milestone.capture_id,
                payout_batch_id=milestone.payout_batch_id,
                payout_status=milestone.payout_status,
                simulated=is_simulated,
                gate_decided="deterministic",
                risk_flags=arbiter_res.risk_flags
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
