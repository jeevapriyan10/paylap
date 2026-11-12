import hashlib
import hmac
import json
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.config import settings
from app.ledger import compute_event_hash
from app.models import Contract, Event, utc_now
from app.schemas import cents_to_usd_str
from app.services.policy import mask_email


def canonical_json_dumps(data: Any) -> str:
    """Deterministic JSON serialization with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_receipt_signature(receipt_dict: Dict[str, Any], secret: str) -> str:
    """Compute HMAC-SHA256 hex digest over canonical JSON of receipt excluding signature field."""
    payload_to_sign = {k: v for k, v in receipt_dict.items() if k != "signature"}
    canonical_bytes = canonical_json_dumps(payload_to_sign).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()


def generate_receipt(contract: Contract, db: Session) -> Dict[str, Any]:
    """
    Generate a self-contained, tamper-evident cryptographic receipt for a contract.
    Contains contract summary, milestone outcomes, complete event trail, and HMAC-SHA256 signature.
    Worker email is masked and hidden tests are never included.
    """
    secret, key_id = settings.receipt_signing_info

    # Collect milestones (excluding hidden test definitions)
    milestones_data = [
        {
            "idx": m.idx,
            "title": m.title,
            "amount_cents": m.amount_cents,
            "amount_usd": cents_to_usd_str(m.amount_cents),
            "verifier_type": getattr(m, "verifier_type", "python_code") or "python_code",
            "status": m.status,
            "attempts": m.attempts,
            "capture_id": m.capture_id,
            "payout_batch_id": m.payout_batch_id,
            "paid_at": m.paid_at.isoformat() if m.paid_at else None,
        }
        for m in sorted(contract.milestones, key=lambda x: x.idx)
    ]

    # Collect contract event trail
    events = (
        db.query(Event)
        .filter(Event.contract_id == contract.id)
        .order_by(Event.seq.asc())
        .all()
    )

    events_data = [
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

    # Verify event hashes within receipt
    events_valid = True
    for e in events_data:
        recalc_hash = compute_event_hash(
            prev_hash=e["prev_hash"],
            event_type=e["type"],
            payload=e["payload"],
            contract_id=e["contract_id"],
            simulated=e["simulated"],
            created_at_iso=e["created_at"],
        )
        if recalc_hash != e["hash"]:
            events_valid = False
            break

    settled_at = None
    if contract.status in ("COMPLETED", "VOIDED"):
        settled_at = contract.updated_at.isoformat() if contract.updated_at else None

    receipt: Dict[str, Any] = {
        "schema_version": "1.0",
        "contract_id": contract.id,
        "title": contract.title,
        "buyer_id": contract.buyer_id,
        "worker_id": contract.worker_id,
        "worker_email": mask_email(contract.worker_email),
        "total_cents": contract.total_cents,
        "total_usd": cents_to_usd_str(contract.total_cents),
        "currency": contract.currency,
        "status": contract.status,
        "mode": contract.mode,
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "settled_at": settled_at,
        "hidden_commitment": getattr(contract, "hidden_commitment", None),
        "milestones": milestones_data,
        "events": events_data,
        "event_hash_chain_valid": events_valid,
        "key_id": key_id,
        "issued_at": utc_now().isoformat(),
    }

    # Compute signature
    signature = compute_receipt_signature(receipt, secret)
    receipt["signature"] = signature

    return receipt


def verify_receipt(receipt_data: Dict[str, Any], db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Cryptographically verify a receipt payload:
    1. Recompute HMAC-SHA256 signature using canonical JSON representation.
    2. Verify cryptographic hash of every event in the event trail.
    3. If DB is provided, verify matching record exists.
    """
    secret, _ = settings.receipt_signing_info

    signature = receipt_data.get("signature")
    if not signature:
        return {
            "valid": False,
            "signature_valid": False,
            "chain_valid": False,
            "contract_id": receipt_data.get("contract_id"),
            "status": receipt_data.get("status"),
            "details": "Receipt is missing 'signature' field.",
        }

    # 1. Verify HMAC signature
    expected_sig = compute_receipt_signature(receipt_data, secret)
    signature_valid = hmac.compare_digest(str(signature), expected_sig)

    # 2. Verify event hashes
    events = receipt_data.get("events", [])
    chain_valid = True
    chain_error = None

    for idx, e in enumerate(events):
        try:
            recalc_hash = compute_event_hash(
                prev_hash=e.get("prev_hash", ""),
                event_type=e.get("type", ""),
                payload=e.get("payload", {}),
                contract_id=e.get("contract_id"),
                simulated=e.get("simulated", False),
                created_at_iso=e.get("created_at", ""),
            )
            if recalc_hash != e.get("hash"):
                chain_valid = False
                chain_error = f"Event hash mismatch at sequence {e.get('seq', idx)}."
                break
        except Exception as exc:
            chain_valid = False
            chain_error = f"Malformed event at index {idx}: {exc}"
            break

    # 3. Optional DB cross-check
    db_match = True
    if db is not None:
        contract_id = receipt_data.get("contract_id")
        contract = db.query(Contract).filter(Contract.id == contract_id).first()
        if not contract:
            db_match = False
            chain_error = f"Contract '{contract_id}' not found in local database."
        elif contract.status != receipt_data.get("status"):
            db_match = False
            chain_error = f"Status mismatch: DB has '{contract.status}', receipt has '{receipt_data.get('status')}'."

    is_valid = signature_valid and chain_valid and db_match

    if is_valid:
        details = "Receipt is cryptographically authentic and untampered."
    else:
        details_list = []
        if not signature_valid:
            details_list.append("HMAC signature verification failed (payload tampered or wrong key).")
        if not chain_valid:
            details_list.append(chain_error or "Event hash chain verification failed.")
        if not db_match:
            details_list.append(chain_error or "Database cross-reference check failed.")
        details = " ".join(details_list)

    return {
        "valid": is_valid,
        "signature_valid": signature_valid,
        "chain_valid": chain_valid,
        "contract_id": receipt_data.get("contract_id"),
        "status": receipt_data.get("status"),
        "details": details,
    }
