# PayLap Documentation

**PayLap** is an open-source, multi-tenant settlement engine and web application for **"pay on verified delivery"**.

## Core Philosophy

- **Verified-Delivery Payment Holds**: Funds are authorized directly on the customer's own PayPal Business account using PayPal Orders v2 (`AUTHORIZE`). PayLap **never** custodies money.
- **Deterministic Multi-Stage Verifiers**: Deliverables are verified automatically using deterministic sandboxes, public tests, and hidden test commitments.
- **Fail-Closed LLM Arbiter**: AI reviewers (Gemini) operate in a strictly constrained veto-only capacity. An LLM may veto passing work on safety or policy grounds, but can **never** grant payment.
- **Cryptographic Receipts**: Every settlement decision produces an Ed25519-signed, SHA-256 hash-chained digital receipt that anyone can verify offline without network access.
- **Strict Multi-Tenancy**: Tenant isolation is enforced via PostgreSQL Row-Level Security (RLS) with unbypassable runtime roles.

## Navigation

- [Quickstart Guide](quickstart.md): Get up and running with PayLap in under 5 minutes.
- [Core Concepts](concepts.md): Understand contracts, milestones, holds, and verifiers.
- [System Architecture](architecture.md): Database RLS, event ledger, sandbox runner, and arbiter design.
- [Receipts & Cryptography](receipts.md): Specification of RFC 8785 canonical JSON and Ed25519 receipts.
- [Threat Model](threat_model.md): Adversarial defense invariants and Red Team Arena.
- [Python SDK & MCP](sdk_mcp.md): Python SDK reference and Model Context Protocol agent tools.
- [Architecture Decision Records (ADRs)](adrs/0001-postgresql-rls.md): Key technical decisions.
