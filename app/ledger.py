import hashlib
import json
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models import Event, utc_now

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
    simulated: bool = False
) -> Event:
    """Append a new event to the hash-chained, tamper-evident ledger."""
    last_event = db.query(Event).order_by(Event.seq.desc()).first()

    if last_event is None:
        seq = 1
        prev_hash = GENESIS_PREV_HASH
    else:
        seq = last_event.seq + 1
        prev_hash = last_event.hash

    created_at = utc_now()
    created_at_iso = created_at.isoformat()

    event_hash = compute_event_hash(
        prev_hash=prev_hash,
        event_type=event_type,
        payload=payload,
        contract_id=contract_id,
        simulated=simulated,
        created_at_iso=created_at_iso
    )

    event = Event(
        contract_id=contract_id,
        seq=seq,
        type=event_type,
        payload=payload,
        simulated=simulated,
        prev_hash=prev_hash,
        hash=event_hash,
        created_at=created_at
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def verify_chain(db: Session) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Verify the integrity of the append-only event log.
    Returns (is_valid, error_message, broken_seq).
    """
    events = db.query(Event).order_by(Event.seq.asc()).all()
    if not events:
        return True, None, None

    expected_prev_hash = GENESIS_PREV_HASH
    expected_seq = 1

    for event in events:
        if event.seq != expected_seq:
            return (
                False,
                f"Sequence break: expected seq {expected_seq}, found {event.seq}",
                event.seq,
            )

        if event.prev_hash != expected_prev_hash:
            return (
                False,
                f"Broken link at seq {event.seq}: prev_hash mismatch. Expected {expected_prev_hash}, found {event.prev_hash}",
                event.seq,
            )

        created_at_iso = (
            event.created_at.isoformat()
            if hasattr(event.created_at, "isoformat")
            else str(event.created_at)
        )
        recomputed = compute_event_hash(
            prev_hash=expected_prev_hash,
            event_type=event.type,
            payload=event.payload,
            contract_id=event.contract_id,
            simulated=event.simulated,
            created_at_iso=created_at_iso,
        )

        if recomputed != event.hash:
            return (
                False,
                f"Tampered event at seq {event.seq}: stored hash {event.hash} does not match recomputed {recomputed}",
                event.seq,
            )

        expected_prev_hash = event.hash
        expected_seq += 1

    return True, None, None
