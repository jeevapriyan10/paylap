import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, require_principal
from app.config import settings
from app.db import get_db
from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract, Event, WebhookDelivery, WebhookEndpoint
from app.services.webhooks import (
    deliver_webhook_sync,
    is_safe_webhook_url,
)
from app.state import ContractStatus

logger = logging.getLogger("paylap.webhooks.api")

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


class CreateEndpointRequest(BaseModel):
    url: str
    events_filter: Optional[List[str]] = None


class EndpointResponse(BaseModel):
    id: str
    url: str
    is_active: bool
    events_filter: Optional[List[str]]
    created_at: str
    secret: Optional[str] = None  # Returned only upon creation


# --- Outbound Endpoints Management ---


@router.post("/endpoints", response_model=EndpointResponse)
def create_webhook_endpoint(
    payload: CreateEndpointRequest,
    principal: Principal = Depends(require_principal("webhooks:manage")),
    db: Session = Depends(get_db),
):
    """Register a new outbound webhook endpoint. Returns the signing secret once."""
    # SSRF verification
    is_safe, err = is_safe_webhook_url(payload.url, allow_test=(settings.PAYLAP_ENV == "test"))
    if not is_safe:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook URL: {err}",
        )

    raw_secret = f"whsec_{secrets.token_hex(24)}"
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    endpoint = WebhookEndpoint(
        id=generate_id("ep"),
        org_id=principal.org_id,
        url=payload.url,
        secret_hash=secret_hash,
        is_active=True,
        events_filter=payload.events_filter,
        created_at=now,
        updated_at=now,
    )
    db.add(endpoint)
    db.commit()

    return EndpointResponse(
        id=endpoint.id,
        url=endpoint.url,
        is_active=endpoint.is_active,
        events_filter=endpoint.events_filter,
        created_at=endpoint.created_at.isoformat(),
        secret=raw_secret,
    )


@router.get("/endpoints", response_model=List[EndpointResponse])
def list_webhook_endpoints(
    principal: Principal = Depends(require_principal("webhooks:manage")),
    db: Session = Depends(get_db),
):
    """List registered webhook endpoints for the current organization."""
    endpoints = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.org_id == principal.org_id)).all()

    return [
        EndpointResponse(
            id=ep.id,
            url=ep.url,
            is_active=ep.is_active,
            events_filter=ep.events_filter,
            created_at=ep.created_at.isoformat(),
            secret=None,
        )
        for ep in endpoints
    ]


@router.delete("/endpoints/{endpoint_id}")
def delete_webhook_endpoint(
    endpoint_id: str,
    principal: Principal = Depends(require_principal("webhooks:manage")),
    db: Session = Depends(get_db),
):
    """Delete a webhook endpoint."""
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.org_id == principal.org_id,
        )
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    db.delete(endpoint)
    db.commit()
    return {"status": "deleted", "id": endpoint_id}


@router.post("/endpoints/{endpoint_id}/test")
def test_webhook_endpoint(
    endpoint_id: str,
    principal: Principal = Depends(require_principal("webhooks:manage")),
    db: Session = Depends(get_db),
):
    """Dispatch a test ping webhook delivery."""
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.org_id == principal.org_id,
        )
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    now = datetime.now(timezone.utc)
    deliv = WebhookDelivery(
        id=generate_id("del"),
        org_id=principal.org_id,
        endpoint_id=endpoint.id,
        event_id=f"test_evt_{secrets.token_hex(8)}",
        event_type="TEST_PING",
        payload={
            "type": "TEST_PING",
            "message": "PayLap webhook connectivity test",
            "timestamp": now.isoformat(),
        },
        status="PENDING",
        attempt_count=0,
        next_retry_at=now,
        created_at=now,
    )
    db.add(deliv)
    db.commit()

    success = deliver_webhook_sync(db, deliv)
    return {
        "delivery_id": deliv.id,
        "success": success,
        "status": deliv.status,
        "response_status": deliv.response_status,
        "response_body": deliv.response_body,
    }


# --- Inbound PayPal Webhooks Ingestion ---

