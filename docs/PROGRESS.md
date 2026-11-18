# PayLap Engineering Progress & Phase Tracking

This document tracks execution across all phases, recording exit gate validations, key architectural decisions, and open uncertainties.

---

## Phase Checklist & Exit Gates

- [x] **P0: Plan and Foundation**
  - [x] Branch `product-core` created
  - [x] Non-negotiable engineering rules documented in `docs/ENGINEERING_RULES.md`
  - [x] Progress tracking initialized in `docs/PROGRESS.md`
  - [x] Configuration model via `pydantic-settings` with all specified env variables and validation
  - [x] Startup validation for production (fails if master/secret keys are missing or < 32 bytes)
  - [x] Pinned dependencies in `requirements.txt`
  - [x] **Exit Gate**: Settings tests pass; rules and progress files exist. (Passed: 7/7 tests)

- [x] **P1: Database, Roles, and Row-Level Security (RLS)**
  - [x] PostgreSQL Docker Compose configuration with healthcheck
  - [x] Role initialization (`paylap_owner` schema owner/migrator, `paylap_app` runtime DML only, `NOBYPASSRLS`)
  - [x] SQLAlchemy 2.x declarative models with prefixed public IDs (`org_`, `usr_`, `key_`, `ctr_`, `mst_`, `evt_`)
  - [x] RLS policies enabled and forced on all tenant tables
  - [x] Org session context helper `org_session(org_id)` setting `app.current_org`
  - [x] Alembic baseline migration running as owner
  - [x] **Exit Gate**: Migration up/down/up and `alembic check` clean; RLS test proves zero rows without org and zero cross-org leaks; asserts runtime role has `rolbypassrls=false` and is not table owner. (Passed: 3/3 tests)

- [x] **P2: Auth, RBAC, and API Keys**
  - [x] `POST /v1/auth/signup`, `login`, `logout`, `GET /v1/auth/me`
  - [x] Argon2id password hashing (min length 12, common password blacklist check, rehash on login)
  - [x] Server-side sessions (256-bit random token, SHA-256 hash stored, 24h idle / 14d absolute timeout, HttpOnly/SameSite/Secure cookies)
  - [x] Double-submit CSRF cookie (`paylap_csrf` + `X-CSRF-Token`) for cookie auth unsafe methods; Bearer exempt
  - [x] Login throttling (5 failures per email+IP per 15 min -> 429 with `Retry-After`; constant-time equalized errors)
  - [x] RBAC permission matrix (`viewer`, `developer`, `admin`, `owner`)
  - [x] API keys (`pl_test_...` and `pl_live_...`, lookup ID + hashed secret, scoped permissions, environment class)
  - [x] Principal dependency resolving cookie or Bearer into an org-scoped session
  - [x] **Exit Gate**: Auth, CSRF, throttling, anti-enumeration, RBAC matrix, key-scope, and environment-class tests pass. (Passed: 6/6 tests)

- [x] **P3: Platform Plumbing**
  - [x] Request ID middleware (`X-Request-ID`)
  - [x] Standardized error format `{"error": {"type", "code", "message", "request_id", "details"}}` with no stack traces
  - [x] JSON logging with redaction filter (API keys, passwords, session tokens, PayPal credentials, Auth headers, hidden test strings)
  - [x] Token-bucket rate limiting per key and per IP
  - [x] Security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options)
  - [x] Strict CORS middleware restricted to `PAYLAP_CORS_ORIGINS`
  - [x] Request body size limits
  - [x] `/docs` and `/openapi.json` gated by `PAYLAP_ENABLE_DOCS`
  - [x] `/healthz` and `/readyz` probes
  - [x] Migration of all endpoints from `/api/*` to `/v1/*`
  - [x] **Exit Gate**: Error format, redaction filter (with planted sentinels), rate limiting, and health checks pass. (Passed: 5/5 tests)

