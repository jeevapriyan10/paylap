from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Contract, ShareToken
from app.services.receipts import generate_receipt

router = APIRouter(prefix="/v1/receipts", tags=["Receipts"])


@router.get("/{share_token}")
def get_public_shared_receipt(
    share_token: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Public verification endpoint to retrieve a cryptographic digital receipt via share token.
    No authentication required. Rate-limited by IP.
    Worker email is strictly masked; hidden tests are omitted.
    """
    now = datetime.now(timezone.utc)

    # Find valid unexpired share token
    token_record = db.scalar(
        select(ShareToken).where(
            ShareToken.token == share_token,
            ShareToken.expires_at > now,
        )
    )
    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared receipt not found or expired.",
        )

    # Set tenant context to allow reading this contract under forced RLS
    db.execute(
        text("SELECT set_config('app.current_org', :org_id, true)"),
        {"org_id": token_record.org_id},
    )

    contract = db.scalar(
        select(Contract).where(
            Contract.id == token_record.contract_id,
            Contract.org_id == token_record.org_id,
        )
    )
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract referenced by share token not found.",
        )

    return generate_receipt(contract, db)
