import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, set_tenant_org
from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract, Event, Milestone, Organization, ShareToken
from app.routers.auth import Principal, get_current_principal
from app.schemas import (
    ContractCreate,
    ContractResponse,
    MilestoneOutcome,
    MilestoneResponse,
    MilestoneSubmit,
    PaginatedContractsResponse,
    cents_to_usd_str,
)
from app.services.idempotency import check_idempotency_key, store_idempotency_key
from app.services.pagination import decode_cursor, encode_cursor
from app.services.paypal_factory import get_provider
from app.services.policy import evaluate_spend_policy, mask_email
from app.services.settlement import settle_milestone
from app.services.state_tokens import create_signed_funding_state, verify_signed_funding_state
from app.state import (
    ContractStatus,
    InvalidStateTransitionError,
    transition_contract,
)

router = APIRouter(prefix="/v1/contracts", tags=["Contracts"])


def sanitize_verifier_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strictly sanitize verifier configuration so hidden tests are never leaked."""
    if not config:
        return None
    sanitized = dict(config)
    for sensitive_key in ("hidden_tests", "hidden_checks", "secret", "private", "private_tests"):
        sanitized.pop(sensitive_key, None)
    return sanitized


def format_contract_response(contract: Contract) -> ContractResponse:
    milestones_resp = [
        MilestoneResponse(
            id=m.id,
            idx=m.sequence,
            title=m.title,
            amount_cents=m.amount_cents,
            amount_usd=cents_to_usd_str(m.amount_cents),
            spec=m.spec,
            public_tests=m.public_tests,
            verifier_type=m.verifier_type or "python_code",
            verifier_config=sanitize_verifier_config(m.verifier_config),
            status=m.status,
            attempts=m.attempts_count,
            capture_id=m.capture_id,
            payout_batch_id=m.payout_id,
            payout_status=m.payout_status,
            paid_at=m.paid_at,
        )
        for m in sorted(contract.milestones, key=lambda x: x.sequence)
    ]

    effective_max_attempts = (
        contract.metadata_json.get("max_attempts", 2)
        if contract.metadata_json and isinstance(contract.metadata_json, dict)
        else 2
    )

    return ContractResponse(
        id=contract.id,
        title=contract.title,
        buyer_id=contract.org_id,
        worker_id=contract.worker_id,
        worker_email=contract.worker_email,
        total_cents=contract.total_cents,
        total_usd=cents_to_usd_str(contract.total_cents),
        currency=contract.currency,
        status=contract.status,
        environment=contract.environment,
        paypal_order_id=contract.paypal_order_id,
        paypal_authorization_id=contract.paypal_authorization_id,
        authorization_expires_at=contract.authorization_expires_at,
        approve_url=contract.approve_url,
        mode=contract.mode,
        max_attempts=effective_max_attempts,
        capture_strategy=contract.capture_strategy or "partial",
        external_reference=contract.external_reference,
        metadata=contract.metadata_json,
        hidden_commitment=contract.hidden_commitment,
        milestones=milestones_resp,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


@router.post("", response_model=ContractResponse, status_code=201)
def create_contract(
    payload: ContractCreate,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    Create a new milestone contract and initialize PayPal escrow order.
    Enforces Row-Level Security, spend policies, hidden test commitments, and idempotency.
    """
    principal.require_scope("contracts:write")
    set_tenant_org(db, principal.org_id)

    # Environment class validation for API keys
    if principal.is_api_key:
        if payload.environment == "live" and principal.env_class != "live":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Test API keys cannot create live contracts",
            )
        if payload.environment != "live" and principal.env_class == "live":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Live API keys cannot create non-live contracts",
            )

    # Check idempotency
    payload_dict = payload.model_dump(mode="json")
    cached = check_idempotency_key(
        db=db,
        org_id=principal.org_id,
        idempotency_key=idempotency_key,
        method="POST",
        path="/v1/contracts",
        body=payload_dict,
    )
    if cached:
        c_code, c_body, c_headers = cached
        return JSONResponse(status_code=c_code, content=c_body, headers=c_headers)

    # Deadline validation
    now = datetime.now(timezone.utc)
    contract_days = None
    if payload.deadline_at:
        deadline = (
            payload.deadline_at if payload.deadline_at.tzinfo else payload.deadline_at.replace(tzinfo=timezone.utc)
        )
        if deadline <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contract deadline must be in the future",
            )
        max_days = settings.PAYLAP_MAX_CONTRACT_DAYS
        if deadline > now + timedelta(days=max_days):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Contract deadline exceeds maximum allowed days ({max_days})",
            )
        contract_days = (deadline - now).days

    contract_id = generate_id("ctr")
    is_simulated = payload.environment == "simulated"

    # Compute amounts
    milestone_cents = [(m.amount_minor or 0) for m in payload.milestones]
    total_cents = sum(milestone_cents)

    # Hidden test commitment hashes (stored internally, never returned in responses)
    hidden_commitments = []
    for m in payload.milestones:
        h_str = (m.hidden_tests or "").strip()
        if h_str:
            h_commit = hashlib.sha256(h_str.encode("utf-8")).hexdigest()
        else:
            h_commit = None
        hidden_commitments.append(h_commit)

    overall_h_commit = (
        hashlib.sha256("".join(c for c in hidden_commitments if c).encode("utf-8")).hexdigest()
        if any(hidden_commitments)
        else None
    )

    # Spend policy evaluation
    allowed, violations = evaluate_spend_policy(
        db=db,
        org_id=principal.org_id,
        environment=payload.environment,
        total_cents=total_cents,
        milestones=[m.model_dump() for m in payload.milestones],
        worker_email=payload.worker_email,
        deadline_at=payload.deadline_at,
    )

    if not allowed:
        blocked_contract = Contract(
            id=contract_id,
            org_id=principal.org_id,
            title=payload.title,
            worker_id=payload.worker_id,
            worker_email=payload.worker_email,
            environment=payload.environment,
            total_cents=total_cents,
            currency="USD",
            status=ContractStatus.BLOCKED.value,
            deadline_at=payload.deadline_at,
            external_reference=payload.external_reference,
            metadata_json=payload.metadata,
            capture_strategy=payload.capture_strategy,
            hidden_commitment=overall_h_commit,
        )
        db.add(blocked_contract)
        db.commit()

        append_event(
            db,
            event_type="POLICY_BLOCKED",
            payload={
                "contract_id": contract_id,
                "buyer_id": principal.org_id,
                "worker_email": mask_email(payload.worker_email),
                "total_cents": total_cents,
                "violations": violations,
            },
            contract_id=contract_id,
            org_id=principal.org_id,
            simulated=is_simulated,
        )
        db.commit()

        return JSONResponse(
            status_code=422,
            content={
                "error": "Policy violation",
                "violations": violations,
                "contract_id": contract_id,
                "detail": {
                    "error": "Policy violation",
                    "violations": violations,
                },
            },
        )

    # Initialize Contract record
    contract = Contract(
        id=contract_id,
        org_id=principal.org_id,
        title=payload.title,
        worker_id=payload.worker_id,
        worker_email=payload.worker_email,
        environment=payload.environment,
        total_cents=total_cents,
        currency="USD",
        status=ContractStatus.CREATED.value,
        deadline_at=payload.deadline_at,
        external_reference=payload.external_reference,
        metadata_json={**(payload.metadata or {}), "max_attempts": payload.max_attempts},
        capture_strategy=payload.capture_strategy,
        hidden_commitment=overall_h_commit,
    )
    db.add(contract)

    # Add milestones
    for idx, (m_spec, cents, h_commit) in enumerate(
        zip(payload.milestones, milestone_cents, hidden_commitments), start=1
    ):
        milestone = Milestone(
            id=generate_id("mst"),
            org_id=principal.org_id,
            contract_id=contract_id,
            sequence=idx,
            title=m_spec.title,
            amount_cents=cents,
            spec=m_spec.spec,
            public_tests=m_spec.public_tests,
            hidden_tests=m_spec.hidden_tests,  # Stored securely, never exposed in API responses
            verifier_type=m_spec.verifier_type or "python_code",
            verifier_config=m_spec.verifier_config,
            hidden_commitment_hash=h_commit,
            status="PENDING",
            attempts_count=0,
            max_attempts=payload.max_attempts,
        )
        db.add(milestone)

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
            "environment": payload.environment,
        },
        contract_id=contract.id,
        org_id=principal.org_id,
        simulated=is_simulated,
    )

    # Resolve provider
    org = db.scalar(select(Organization).where(Organization.id == principal.org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    provider = get_provider(org, payload.environment, db)

    if payload.environment == "simulated":
        # Auto-fund simulated order
        order_res = provider.create_escrow_order(
            contract_id=contract.id,
            amount_cents=total_cents,
            return_url=f"{settings.PAYLAP_PUBLIC_URL}/v1/contracts/{contract.id}/funding/return",
            cancel_url=f"{settings.PAYLAP_PUBLIC_URL}/v1/contracts/{contract.id}/funding/cancel",
        )
        contract.paypal_order_id = order_res.get("order_id")

        append_event(
            db,
            event_type="ORDER_CREATED",
            payload={"order_id": contract.paypal_order_id, "amount_cents": total_cents},
            contract_id=contract.id,
            org_id=principal.org_id,
            simulated=True,
        )

        auth_res = provider.authorize_order(order_id=contract.paypal_order_id or "")
        contract.paypal_authorization_id = auth_res.get("authorization_id")

        append_event(
            db,
            event_type="ORDER_AUTHORIZED",
            payload={"authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            org_id=principal.org_id,
            simulated=True,
        )

        transition_contract(contract.status, ContractStatus.FUNDED)
        contract.status = ContractStatus.FUNDED.value

        append_event(
            db,
            event_type="CONTRACT_FUNDED",
            payload={"contract_id": contract.id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            org_id=principal.org_id,
            simulated=True,
        )
        db.commit()

    else:
        # Sandbox or Live: Create PayPal order with signed state token URLs
        state_token = create_signed_funding_state(contract.id, principal.org_id)
        return_url = f"{settings.PAYLAP_PUBLIC_URL}/v1/contracts/{contract.id}/funding/return?state={state_token}"
        cancel_url = f"{settings.PAYLAP_PUBLIC_URL}/v1/contracts/{contract.id}/funding/cancel?state={state_token}"

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
                org_id=principal.org_id,
                simulated=False,
            )
            db.commit()

        except Exception as exc:
            append_event(
                db,
                event_type="ORDER_CREATION_FAILED",
                payload={"error": str(exc)},
                contract_id=contract.id,
                org_id=principal.org_id,
                simulated=False,
            )
            db.commit()
            raise HTTPException(status_code=502, detail=f"Failed to create PayPal escrow order: {exc}")

    db.refresh(contract)
    resp = format_contract_response(contract)

    if idempotency_key:
        store_idempotency_key(
            db=db,
            org_id=principal.org_id,
            idempotency_key=idempotency_key,
            method="POST",
            path="/v1/contracts",
            body=payload_dict,
            response_code=201,
            response_body=resp.model_dump(mode="json"),
        )

    return resp


@router.get("", response_model=PaginatedContractsResponse)
def list_contracts(
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    environment: Optional[str] = Query(None, description="Filter by environment"),
    status: Optional[str] = Query(None, description="Filter by status"),
    worker_id: Optional[str] = Query(None, description="Filter by worker_id"),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """
    List contracts with cursor-based pagination and filtering.
    Enforces Row-Level Security for the authenticated organization.
    """
    principal.require_scope("contracts:read")
    set_tenant_org(db, principal.org_id)

    stmt = select(Contract).where(Contract.org_id == principal.org_id)

    if environment:
        stmt = stmt.where(Contract.environment == environment)
    if status:
        stmt = stmt.where(Contract.status == status)
    if worker_id:
        stmt = stmt.where(Contract.worker_id == worker_id)

    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        if cursor_dt and cursor_id:
            stmt = stmt.where(
                (Contract.created_at < cursor_dt) | ((Contract.created_at == cursor_dt) & (Contract.id < cursor_id))
            )

    stmt = stmt.order_by(Contract.created_at.desc(), Contract.id.desc()).limit(limit + 1)
    results = db.scalars(stmt).all()

    has_more = len(results) > limit
    items = results[:limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_cursor(last_item.created_at, last_item.id)

    return PaginatedContractsResponse(
        items=[format_contract_response(c) for c in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/{contract_id}")
def get_contract_detail(
    contract_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get detailed contract information including milestones (never hidden_tests)
    and recent ledger events.
    """
    principal.require_scope("contracts:read")
    set_tenant_org(db, principal.org_id)

    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == principal.org_id))
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    recent_events = db.scalars(
        select(Event)
        .where(Event.contract_id == contract_id, Event.org_id == principal.org_id)
        .order_by(Event.seq.desc())
        .limit(20)
    ).all()

    return {
        "contract": format_contract_response(contract),
        "recent_events": [
            {
                "seq": e.seq,
                "type": e.event_type,
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
    state: Optional[str] = Query(None, description="Signed funding state token"),
    db: Session = Depends(get_db),
):
    """
    Redirect endpoint called by PayPal when buyer approves authorization.
    Verifies cryptographic signed state token and transitions contract to FUNDED.
    """
    if not state:
        return HTMLResponse(status_code=400, content="<h3>Missing funding state token</h3>")

    is_valid, state_cid, org_id = verify_signed_funding_state(state)
    if not is_valid or state_cid != contract_id or not org_id:
        return HTMLResponse(status_code=400, content="<h3>Invalid or expired funding state token</h3>")

    set_tenant_org(db, org_id)
    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == org_id))
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found.")

    if contract.status == ContractStatus.FUNDED.value:
        return HTMLResponse(
            content="""
            <html>
              <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0fdf4;">
                <h1 style="color:#166534;">Payment Hold Already Active</h1>
                <p>The verified-delivery payment hold for this contract is already active.</p>
              </body>
            </html>
            """
        )

    order_id = token or contract.paypal_order_id
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order ID token.")

    org = db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    provider = get_provider(org, contract.environment, db)

    try:
        auth_res = provider.authorize_order(order_id=order_id, request_id=f"auth-{contract.id}")
        contract.paypal_authorization_id = auth_res.get("authorization_id")
        if auth_res.get("expiration_time"):
            try:
                contract.authorization_expires_at = datetime.fromisoformat(
                    auth_res["expiration_time"].replace("Z", "+00:00")
                )
            except Exception:
                pass

        append_event(
            db,
            event_type="ORDER_AUTHORIZED",
            payload={"order_id": order_id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            org_id=contract.org_id,
            simulated=False,
        )

        transition_contract(contract.status, ContractStatus.FUNDED)
        contract.status = ContractStatus.FUNDED.value

        append_event(
            db,
            event_type="CONTRACT_FUNDED",
            payload={"contract_id": contract.id, "authorization_id": contract.paypal_authorization_id},
            contract_id=contract.id,
            org_id=contract.org_id,
            simulated=False,
        )
        db.commit()

    except Exception as exc:
        append_event(
            db,
            event_type="AUTHORIZATION_FAILED",
            payload={"order_id": order_id, "error": str(exc)},
            contract_id=contract.id,
            org_id=contract.org_id,
            simulated=False,
        )
        db.commit()
        return HTMLResponse(
            status_code=500,
            content=f"""
            <html>
              <body style="font-family:sans-serif; text-align:center; padding:50px; background:#fef2f2;">
                <h1 style="color:#991b1b;">Authorization Failed</h1>
                <p>Error authorizing PayPal payment hold: {exc}</p>
              </body>
            </html>
            """,
        )

    return HTMLResponse(
        content="""
        <html>
          <head><title>PayLap Hold Active</title></head>
          <body style="font-family:sans-serif; text-align:center; padding:50px; background:#f0fdf4;">
            <h1 style="color:#166534;">Payment Hold Authorized Successfully!</h1>
            <p style="font-size:18px; color:#15803d;">
              Funds are securely placed on hold in your PayPal business account.
            </p>
            <p style="color:#4b5563;">
              The worker agent may now submit work against milestone specifications.<br>
              You may safely close this browser window.
            </p>
          </body>
        </html>
        """
    )


@router.get("/{contract_id}/funding/cancel", response_class=HTMLResponse)
def funding_cancel_callback(
    contract_id: str,
    state: Optional[str] = Query(None, description="Signed funding state token"),
    db: Session = Depends(get_db),
):
    """Called when buyer cancels approval at PayPal checkout."""
    if state:
        is_valid, state_cid, org_id = verify_signed_funding_state(state)
        if is_valid and state_cid == contract_id and org_id:
            set_tenant_org(db, org_id)
            contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == org_id))
            if contract and contract.status == ContractStatus.AWAITING_FUNDING.value:
                transition_contract(contract.status, ContractStatus.CANCELLED)
                contract.status = ContractStatus.CANCELLED.value
                append_event(
                    db,
                    event_type="CONTRACT_CANCELLED",
                    payload={"contract_id": contract.id, "reason": "Buyer cancelled at PayPal checkout."},
                    contract_id=contract.id,
                    org_id=contract.org_id,
                    simulated=(contract.environment == "simulated"),
                )
                db.commit()

    return HTMLResponse(
        content="""
        <html>
          <body style="font-family:sans-serif; text-align:center; padding:50px; background:#fef2f2;">
            <h1 style="color:#991b1b;">Payment Hold Cancelled</h1>
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
    principal: Principal = Depends(get_current_principal),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    Submit work for a milestone.
    Runs injection scan, isolated verifiers, fail-closed LLM arbiter veto layer, and capture/payouts.
    """
    principal.require_scope("contracts:write")
    set_tenant_org(db, principal.org_id)

    # Check idempotency
    submit_dict = payload.model_dump(mode="json")
    cached = check_idempotency_key(
        db=db,
        org_id=principal.org_id,
        idempotency_key=idempotency_key,
        method="POST",
        path=f"/v1/contracts/{contract_id}/milestones/{idx}/submit",
        body=submit_dict,
    )
    if cached:
        c_code, c_body, c_headers = cached
        return JSONResponse(status_code=c_code, content=c_body, headers=c_headers)

    # Verify contract exists for this org
    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == principal.org_id))
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    try:
        outcome = settle_milestone(db=db, contract_id=contract_id, milestone_idx=idx, code=payload.code)

        if idempotency_key:
            store_idempotency_key(
                db=db,
                org_id=principal.org_id,
                idempotency_key=idempotency_key,
                method="POST",
                path=f"/v1/contracts/{contract_id}/milestones/{idx}/submit",
                body=submit_dict,
                response_code=200,
                response_body=outcome.model_dump(mode="json"),
            )

        return outcome
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except InvalidStateTransitionError as state_err:
        raise HTTPException(status_code=400, detail=str(state_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Settlement error: {exc}")


@router.post("/{contract_id}/cancel", response_model=ContractResponse)
def cancel_contract(
    contract_id: str,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """
    Buyer cancellation: voids remaining hold if funded, or marks cancelled if awaiting funding.
    """
    principal.require_scope("contracts:write")
    set_tenant_org(db, principal.org_id)

    # Check idempotency
    cached = check_idempotency_key(
        db=db,
        org_id=principal.org_id,
        idempotency_key=idempotency_key,
        method="POST",
        path=f"/v1/contracts/{contract_id}/cancel",
        body=None,
    )
    if cached:
        c_code, c_body, c_headers = cached
        return JSONResponse(status_code=c_code, content=c_body, headers=c_headers)

    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == principal.org_id))
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    org = db.scalar(select(Organization).where(Organization.id == principal.org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    provider = get_provider(org, contract.environment, db)
    is_simulated = contract.environment == "simulated"

    if contract.status == ContractStatus.FUNDED.value:
        if contract.paypal_authorization_id:
            try:
                provider.void_authorization(
                    authorization_id=contract.paypal_authorization_id, request_id=f"buyer-void-{contract.id}"
                )
                append_event(
                    db,
                    event_type="AUTHORIZATION_VOIDED",
                    payload={"authorization_id": contract.paypal_authorization_id, "reason": "Buyer cancellation"},
                    contract_id=contract.id,
                    org_id=principal.org_id,
                    simulated=is_simulated,
                )
            except Exception as exc:
                append_event(
                    db,
                    event_type="VOID_ERROR",
                    payload={"error": str(exc)},
                    contract_id=contract.id,
                    org_id=principal.org_id,
                    simulated=is_simulated,
                )

        transition_contract(contract.status, ContractStatus.VOIDED)
        contract.status = ContractStatus.VOIDED.value
        append_event(
            db,
            event_type="CONTRACT_VOIDED",
            payload={"reason": "Cancelled by buyer."},
            contract_id=contract.id,
            org_id=principal.org_id,
            simulated=is_simulated,
        )

    elif contract.status == ContractStatus.AWAITING_FUNDING.value:
        transition_contract(contract.status, ContractStatus.CANCELLED)
        contract.status = ContractStatus.CANCELLED.value
        append_event(
            db,
            event_type="CONTRACT_CANCELLED",
            payload={"reason": "Cancelled by buyer before funding."},
            contract_id=contract.id,
            org_id=principal.org_id,
            simulated=is_simulated,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Cannot cancel contract in status '{contract.status}'.")

    db.commit()
    db.refresh(contract)
    resp = format_contract_response(contract)

    if idempotency_key:
        store_idempotency_key(
            db=db,
            org_id=principal.org_id,
            idempotency_key=idempotency_key,
            method="POST",
            path=f"/v1/contracts/{contract_id}/cancel",
            body=None,
            response_code=200,
            response_body=resp.model_dump(mode="json"),
        )

    return resp


@router.get("/{contract_id}/receipt")
def get_contract_receipt(
    contract_id: str, principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Generate and return a signed, tamper-evident cryptographic receipt for the contract."""
    from app.services.receipts import generate_receipt

    principal.require_scope("receipts:read")
    set_tenant_org(db, principal.org_id)

    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == principal.org_id))
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    return generate_receipt(contract, db)


@router.post("/{contract_id}/share")
def create_receipt_share_token(
    contract_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Generate an unguessable public share token for this contract's receipt.
    Requires receipts:read permission.
    """
    principal.require_scope("receipts:read")
    set_tenant_org(db, principal.org_id)

    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.org_id == principal.org_id))
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")

    token_str = f"shr_{secrets.token_hex(20)}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=30)

    token_record = ShareToken(
        id=generate_id("tok"),
        org_id=principal.org_id,
        contract_id=contract.id,
        token=token_str,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(token_record)
    db.commit()

    return {
        "share_token": token_str,
        "share_url": f"{settings.PAYLAP_PUBLIC_URL}/v1/receipts/{token_str}",
        "expires_at": expires_at.isoformat(),
        "contract_id": contract.id,
    }