- [x] **P4: PayPal Credentials, Environments, and Policy**
  - [x] Org BYO credentials encrypted with AES-256-GCM (12-byte random nonce, AAD `org_id:environment:field`, envelope `key_id.nonce.ciphertext`)
  - [x] Credentials CRUD endpoints and OAuth token verification
  - [x] Fixed PayPal base URLs per environment
  - [x] CLI command `rotate-master-key` and batch rotation service
  - [x] Provider factory `get_provider(org, environment)`
  - [x] Per-org spend policies (max task amount, daily spend cap, max milestones, worker allowlist, require hidden tests)
  - [x] **Exit Gate**: Encryption round-trip, wrong-AAD failure, key rotation, live-disabled-by-default, and policy enforcement tests pass. (Passed: 5/5 tests)

- [x] **P5: Contract Engine V1**
  - [x] Contract & milestone schemas with verifiers (`python_code`, `json_data`, `text_rules`)
  - [x] Hidden test commitment hashes recorded at creation and never exposed in public responses
  - [x] Prompt injection scanning with risk flags
  - [x] Settlement pipeline: scan -> verifiers -> arbiter -> pay or void
  - [x] Capture strategies (partial vs batch at end) and void fallback
  - [x] Signed state token for funding redirects
  - [x] Cursor-based pagination and filtering
  - [x] Idempotency-Key support with stored fingerprints and replayed headers
  - [x] Gemini arbiter client (veto-only, fail-closed, cached, hourly cap)
  - [x] Contract deadline expiry via fake-clock service helper
  - [x] **Exit Gate**: Simulated provider drives full milestone lifecycle, failing verifier never reaches arbiter, concurrency test proves no double-spend, fake clock proves deadline expiry, planted hidden test sentinel never leaks. (Passed: 7/7 tests, 33/33 total)

- [x] **P6: Ledger, Receipts, and Code Runner**
  - [x] Per-contract hash chain with PostgreSQL transaction advisory locks (`SELECT pg_advisory_xact_lock(hashtext(contract_id))`)
  - [x] Per-org `org_audit_log` hash chain for sensitive operations
  - [x] Ed25519 digital receipts (Receipt v2 over RFC 8785 canonical JSON derived via HKDF `paylap-receipt-v2`)
  - [x] Receipt share tokens (`shr_...`) and unauthenticated public verification endpoint `GET /v1/receipts/{share_token}`
  - [x] Standalone, zero-network offline receipt verification CLI `scripts/verify_receipt.py`
  - [x] Hardened `ProcessRunner` (static AST screening, scrubbed env, timeout killing) and `RemoteRunner` (TLS client)
  - [x] **Exit Gate**: 50 concurrent appends yield gapless valid chain; tampering detected; offline receipt verification passes; runner isolation proven. (Passed: 6/6 tests, 39/39 total)

- [x] **P7: Background Jobs, Webhooks, Reconciliation, Stream, Playground**
  - [x] Job scheduler with advisory lock leader election (`SELECT pg_try_advisory_lock(hashtext('paylap:job_leader'))`)
  - [x] Outbound webhooks with HMAC-SHA256 signatures (`PayLap-Signature`), exponential backoff schedule (1m, 5m, 30m, 2h, 5h), and strict SSRF protection
  - [x] Inbound PayPal webhook ingestion with deduplication and contradiction detection (flags `needs_attention=true` without state corruption)
  - [x] Daily and on-demand PayPal reconciliation (`POST /v1/reconcile`) detecting ledger discrepancies
  - [x] Org-scoped SSE `/v1/stream` with heartbeats (`: ping\n\n`), sequence cursors, and `Last-Event-ID` reconnection
  - [x] Red Team Arena 6 scenarios under `/v1/playground` (prompt injection bypass, AST escape, infinite loop, time-travel expiry, hidden test probe, concurrent race double-spend)
  - [x] Aggregated platform statistics (`GET /v1/org/stats`) and worker reputation (`GET /v1/workers/{worker_id}/stats`)
  - [x] **Exit Gate**: Webhook signatures, retry schedule, SSRF protection, inbound deduplication, reconciliation discrepancy tests, and 6/6 playground runs pass. (Passed: 9/9 tests, 48/48 total)

