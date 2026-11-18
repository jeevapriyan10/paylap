from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.ids import generate_id
from app.models import Organization, OrgPayPalCredential
from app.routers.auth import Principal, get_current_principal
from app.services.crypto import decrypt_credential, encrypt_credential
from app.services.paypal_factory import PAYPAL_LIVE_BASE_URL, PAYPAL_SANDBOX_BASE_URL

router = APIRouter(prefix="/v1/org/paypal", tags=["Organization PayPal Credentials"])


class PayPalCredentialsPayload(BaseModel):
    client_id: str = Field(..., min_length=4)
    client_secret: str = Field(..., min_length=8)


@router.put("/{environment}")
def set_paypal_credentials(
    environment: str,
    payload: PayPalCredentialsPayload,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if environment not in ("sandbox", "live"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Credentials can only be set for 'sandbox' or 'live' environments",
        )

    # Permission check: admin or owner
    if not principal.is_api_key and principal.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or owner can manage organization PayPal credentials",
        )

    # Encrypt secret with AES-256-GCM envelope
    encrypted_secret = encrypt_credential(
        plaintext=payload.client_secret,
        org_id=principal.org_id,
        environment=environment,
        field="client_secret",
    )

    now = datetime.now(timezone.utc)
    cred = db.scalar(
        select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == principal.org_id,
            OrgPayPalCredential.environment == environment,
        )
    )
    if cred:
        cred.client_id = payload.client_id
        cred.encrypted_client_secret = encrypted_secret
        cred.verified_at = None
        cred.updated_at = now
    else:
        cred = OrgPayPalCredential(
            id=generate_id("cred"),
            org_id=principal.org_id,
            environment=environment,
            client_id=payload.client_id,
            encrypted_client_secret=encrypted_secret,
            created_at=now,
            updated_at=now,
        )
        db.add(cred)

    db.commit()

    # Client secret is strictly NEVER returned in the response
    return {
        "org_id": principal.org_id,
        "environment": environment,
        "client_id": cred.client_id,
        "verified_at": cred.verified_at,
        "updated_at": cred.updated_at,
    }


@router.get("/{environment}")
def get_paypal_credentials_info(
    environment: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if environment not in ("sandbox", "live"):
        raise HTTPException(status_code=422, detail="Environment must be 'sandbox' or 'live'")

    cred = db.scalar(
        select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == principal.org_id,
            OrgPayPalCredential.environment == environment,
        )
    )
    if not cred:
        raise HTTPException(status_code=404, detail=f"No credentials configured for '{environment}'")

    # Client secret is never returned
    return {
        "org_id": principal.org_id,
        "environment": environment,
        "client_id": cred.client_id,
        "verified_at": cred.verified_at,
        "created_at": cred.created_at,
        "updated_at": cred.updated_at,
    }


@router.delete("/{environment}")
def delete_paypal_credentials(
    environment: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if not principal.is_api_key and principal.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Only admin or owner can delete credentials")

    cred = db.scalar(
        select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == principal.org_id,
            OrgPayPalCredential.environment == environment,
        )
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credentials not found")

    db.delete(cred)
    db.commit()
    return {"status": "deleted", "environment": environment}


@router.post("/{environment}/verify")
def verify_paypal_credentials(
    environment: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if environment not in ("sandbox", "live"):
        raise HTTPException(status_code=422, detail="Environment must be 'sandbox' or 'live'")

    cred = db.scalar(
        select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == principal.org_id,
            OrgPayPalCredential.environment == environment,
        )
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credentials not found")

    secret = decrypt_credential(
        cred.encrypted_client_secret,
        org_id=principal.org_id,
        environment=environment,
        field="client_secret",
    )

    base_url = PAYPAL_LIVE_BASE_URL if environment == "live" else PAYPAL_SANDBOX_BASE_URL
    token_url = f"{base_url}/v1/oauth2/token"

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                token_url,
                auth=(cred.client_id, secret),
                data={"grant_type": "client_credentials"},
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"PayPal verification failed: {resp.text}",
                )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to PayPal API: {exc}")

    now = datetime.now(timezone.utc)
    cred.verified_at = now
    db.commit()

    return {
        "status": "verified",
        "verified_at": cred.verified_at,
        "environment": environment,
    }
