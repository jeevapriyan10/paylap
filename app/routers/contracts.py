from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.ledger import append_event
from app.models import Contract, Milestone, Event, generate_short_id
from app.schemas import (
    ContractCreate,
    ContractResponse,
    MilestoneOutcome,
    MilestoneResponse,
    MilestoneSubmit,
    cents_to_usd_str,
    usd_str_to_cents,
)
from app.services.settlement import get_paypal_provider, settle_milestone
from app.state import (
    ContractStatus,
    InvalidStateTransitionError,
    transition_contract,
)

router = APIRouter(prefix="/api/contracts", tags=["Contracts"])


def format_contract_response(contract: Contract) -> ContractResponse:
    milestones_resp = [
        MilestoneResponse(
            id=m.id,
            idx=m.idx,
            title=m.title,
            amount_cents=m.amount_cents,
            amount_usd=cents_to_usd_str(m.amount_cents),
            spec=m.spec,
            public_tests=m.public_tests,
            verifier_type=getattr(m, "verifier_type", "python_code") or "python_code",
            verifier_config=getattr(m, "verifier_config", None),
            status=m.status,
            attempts=m.attempts,
            capture_id=m.capture_id,
            payout_batch_id=m.payout_batch_id,
            payout_status=m.payout_status,
            paid_at=m.paid_at,
        )
        for m in sorted(contract.milestones, key=lambda x: x.idx)
    ]

    return ContractResponse(
        id=contract.id,
        title=contract.title,
        buyer_id=contract.buyer_id,
        worker_id=contract.worker_id,
        worker_email=contract.worker_email,
        total_cents=contract.total_cents,
        total_usd=cents_to_usd_str(contract.total_cents),
        currency=contract.currency,
        status=contract.status,
        paypal_order_id=contract.paypal_order_id,
        paypal_authorization_id=contract.paypal_authorization_id,
        approve_url=contract.approve_url,
        mode=contract.mode,
        max_attempts=contract.max_attempts,
        milestones=milestones_resp,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


@router.post("", response_model=ContractResponse, status_code=201)
def create_contract(
    payload: ContractCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new milestone contract and initialize PayPal escrow order.
    In Demo mode, the contract is automatically funded.
    In Live mode, status is AWAITING_FUNDING with an approval URL for the buyer.
    """
    import hashlib

    mode = settings.PAYLAP_MODE
    is_simulated = (mode == "demo")
    provider = get_paypal_provider(mode)

    contract_id = generate_short_id()

    # Calculate total cents exactly from milestone amounts
    milestone_cents = [usd_str_to_cents(m.amount) for m in payload.milestones]
    total_cents = sum(milestone_cents)

    contract = Contract(
        id=contract_id,
        title=payload.title,
        buyer_id=payload.buyer_id,
        worker_id=payload.worker_id,
        worker_email=payload.worker_email,
        total_cents=total_cents,
        currency="USD",
        status=ContractStatus.CREATED.value,
        mode=mode,
        max_attempts=payload.max_attempts,
    )
    db.add(contract)

    hidden_commitments = []
    for idx, (m_spec, cents) in enumerate(zip(payload.milestones, milestone_cents), start=1):
        hidden_parts = []
        if m_spec.hidden_tests:
            hidden_parts.append(m_spec.hidden_tests)
        if m_spec.verifier_config and "hidden_tests" in m_spec.verifier_config:
            hidden_parts.append(str(m_spec.verifier_config["hidden_tests"]))

        h_commit = (
            hashlib.sha256("".join(hidden_parts).encode("utf-8")).hexdigest()
            if hidden_parts else None
        )
        hidden_commitments.append(h_commit)

        milestone = Milestone(
            id=generate_short_id(),
            contract_id=contract_id,
            idx=idx,
            title=m_spec.title,
            amount_cents=cents,
            spec=m_spec.spec,
            public_tests=m_spec.public_tests,
            hidden_tests=m_spec.hidden_tests,  # Stored internally, never exposed via API
            verifier_type=m_spec.verifier_type or "python_code",
            verifier_config=m_spec.verifier_config,
            hidden_commitment=h_commit,
            status="PENDING",
            attempts=0,
        )
        db.add(milestone)

    overall_h_commit = (
        hashlib.sha256("".join(c for c in hidden_commitments if c).encode("utf-8")).hexdigest()
        if any(hidden_commitments) else None
    )
    contract.hidden_commitment = overall_h_commit

    db.commit()
    db.refresh(contract)

    append_event(
        db,
        event_type="CONTRACT_CREATED",
        payload={
            "contract_id": contract.id,
            "title": contract.title,
            "total_cents": total_cents,
            "total_usd": cents_to_usd_str(total_cents),
            "milestone_count": len(payload.milestones),
            "hidden_commitments": hidden_commitments,
            "hidden_commitment": overall_h_commit,
            "mode": mode,
        },
        contract_id=contract.id,
        simulated=is_simulated,
    )

    if mode == "demo":
        # Auto-fund simulated order
        order_res = provider.create_escrow_order(
            contract_id=contract.id,
            amount_cents=total_cents,
            return_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract.id}/funding/return",
            cancel_url=f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract.id}/funding/cancel",
        )
        contract.paypal_order_id = order_res.get("order_id")

        append_event(
            db,
            event_type="ORDER_CREATED",
            payload={"order_id": contract.paypal_order_id, "amount_cents": total_cents},
            contract_id=contract.id,
            simulated=True,
        )

        auth_res = provider.authorize_order(order_id=contract.paypal_order_id)
        contract.paypal_authorization_id = auth_res.get("authorization_id")

        append_event(
            db,
            event_type="ORDER_AUTHORIZED",
            payload={"authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            simulated=True,
        )

        transition_contract(contract.status, ContractStatus.FUNDED)
        contract.status = ContractStatus.FUNDED.value

        append_event(
            db,
            event_type="CONTRACT_FUNDED",
            payload={"contract_id": contract.id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            simulated=True,
        )
        db.commit()

    else:
        # Live mode: Create PayPal order and obtain buyer approval redirect URL
        return_url = f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract.id}/funding/return"
        cancel_url = f"{settings.PAYLAP_PUBLIC_URL}/api/contracts/{contract.id}/funding/cancel"

        try:
            order_res = provider.create_escrow_order(
                contract_id=contract.id,
                amount_cents=total_cents,
                return_url=return_url,
                cancel_url=cancel_url,
                request_id=f"order-{contract.id}",
            )
            contract.paypal_order_id = order_res.get("order_id")
            contract.approve_url = order_res.get("approve_url")

            transition_contract(contract.status, ContractStatus.AWAITING_FUNDING)
            contract.status = ContractStatus.AWAITING_FUNDING.value

            append_event(
                db,
                event_type="ORDER_CREATED",
                payload={
                    "order_id": contract.paypal_order_id,
                    "approve_url": contract.approve_url,
                    "amount_cents": total_cents,
                },
                contract_id=contract.id,
                simulated=False,
            )
            db.commit()

        except Exception as exc:
            append_event(
                db,
                event_type="ORDER_CREATION_FAILED",
                payload={"error": str(exc)},
                contract_id=contract.id,
                simulated=False,
            )
            db.commit()
            raise HTTPException(status_code=502, detail=f"Failed to create PayPal escrow order: {exc}")

    db.refresh(contract)
    return format_contract_response(contract)


@router.get("", response_model=List[ContractResponse])
def list_contracts(db: Session = Depends(get_db)):
    """List all contracts."""
    contracts = db.query(Contract).order_by(Contract.created_at.desc()).all()
    return [format_contract_response(c) for c in contracts]


@router.get("/{contract_id}")
def get_contract_detail(contract_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get detailed contract information including milestones (without hidden_tests)
    and recent ledger events.
    """
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    recent_events = (
        db.query(Event)
        .filter(Event.contract_id == contract_id)
        .order_by(Event.seq.desc())
        .limit(20)
        .all()
    )

    return {
        "contract": format_contract_response(contract),
        "recent_events": [
            {
                "seq": e.seq,
                "type": e.type,
                "payload": e.payload,
                "simulated": e.simulated,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in recent_events
        ],
    }


@router.get("/{contract_id}/funding/return", response_class=HTMLResponse)
def funding_return_callback(
    contract_id: str,
    token: Optional[str] = Query(None, description="PayPal Order ID"),
    db: Session = Depends(get_db)
):
    """
    Redirect endpoint called by PayPal when buyer approves authorization.
    Authorizes the order in live mode and transitions contract to FUNDED.
    """
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found.")

    if contract.status == ContractStatus.FUNDED.value:
        return HTMLResponse(
            content="""
            <html>
              <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0fdf4;">
                <h1 style="color:#166534;">Escrow Already Funded!</h1>
                <p>The escrow hold for this contract is already active. You can safely close this window.</p>
              </body>
            </html>
            """
        )

    order_id = token or contract.paypal_order_id
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order ID token.")

    provider = get_paypal_provider(contract.mode)

    try:
        auth_res = provider.authorize_order(order_id=order_id, request_id=f"auth-{contract.id}")
        contract.paypal_authorization_id = auth_res.get("authorization_id")

        append_event(
            db,
            event_type="ORDER_AUTHORIZED",
            payload={"order_id": order_id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            simulated=False,
        )

        transition_contract(contract.status, ContractStatus.FUNDED)
        contract.status = ContractStatus.FUNDED.value

        append_event(
            db,
            event_type="CONTRACT_FUNDED",
            payload={"contract_id": contract.id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            simulated=False,
        )
        db.commit()

    except Exception as exc:
        append_event(
            db,
            event_type="AUTHORIZATION_FAILED",
            payload={"order_id": order_id, "error": str(exc)},
            contract_id=contract.id,
            simulated=False,
        )
        db.commit()
        return HTMLResponse(
            status_code=500,
            content=f"""
            <html>
              <body style="font-family:sans-serif; text-align:center; padding:50px; background:#fef2f2;">
                <h1 style="color:#991b1b;">Escrow Authorization Failed</h1>
                <p>Error authorizing PayPal escrow order: {exc}</p>
              </body>
            </html>
            """
        )

    return HTMLResponse(
        content="""
        <html>
          <head><title>PayLap Escrow Funded</title></head>
          <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0fdf4;">
            <h1 style="color:#166534;">Escrow Funded Successfully!</h1>
            <p style="font-size:18px; color:#15803d;">
              Funds are securely placed on hold in PayPal escrow.
            </p>
            <p style="color:#4b5563;">
              The worker agent may now submit work against the milestone specifications.<br>
              You may safely close this browser window.
            </p>
          </body>
        </html>
        """
    )


@router.get("/{contract_id}/funding/cancel", response_class=HTMLResponse)
def funding_cancel_callback(contract_id: str, db: Session = Depends(get_db)):
    """Called when buyer cancels approval on PayPal."""
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if contract and contract.status == ContractStatus.AWAITING_FUNDING.value:
        transition_contract(contract.status, ContractStatus.CANCELLED)
        contract.status = ContractStatus.CANCELLED.value
        append_event(
            db,
            event_type="CONTRACT_CANCELLED",
            payload={"contract_id": contract.id, "reason": "Buyer cancelled at PayPal checkout."},
            contract_id=contract.id,
            simulated=(contract.mode == "demo"),
        )
        db.commit()

    return HTMLResponse(
        content="""
        <html>
          <body style="font-family:sans-serif; text-align:center; padding:50px; background:#fef2f2;">
            <h1 style="color:#991b1b;">Escrow Funding Cancelled</h1>
            <p>You cancelled the authorization on PayPal. The contract has been cancelled.</p>
          </body>
        </html>
        """
    )


@router.post("/{contract_id}/milestones/{idx}/submit", response_model=MilestoneOutcome)
def submit_milestone(
    contract_id: str,
    idx: int,
    payload: MilestoneSubmit,
    db: Session = Depends(get_db)
):
    """
    Submit a Python solution for a milestone.
    Runs isolated sandbox tests, captures approved funds, and dispatches payout.
    """
    try:
        outcome = settle_milestone(
            db=db,
            contract_id=contract_id,
            milestone_idx=idx,
            code=payload.code
        )
        return outcome
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except InvalidStateTransitionError as state_err:
        raise HTTPException(status_code=400, detail=str(state_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Settlement error: {exc}")


@router.post("/{contract_id}/cancel", response_model=ContractResponse)
def cancel_contract(contract_id: str, db: Session = Depends(get_db)):
    """
    Buyer cancellation: voids remaining hold if funded, or marks cancelled if awaiting funding.
    """
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    provider = get_paypal_provider(contract.mode)
    is_simulated = (contract.mode == "demo")

    if contract.status == ContractStatus.FUNDED.value:
        if contract.paypal_authorization_id:
            try:
                provider.void_authorization(
                    authorization_id=contract.paypal_authorization_id,
                    request_id=f"buyer-void-{contract.id}"
                )
                append_event(
                    db,
                    event_type="AUTHORIZATION_VOIDED",
                    payload={"authorization_id": contract.paypal_authorization_id, "reason": "Buyer cancellation"},
                    contract_id=contract.id,
                    simulated=is_simulated
                )
            except Exception as exc:
                append_event(
                    db,
                    event_type="VOID_ERROR",
                    payload={"error": str(exc)},
                    contract_id=contract.id,
                    simulated=is_simulated
                )

        transition_contract(contract.status, ContractStatus.VOIDED)
        contract.status = ContractStatus.VOIDED.value
        append_event(
            db,
            event_type="CONTRACT_VOIDED",
            payload={"reason": "Cancelled by buyer."},
            contract_id=contract.id,
            simulated=is_simulated
        )

    elif contract.status == ContractStatus.AWAITING_FUNDING.value:
        transition_contract(contract.status, ContractStatus.CANCELLED)
        contract.status = ContractStatus.CANCELLED.value
        append_event(
            db,
            event_type="CONTRACT_CANCELLED",
            payload={"reason": "Cancelled by buyer before funding."},
            contract_id=contract.id,
            simulated=is_simulated
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel contract in status '{contract.status}'."
        )

    db.commit()
    db.refresh(contract)
    return format_contract_response(contract)
