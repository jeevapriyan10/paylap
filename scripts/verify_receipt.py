#!/usr/bin/env python3
"""
PayLap Offline Receipt Verifier.
A standalone, zero-network utility to cryptographically verify Ed25519 digital receipts (Receipt v2).

Usage:
    python scripts/verify_receipt.py path/to/receipt.json
    cat receipt.json | python scripts/verify_receipt.py -
"""

import base64
import hashlib
import json
import sys
from typing import Any, Dict, Optional, Tuple

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    ed25519 = None


def rfc8785_canonical_json(data: Any) -> bytes:
    """Deterministic JSON serialization matching RFC 8785."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_event_hash(
    prev_hash: str, event_type: str, payload: dict, contract_id: Optional[str], simulated: bool, created_at_iso: str
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


def verify_receipt(receipt: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Verify Ed25519 digital signature and event chain integrity."""
    if not isinstance(receipt, dict):
        return False, "Receipt must be a JSON object"

    signature_b64 = receipt.get("signature")
    pubkey_b64 = receipt.get("signer_public_key")
    if not signature_b64 or not pubkey_b64:
        return False, "Receipt missing 'signature' or 'signer_public_key'"

    # 1. Verify Ed25519 Signature over RFC 8785 canonical JSON
    payload_to_verify = {k: v for k, v in receipt.items() if k != "signature"}
    try:
        canonical_bytes = rfc8785_canonical_json(payload_to_verify)
        sig_bytes = base64.b64decode(signature_b64)
        pub_bytes = base64.b64decode(pubkey_b64)

        if ed25519 is None:
            return False, "cryptography library is required for Ed25519 signature verification"

        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        public_key.verify(sig_bytes, canonical_bytes)
    except Exception as exc:
        return False, f"Ed25519 signature verification failed: {exc}"

    # 2. Replay and verify event hash chain
    contract_id = receipt.get("contract_id")
    events = receipt.get("events", [])
    expected_prev = hashlib.sha256(f"paylap:genesis:{contract_id}".encode("utf-8")).hexdigest()

    for idx, e in enumerate(events, start=1):
        if e.get("seq") != idx:
            return False, f"Event sequence break at seq {e.get('seq')}: expected {idx}"

        if e.get("prev_hash") != expected_prev:
            return False, f"Broken event hash chain link at seq {e.get('seq')}"

        recalc_hash = compute_event_hash(
            prev_hash=e["prev_hash"],
            event_type=e["type"],
            payload=e["payload"],
            contract_id=contract_id,
            simulated=bool(e.get("simulated", False)),
            created_at_iso=e["created_at"],
        )
        if recalc_hash != e.get("hash"):
            return False, f"Corrupted event hash at seq {e.get('seq')}"

        expected_prev = e["hash"]

    if events:
        head_hash = receipt.get("chain_head_hash")
        if head_hash != events[-1]["hash"]:
            return False, f"chain_head_hash mismatch: expected {events[-1]['hash']}, got {head_hash}"

    return True, None


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_receipt.py <receipt.json | ->", file=sys.stderr)
        sys.exit(2)

    arg = sys.argv[1]
    if arg == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(arg, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as exc:
            print(f"[ERROR] Could not read receipt file '{arg}': {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        receipt_data = json.loads(raw)
    except Exception as exc:
        print(f"[ERROR] Invalid JSON in receipt: {exc}", file=sys.stderr)
        sys.exit(1)

    is_valid, err = verify_receipt(receipt_data)
    if is_valid:
        contract_id = receipt_data.get("contract_id")
        event_count = len(receipt_data.get("events", []))
        signer = receipt_data.get("signer_public_key")
        print("=================================================================")
        print(" PayLap Cryptographic Receipt Verification: SUCCESS")
        print("=================================================================")
        print(f" Contract ID:       {contract_id}")
        print(f" Receipt ID:        {receipt_data.get('receipt_id')}")
        print(f" Total Amount:      {receipt_data.get('total_amount_minor')} {receipt_data.get('currency', 'USD')}")
        print(f" Events Verified:   {event_count} (Genesis to Chain Head)")
        print(f" Signer Public Key: {signer[:16]}...{signer[-16:] if len(signer) > 32 else ''}")
        print(" Signature:         Ed25519 Verified OK")
        print("=================================================================")
        sys.exit(0)
    else:
        print("=================================================================", file=sys.stderr)
        print(" PayLap Cryptographic Receipt Verification: FAILED", file=sys.stderr)
        print("=================================================================", file=sys.stderr)
        print(f" Error: {err}", file=sys.stderr)
        print("=================================================================", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
