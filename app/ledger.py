import hashlib
import json
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ids import generate_id
from app.models import Contract, Event, utc_now

GENESIS_PREV_HASH = "0" * 64


def compute_event_hash(
    prev_hash: str,
    event_type: str,
    payload: dict,
    contract_id: Optional[str],
    simulated: bool,
    created_at_iso: str
) -> str:
    """Compute deterministic SHA-256 hash using sorted canonical JSON representation."""
    canonical_dict = {
        "contract_id": contract_id,
        "created_at": created_at_iso,
        "payload": payload,
        "simulated": simulated,
        "type": event_type,
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    content = f"{prev_hash}{canonical_json}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def append_event(
    db: Session,
    event_type: str,
    payload: dict,
    contract_id: Optional[str] = None,
    org_id: Optional[str] = None,
    simulated: bool = False
) -> Event:
    """Append a new event to the hash-chained, tamper-evident ledger."""
    # Resolve org_id from contract if not provided
    resolved_org_id = org_id
    if not resolved_org_id and contract_id:
        ctr = db.scalar(select(Contract).where(Contract.id == contract_id))
        if ctr:
            resolved_org_id = ctr.org_id

    if not resolved_org_id:
        resolved_org_id = "org_system"

    # Per-contract hash chain sequence
    if contract_id:
        last_event = db.scalar(
            select(Event).where(Event.contract_id == contract_id).order_by(Event.seq.desc()).limit(1)
        )
    else:
        last_event = db.scalar(
            select(Event).order_by(Event.seq.desc()).limit(1)
        )

    if last_event is None:
        seq = 1
        # Genesis hash per contract: sha256("paylap:genesis:" + contract_id)
        if contract_id:
            prev_hash = hashlib.sha256(f"paylap:genesis:{contract_id}".encode("utf-8")).hexdigest()
        else:
            prev_hash = GENESIS_PREV_HASH
    else:
        seq = last_event.seq + 1
        prev_hash = last_event.event_hash

    created_at = utc_now()
    created_at_iso = created_at.isoformat()

    event_payload = dict(payload)
    if simulated:
        event_payload["simulated"] = True

    event_hash = compute_event_hash(
        prev_hash=prev_hash,
        event_type=event_type,
        payload=event_payload,
        contract_id=contract_id,
        simulated=simulated,
        created_at_iso=created_at_iso
    )

    event = Event(
        id=generate_id("evt"),
        org_id=resolved_org_id,
        contract_id=contract_id,
        seq=seq,
        event_type=event_type,
        payload=event_payload,
        prev_hash=prev_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, contract_id: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[int]]:
    """Verify hash chain integrity."""
    query = select(Event).order_by(Event.seq.asc())
    if contract_id:
        query = query.where(Event.contract_id == contract_id)

    events = db.scalars(query).all()
    if not events:
        return True, None, None

    expected_prev = None
    for evt in events:
        if expected_prev is None:
            expected_prev = evt.prev_hash
        elif evt.prev_hash != expected_prev:
            return False, f"Broken link at seq {evt.seq}", evt.seq

        calc_hash = compute_event_hash(
            prev_hash=evt.prev_hash,
            event_type=evt.event_type,
            payload=evt.payload,
            contract_id=evt.contract_id,
            simulated=evt.simulated,
            created_at_iso=evt.created_at.isoformat()
        )
        if calc_hash != evt.event_hash:
            return False, f"Corrupted hash at seq {evt.seq}", evt.seq

        expected_prev = evt.event_hash

    return True, None, None
