"""
Organization Management Router: API Keys, Webhooks, and Policy Aliases.
Supports /v1/org endpoints for frontend, SDK, and third-party integrations.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal, require_principal
from app.db import get_db
from app.routers.auth import CreateApiKeyRequest, create_api_key, list_api_keys, revoke_api_key
from app.routers.webhooks import (
    CreateEndpointRequest,
    create_webhook_endpoint,
    delete_webhook_endpoint,
    list_webhook_endpoints,
    test_webhook_endpoint,
)

router = APIRouter(prefix="/v1/org", tags=["Organization Management"])


class OrgWebhookCreateRequest(BaseModel):
    url: str
    event_types: Optional[List[str]] = None
    events_filter: Optional[List[str]] = None


# ==============================================================================
# API KEYS (/v1/org/api-keys)
# ==============================================================================

@router.get("/api-keys")
def get_org_api_keys(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """List registered API keys for the current organization."""
    return list_api_keys(principal=principal, db=db)


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
def post_org_api_keys(
    payload: CreateApiKeyRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Generate a new scoped API key for the current organization."""
    return create_api_key(payload=payload, principal=principal, db=db)


@router.delete("/api-keys/{key_id}")
def delete_org_api_key(
    key_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Revoke an API key."""
    return revoke_api_key(key_id=key_id, principal=principal, db=db)


# ==============================================================================
# WEBHOOKS (/v1/org/webhooks)
# ==============================================================================

@router.get("/webhooks")
def get_org_webhooks(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """List configured webhook endpoints for the current organization."""
    # Ensure user has permission
    if not principal.is_api_key or principal.has_scope("webhooks:manage"):
        return list_webhook_endpoints(principal=principal, db=db)
    raise HTTPException(status_code=403, detail="Missing permission: webhooks:manage")


@router.post("/webhooks", status_code=status.HTTP_201_CREATED)
def post_org_webhooks(
    payload: OrgWebhookCreateRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Register a new outbound webhook endpoint."""
    events = payload.event_types or payload.events_filter
    req = CreateEndpointRequest(url=payload.url, events_filter=events)
    return create_webhook_endpoint(payload=req, principal=principal, db=db)


@router.delete("/webhooks/{endpoint_id}")
def delete_org_webhook(
    endpoint_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Delete a registered webhook endpoint."""
    return delete_webhook_endpoint(endpoint_id=endpoint_id, principal=principal, db=db)


@router.post("/webhooks/{endpoint_id}/ping")
def ping_org_webhook(
    endpoint_id: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Dispatch a test ping to the specified webhook endpoint."""
    return test_webhook_endpoint(endpoint_id=endpoint_id, principal=principal, db=db)
