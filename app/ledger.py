import hashlib
import json
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.db import set_tenant_org
from app.ids import generate_id
from app.models import Contract, Event, OrgAuditLog, utc_now

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
    """
    Append a new event to the hash-chained, tamper-evident ledger.
    Serializes concurrent appends on the same contract via PostgreSQL transaction advisory lock.
    """
    if contract_id:
        # Acquire transaction-scoped advisory lock on hashtext(contract_id)
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:cid))"),
            {"cid": contract_id}
        )

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
    """
    Verify the cryptographic integrity of the append-only event hash chain.
    Returns (is_valid, error_message, broken_seq).
    """
    query = select(Event).order_by(Event.seq.asc())
    if contract_id:
        query = query.where(Event.contract_id == contract_id)

    events = db.scalars(query).all()
    if not events:
        return True, None, None

    expected_prev = (
        hashlib.sha256(f"paylap:genesis:{contract_id}".encode("utf-8")).hexdigest()
        if contract_id
        else GENESIS_PREV_HASH
    )

    for idx, evt in enumerate(events, start=1):
        if evt.seq != idx:
            return False, f"Sequence gap at seq {evt.seq} (expected {idx})", evt.seq

        if evt.prev_hash != expected_prev:
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


# ==============================================================================
# PER-ORGANIZATION AUDIT LOG HASH CHAIN
# ==============================================================================

def compute_org_audit_hash(
    prev_hash: str,
    seq: int,
    action: str,
    actor_id: Optional[str],
    details: Optional[Dict[str, Any]],
    org_id: str,
    created_at_iso: str
) -> str:
    """Compute deterministic SHA-256 hash for org audit log entry."""
    canonical_dict = {
        "action": action,
        "actor_id": actor_id,
        "created_at": created_at_iso,
        "details": details or {},
        "org_id": org_id,
        "seq": seq,
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    content = f"{prev_hash}{canonical_json}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def append_org_audit_log(
    db: Session,
    org_id: str,
    action: str,
    actor_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> OrgAuditLog:
    """
    Append an entry to the tamper-evident org audit log hash chain.
    Serializes concurrent appends on the same organization via transaction advisory lock.
    """
    # Advisory lock on the org's audit log
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"org_audit:{org_id}"}
    )

    last_entry = db.scalar(
        select(OrgAuditLog).where(OrgAuditLog.org_id == org_id).order_by(OrgAuditLog.seq.desc()).limit(1)
    )

    if last_entry is None:
        seq = 1
        prev_hash = hashlib.sha256(f"paylap:org_genesis:{org_id}".encode("utf-8")).hexdigest()
    else:
        seq = last_entry.seq + 1
        prev_hash = last_entry.event_hash

    created_at = utc_now()
    created_at_iso = created_at.isoformat()

    entry_hash = compute_org_audit_hash(
        prev_hash=prev_hash,
        seq=seq,
        action=action,
        actor_id=actor_id,
        details=details,
        org_id=org_id,
        created_at_iso=created_at_iso,
    )

    entry = OrgAuditLog(
        id=generate_id("aud"),
        org_id=org_id,
        seq=seq,
        action=action,
        actor_id=actor_id,
        details=details or {},
        prev_hash=prev_hash,
        event_hash=entry_hash,
        created_at=created_at,
    )
    db.add(entry)
    db.flush()
    return entry


def verify_org_audit_chain(db: Session, org_id: str) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Verify the cryptographic integrity of an organization's audit log hash chain.
    Returns (is_valid, error_message, broken_seq).
    """
    entries = db.scalars(
        select(OrgAuditLog).where(OrgAuditLog.org_id == org_id).order_by(OrgAuditLog.seq.asc())
    ).all()

    if not entries:
        return True, None, None

    expected_prev = hashlib.sha256(f"paylap:org_genesis:{org_id}".encode("utf-8")).hexdigest()

    for idx, entry in enumerate(entries, start=1):
        if entry.seq != idx:
            return False, f"Sequence gap at seq {entry.seq} (expected {idx})", entry.seq

        if entry.prev_hash != expected_prev:
            return False, f"Broken link at seq {entry.seq}", entry.seq

        calc_hash = compute_org_audit_hash(
            prev_hash=entry.prev_hash,
            seq=entry.seq,
            action=entry.action,
            actor_id=entry.actor_id,
            details=entry.details,
            org_id=entry.org_id,
            created_at_iso=entry.created_at.isoformat(),
        )
        if calc_hash != entry.event_hash:
            return False, f"Corrupted hash at seq {entry.seq}", entry.seq

        expected_prev = entry.event_hash

    return True, None, None
