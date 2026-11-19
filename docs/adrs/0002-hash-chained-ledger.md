# ADR 0002: Hash-Chained Event Ledger & Digital Receipts

## Status
Accepted

## Context
Settlement decisions (captures, voids, verifier passes, arbiter vetos) must be auditable and tamper-evident. If a database is maliciously modified or an administrator alters state, the tamper must be immediately detectable.

## Decision
1. Maintain an immutable, append-only event table `events` per contract.
2. Every event computes:
   `event_hash = SHA256(prev_event_hash || sequence || event_type || canonical_payload)`.
3. The genesis event links to `0000000000000000000000000000000000000000000000000000000000000000`.
4. Finalized milestones produce an Ed25519 digital receipt over RFC 8785 canonical JSON derived from the contract's master key.

## Consequences
- Any alteration to past event payloads invalidates all subsequent hashes in the chain.
- Receipts can be independently audited by customers, workers, and third parties without access to PayLap's infrastructure.
