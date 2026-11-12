from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.ledger import verify_chain
from app.models import Event
from app.schemas import HealthResponse

from app.verifiers import list_available_verifiers

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """Health check returning runtime configuration, modes, and ledger integrity."""
    paypal_configured = bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET)
    is_valid, _, _ = verify_chain(db)

    return HealthResponse(
        status="ok",
        version="0.2.0",
        mode=settings.PAYLAP_MODE,
        payout_mode=settings.PAYLAP_PAYOUT_MODE,
        arbiter_mode=settings.resolved_arbiter_mode,
        paypal_configured=paypal_configured,
        ledger_chain_valid=is_valid,
        verifiers=list_available_verifiers(),
    )


@router.get("/policy")
def get_policy_endpoint() -> Dict[str, Any]:
    """Get active spend policy limits and masked allowlist."""
    from app.services.policy import get_policy_summary
    return get_policy_summary()


@router.get("/ledger/verify")
def verify_ledger_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Verify cryptographic integrity of the entire event ledger chain."""
    is_valid, error_msg, broken_seq = verify_chain(db)
    return {
        "valid": is_valid,
        "error": error_msg,
        "broken_seq": broken_seq,
    }


@router.get("/events")
def list_events(
    limit: int = Query(50, ge=1, le=500),
    contract_id: Optional[str] = None,
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """Query recent immutable ledger events."""
    query = db.query(Event)
    if contract_id:
        query = query.filter(Event.contract_id == contract_id)

    events = query.order_by(Event.seq.desc()).limit(limit).all()

    return [
        {
            "id": e.id,
            "contract_id": e.contract_id,
            "seq": e.seq,
            "type": e.type,
            "payload": e.payload,
            "simulated": e.simulated,
            "prev_hash": e.prev_hash,
            "hash": e.hash,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