- [x] **P8: OpenAPI, CLI, and CI/CD Automation**
  - [x] OpenAPI export script and schema verification (`scripts/export_openapi.py` exporting to `docs/openapi.json`)
  - [x] Typer CLI tools in `app/cli.py` (`gen-master-key`, `create-user`, `migrate-check`, `seed-dev`, `rotate-master-key`, `reconcile`, `expire-now`)
  - [x] GitHub Actions workflow `.github/workflows/ci.yml` (ruff lint/format, mypy typecheck, pytest coverage >= 80% with PostgreSQL service container, bandit, pip-audit, gitleaks)
  - [x] Pre-commit configuration (`.pre-commit-config.yaml`) and Dependabot (`.github/dependabot.yml`)
  - [x] **Exit Gate**: Full test suite passes (142/142 tests passing) with 80% code coverage; ruff, mypy, bandit clean; CLI commands functional.

- [ ] **P9: Production Frontend (React + TypeScript + Vite)**
  - [ ] Web application with minimal, calm aesthetic and zero Tailwind / UI kits
  - [ ] Complete responsive layouts (360px to 1920px) and WCAG AA accessibility
  - [ ] Real data binding to all v1 endpoints (contracts, playground, policy, webhooks, keys, receipts)
  - [ ] In-browser WebCrypto receipt verification
  - [ ] Vitest unit tests and Playwright end-to-end tests
  - [ ] FastAPI static asset serving with SPA fallback
  - [ ] **Exit Gate**: Frontend lint, typecheck, unit tests, and Playwright smoke tests pass; served cleanly by FastAPI.

- [ ] **P10: Python SDK, MCP Server, and Documentation Site**
  - [ ] Typed `paylap` Python SDK with httpx
  - [ ] Official MCP server with standard tools
  - [ ] MkDocs Material documentation site (Quickstart, Concepts, Guides, Architecture, Threat Model, ADRs)
  - [ ] **Exit Gate**: `mkdocs --strict` builds; SDK and MCP test suites pass.

- [ ] **P11: Production Packaging, Release, and Final Verification**
  - [ ] Multi-stage production Dockerfile and `docker-compose.prod.yml`
  - [ ] Render.yaml demo deployment blueprint
  - [ ] GitHub release workflow
  - [ ] Fresh clone end-to-end smoke test
  - [ ] **Exit Gate**: Release build verified; final test suite, linter, and offline receipt checks pass.

---

## Decisions and Uncertainties

### Decisions
1. **Branching**: Created `product-core` as the active development branch based on `main` (which contains Stage 2 tagged work).
2. **Settings**: Migrating from primitive environment variables to a robust `pydantic-settings` model in `app/config.py` with strict startup validation.
3. **Database Layer**: Transitioning entirely to PostgreSQL 16 with Row-Level Security, dropping SQLite compatibility in production and development to ensure zero discrepancy in tenant isolation.
4. **AnyIO Backend**: Excluding `trio` in pytest configuration to prevent test errors on systems where `trio` is not installed, ensuring `asyncio` is the standard backend.
5. **Contract Engine Invariants**: Enforced strict architectural assertion `assert verif_res.passed is True` before invoking the LLM Arbiter; arbiter veto failures fail-closed without consuming submission attempts.
6. **Concurrency Protection**: Contract and milestone database rows are locked with `FOR UPDATE` during settlement; duplicate concurrent submissions return existing outcomes without repeating payment capture.
7. **Idempotency & Replay**: Idempotency keys verify SHA-256 request payload fingerprints and replay stored responses with the standard `Idempotent-Replayed: true` header.

### Uncertainties & Resolutions
- **PayPal Authorization Expiry Fields**: PayPal Orders v2 returns `expiration_time` inside the authorization object (ISO 8601). We will parse and store this as `authorization_expires_at`.
- **PayPal Inbound Webhooks**: Event types to handle include `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`. These serve strictly as corroborative evidence.
- **Gemini Structured Output**: The Gemini arbiter will use the official Google GenAI API endpoint with JSON response schema enforcement and temperature 0.0.