# In-memory deduplication cache for rapid check; also backed by DB query
_INGESTED_PAYPAL_EVENTS: set[str] = set()


@router.post("/paypal/{environment}")
async def ingest_paypal_webhook(
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Inbound PayPal webhook ingestion with deduplication and contradiction detection.
    Never blindly mutates state on contradictions; flags needs_attention=True.
    """
    if environment not in ("simulated", "sandbox", "live"):
        raise HTTPException(status_code=400, detail="Invalid environment")

    body_bytes = await request.body()
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    pp_event_id = payload.get("id")
    if not pp_event_id:
        raise HTTPException(status_code=400, detail="Missing event id in webhook payload")

    # 1. Deduplication
    if pp_event_id in _INGESTED_PAYPAL_EVENTS:
        return {"status": "duplicate", "event_id": pp_event_id}

    # Also check if event already recorded in DB
    existing_event = db.scalar(
        select(Event).where(
            Event.event_type == "PAYPAL_WEBHOOK_RECEIVED",
            Event.payload["paypal_event_id"].as_string() == pp_event_id,
        )
    )
    if existing_event:
        _INGESTED_PAYPAL_EVENTS.add(pp_event_id)
        return {"status": "duplicate", "event_id": pp_event_id}

    _INGESTED_PAYPAL_EVENTS.add(pp_event_id)

    event_type = payload.get("event_type", "UNKNOWN")
    resource = payload.get("resource", {})

    # Extract associated IDs
    order_id = resource.get("id") if "CHECKOUT.ORDER" in event_type else None
    auth_id = resource.get("id") if "PAYMENT.AUTHORIZATION" in event_type else None
    if not order_id and not auth_id:
        # Check custom_id or supplementary_data
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")

    # Find affected contract
    contract = None
    if order_id:
        contract = db.scalar(select(Contract).where(Contract.paypal_order_id == order_id))
    elif auth_id:
        contract = db.scalar(select(Contract).where(Contract.paypal_authorization_id == auth_id))

    if not contract:
        logger.info(f"PayPal webhook {pp_event_id} ({event_type}) received for untracked resource")
        return {"status": "ignored", "reason": "No matching contract found"}

    now = datetime.now(timezone.utc)

    # 2. Contradiction Detection
    # If PayPal sends VOIDED / DENIED on a contract that is FUNDED or COMPLETED:
    contradiction = False
    contradiction_reason = None

    if event_type in ("PAYMENT.AUTHORIZATION.VOIDED", "CHECKOUT.ORDER.VOIDED"):
        if contract.status in (ContractStatus.FUNDED.value, ContractStatus.COMPLETED.value):
            contradiction = True
            contradiction_reason = f"PayPal reported {event_type} but contract is locally {contract.status}"

    elif event_type == "PAYMENT.CAPTURE.DENIED":
        contradiction = True
        contradiction_reason = "PayPal reported capture was DENIED for authorized payment"

    if contradiction:
        logger.warning(f"CONTRADICTION DETECTED on contract {contract.id}: {contradiction_reason}")
        contract.needs_attention = True
        contract.updated_at = now

        append_event(
            db,
            event_type="CONTRADICTION_DETECTED",
            payload={
                "paypal_event_id": pp_event_id,
                "paypal_event_type": event_type,
                "reason": contradiction_reason,
                "contract_status": contract.status,
            },
            contract_id=contract.id,
            org_id=contract.org_id,
            simulated=(environment == "simulated"),
        )
        db.commit()
        return {"status": "received", "action": "contradiction_flagged", "event_id": pp_event_id}

    # Standard Ingestion
    append_event(
        db,
        event_type="PAYPAL_WEBHOOK_RECEIVED",
        payload={
            "paypal_event_id": pp_event_id,
            "paypal_event_type": event_type,
            "contract_id": contract.id,
        },
        contract_id=contract.id,
        org_id=contract.org_id,
        simulated=(environment == "simulated"),
    )
    db.commit()

    return {"status": "received", "event_id": pp_event_id}
