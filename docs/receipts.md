# Receipts & Cryptography

Every finalized milestone and contract settlement produces a tamper-proof digital receipt (**Receipt v2**).

## Canonical Representation (RFC 8785)

Receipt JSON payloads are normalized using RFC 8785 JSON Canonicalization Scheme (JCS):
- Lexicographical key sorting
- IEEE 754 floating-point serialization
- UTF-8 encoding without whitespace separators: `,` and `:`

## Cryptographic Structure

```json
{
  "version": "receipt-v2",
  "receipt_hash": "<SHA-256 hex string of canonical content>",
  "public_key": "<Base64-encoded 32-byte Ed25519 public key>",
  "ed25519_signature": "<Base64-encoded 64-byte Ed25519 signature>",
  "content": {
    "contract_id": "ctr_...",
    "milestone_id": "mst_...",
    "event": "MILESTONE_SETTLED",
    "amount_cents": 2500,
    "currency": "USD",
    "status": "COMPLETED",
    "worker_id": "usr_...",
    "worker_email_masked": "a***e@example.com",
    "timestamp": "2026-11-19T08:00:00Z"
  }
}
```

## Offline Verification

Receipts can be verified without any network or database connection:

```bash
python scripts/verify_receipt.py receipt.json
```

Or programmatically in Python:

```python
from paylap import verify_receipt_data

receipt = json.load(open("receipt.json"))
is_valid = verify_receipt_data(receipt)
print(f"Receipt Valid: {is_valid}")
```

Or inside any modern web browser using standard WebCrypto:

```javascript
const pubKey = await crypto.subtle.importKey(
  "raw",
  base64ToBytes(receipt.public_key),
  { name: "Ed25519" },
  false,
  ["verify"]
);
const valid = await crypto.subtle.verify(
  "Ed25519",
  pubKey,
  base64ToBytes(receipt.ed25519_signature),
  new TextEncoder().encode(receipt.receipt_hash)
);
```
