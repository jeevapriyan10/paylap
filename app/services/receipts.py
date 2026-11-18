import base64
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.ids import generate_id
from app.ledger import compute_event_hash
from app.models import Contract, Event
from app.schemas import cents_to_usd_str
from app.services.policy import mask_email


def rfc8785_canonical_json(data: Any) -> bytes:
    """
    Deterministic RFC 8785 (JSON Canonicalization Scheme) serialization:
    - Object keys sorted lexicographically
    - Whitespace removed between tokens
    - UTF-8 encoded without BOM
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def get_receipt_signing_key() -> Tuple[ed25519.Ed25519PrivateKey, str, str]:
    """
    Derives an Ed25519 private key from the primary active master key using HKDF (info='paylap-receipt-v2').
    Returns (private_key, base64_public_key, key_id).
    """
    key_id, master_bytes = settings.active_master_key
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"paylap-receipt-v2",
    )
    seed = hkdf.derive(master_bytes)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    pub_raw = private_key.public_key().public_bytes_raw()
    pub_b64 = base64.b64encode(pub_raw).decode("utf-8")
    return private_key, pub_b64, key_id


def generate_receipt(contract: Contract, db: Session) -> Dict[str, Any]:
    """
    Generate a self-contained, tamper-evident cryptographic receipt (Receipt v2) for a contract.
    Contains contract summary, milestones, complete event trail, chain head hash, and Ed25519 signature.
    Worker email is masked and hidden tests are never included.
    """
    private_key, signer_public_key, key_id = get_receipt_signing_key()

    # Collect milestones (excluding hidden test definitions)
    milestones_data = [
        {
            "idx": m.sequence,
            "title": m.title,
            "amount_minor": m.amount_cents,
            "amount_cents": m.amount_cents,
            "amount_usd": cents_to_usd_str(m.amount_cents),
            "status": m.status,
            "verifier_type": m.verifier_type or "python_code",
            "attempts": m.attempts_count,
            "capture_id": m.capture_id,
            "payout_batch_id": m.payout_id,
            "paid_at": m.paid_at.isoformat() if m.paid_at else None,
        }
        for m in sorted(contract.milestones, key=lambda x: x.sequence)
    ]

    # Collect contract event trail
    events = db.scalars(
        select(Event).where(Event.contract_id == contract.id).order_by(Event.seq.asc())
    ).all()

    events_data = [
        {
            "seq": e.seq,
            "type": e.event_type,
            "hash": e.event_hash,
            "prev_hash": e.prev_hash,
            "payload": e.payload,
            "simulated": e.simulated,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

    chain_head_hash = (
        events[-1].event_hash
        if events
        else hashlib.sha256(f"paylap:genesis:{contract.id}".encode("utf-8")).hexdigest()
    )

    completed_at = (
        contract.updated_at.isoformat()
        if contract.status in ("COMPLETED", "VOIDED") and contract.updated_at
        else None
    )

    masked_worker_email = mask_email(contract.worker_email)
    hidden_commitments = [
        m.hidden_commitment_hash for m in contract.milestones if m.hidden_commitment_hash
    ]

    receipt_payload: Dict[str, Any] = {
        "receipt_id": generate_id("rcpt"),
        "version": "2.0",
        "schema_version": "2.0",
        "contract_id": contract.id,
        "title": contract.title,
        "buyer_org_id": contract.org_id,
        "buyer_id": contract.org_id,
        "worker_id": contract.worker_id,
        "worker_email_masked": masked_worker_email,
        "worker_email": masked_worker_email,
        "total_amount_minor": contract.total_cents,
        "total_cents": contract.total_cents,
        "total_usd": cents_to_usd_str(contract.total_cents),
        "currency": contract.currency,
        "status": contract.status,
        "completed_at": completed_at,
        "milestones": milestones_data,
        "hidden_test_commitments": hidden_commitments,
        "events": events_data,
        "chain_head_hash": chain_head_hash,
        "signer_key_id": key_id,
        "signer_public_key": signer_public_key,
    }

    # Ed25519 signature over RFC 8785 canonical JSON
    canonical_bytes = rfc8785_canonical_json(receipt_payload)
    sig_raw = private_key.sign(canonical_bytes)
    receipt_payload["signature"] = base64.b64encode(sig_raw).decode("utf-8")

    return receipt_payload


def verify_receipt(receipt: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Offline verification of an Ed25519 digital receipt (v2).
    Validates canonical JSON, Ed25519 signature, and event hash chain replay.
    Returns (is_valid, error_message).
    """
    if not isinstance(receipt, dict):
        return False, "Receipt must be a JSON object"

    signature_b64 = receipt.get("signature")
    pubkey_b64 = receipt.get("signer_public_key")
    if not signature_b64 or not pubkey_b64:
        return False, "Receipt missing signature or signer_public_key"

    # 1. Verify Ed25519 signature
    payload_to_verify = {k: v for k, v in receipt.items() if k != "signature"}
    try:
        canonical_bytes = rfc8785_canonical_json(payload_to_verify)
        sig_bytes = base64.b64decode(signature_b64)
        pub_bytes = base64.b64decode(pubkey_b64)
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(sig_bytes, canonical_bytes)
    except Exception as exc:
        return False, f"Signature verification failed: {exc}"

    # 2. Verify event hash chain replay
    contract_id = receipt.get("contract_id")
    events = receipt.get("events", [])
    expected_prev = hashlib.sha256(f"paylap:genesis:{contract_id}".encode("utf-8")).hexdigest()

    for idx, e in enumerate(events, start=1):
        if e.get("seq") != idx:
            return False, f"Event sequence break at index {idx}: expected {idx}, got {e.get('seq')}"

        if e.get("prev_hash") != expected_prev:
            return False, f"Broken event hash link at seq {e.get('seq')}"

        recalc = compute_event_hash(
            prev_hash=e["prev_hash"],
            event_type=e["type"],
            payload=e["payload"],
            contract_id=contract_id,
            simulated=bool(e.get("simulated", False)),
            created_at_iso=e["created_at"],
        )
        if recalc != e.get("hash"):
            return False, f"Corrupted event hash at seq {e.get('seq')}"

        expected_prev = e["hash"]

    if events:
        if receipt.get("chain_head_hash") != events[-1]["hash"]:
            return False, "chain_head_hash mismatch with final event hash"

    return True, None
