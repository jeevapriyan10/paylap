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

- [ ] **P1: Database, Roles, and Row-Level Security (RLS)**
  - [ ] PostgreSQL Docker Compose configuration with healthcheck
  - [ ] Role initialization (`paylap_owner` schema owner/migrator, `paylap_app` runtime DML only, `NOBYPASSRLS`)
  - [ ] SQLAlchemy 2.x declarative models with prefixed public IDs (`org_`, `usr_`, `key_`, `ctr_`, `mst_`, `evt_`)
  - [ ] RLS policies enabled and forced on all tenant tables
  - [ ] Org session context helper `org_session(org_id)` setting `app.current_org`
  - [ ] Alembic baseline migration running as owner
  - [ ] **Exit Gate**: Migration up/down/up and `alembic check` clean; RLS test proves zero rows without org and zero cross-org leaks; asserts runtime role has `rolbypassrls=false` and is not table owner.

- [ ] **P2: Auth, RBAC, and API Keys**
  - [ ] `POST /v1/auth/signup`, `login`, `logout`, `GET /v1/auth/me`
  - [ ] Argon2id password hashing (min length 12, common password blacklist check, rehash on login)
  - [ ] Server-side sessions (256-bit random token, SHA-256 hash stored, 24h idle / 14d absolute timeout, HttpOnly/SameSite/Secure cookies)
  - [ ] Double-submit CSRF cookie (`paylap_csrf` + `X-CSRF-Token`) for cookie auth unsafe methods; Bearer exempt
  - [ ] Login throttling (5 failures per email+IP per 15 min -> 429 with `Retry-After`; constant-time equalized errors)
  - [ ] RBAC permission matrix (`viewer`, `developer`, `admin`, `owner`)
  - [ ] API keys (`pl_test_...` and `pl_live_...`, lookup ID + hashed secret, scoped permissions, environment class)
  - [ ] Principal dependency resolving cookie or Bearer into an org-scoped session
  - [ ] **Exit Gate**: Auth, CSRF, throttling, anti-enumeration, RBAC matrix, key-scope, and environment-class tests pass.

- [ ] **P3: Platform Plumbing**
  - [ ] Request ID middleware (`X-Request-ID`)
  - [ ] Standardized error format `{"error": {"type", "code", "message", "request_id", "details"}}` with no stack traces
  - [ ] JSON logging with redaction filter (API keys, passwords, session tokens, PayPal credentials, Auth headers, hidden test strings)
  - [ ] Token-bucket rate limiting per key and per IP
  - [ ] Security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options)
  - [ ] Strict CORS middleware restricted to `PAYLAP_CORS_ORIGINS`
  - [ ] Request body size limits
  - [ ] `/docs` and `/openapi.json` gated by `PAYLAP_ENABLE_DOCS`
  - [ ] `/healthz` and `/readyz` probes
  - [ ] Migration of all endpoints from `/api/*` to `/v1/*`
  - [ ] **Exit Gate**: Error format, redaction filter (with planted sentinels), rate limiting, and health checks pass.

- [ ] **P4: PayPal Credentials, Environments, and Policy**
  - [ ] Org BYO credentials encrypted with AES-256-GCM (12-byte random nonce, AAD `org_id:environment:field`, envelope `key_id.nonce.ciphertext`)
  - [ ] Credentials CRUD endpoints and OAuth token verification
  - [ ] Fixed PayPal base URLs per environment
  - [ ] CLI command `rotate-master-key`
  - [ ] Provider factory `get_provider(org, environment)`
  - [ ] Per-org spend policies (max task amount, daily spend cap, max milestones, worker allowlist, require hidden tests)
  - [ ] **Exit Gate**: Encryption round-trip, wrong-AAD failure, key rotation, live-disabled-by-default, and policy enforcement tests pass.

- [ ] **P5: Contract Engine V1**
  - [ ] Contract & milestone schemas with verifiers (`python_code`, `json_data`, `text_rules`)
  - [ ] Hidden test commitment hashes recorded at creation
  - [ ] Prompt injection scanning with risk flags
  - [ ] Settlement pipeline: scan -> verifiers -> arbiter -> pay or void
  - [ ] Capture strategies (partial vs batch at end) and void fallback
  - [ ] Signed state token for funding redirects
  - [ ] Cursor-based pagination and filtering
  - [ ] Idempotency-Key support with stored fingerprints
  - [ ] Gemini arbiter client (veto-only, fail-closed, cached, hourly cap)
  - [ ] **Exit Gate**: Full milestone lifecycle per environment with simulated provider, concurrency double-spend prevention test, fake-clock expiry test, and leak sentinel test pass.

- [ ] **P6: Ledger, Receipts, and Code Runner**
  - [ ] Per-contract hash chain with PostgreSQL transaction advisory locks
  - [ ] Per-org `org_audit_log` hash chain
  - [ ] Ed25519 digital receipts (receipt v2 canonical JSON signing)
  - [ ] Receipt share tokens and public verification endpoint
  - [ ] Offline receipt verification script `scripts/verify_receipt.py`
  - [ ] Hardened `ProcessRunner` and isolated `RemoteRunner`
  - [ ] **Exit Gate**: 50 concurrent appends yield gapless valid chain; tampering detected; offline receipt verification passes; runner isolation proven.

- [ ] **P7: Background Jobs, Webhooks, Reconciliation, Stream, Playground**
  - [ ] Job scheduler with advisory lock leader election
  - [ ] Outbound webhooks with HMAC signatures, exponential backoff, and SSRF protection
  - [ ] Inbound PayPal webhook ingestion and contradiction detection
  - [ ] Daily and on-demand PayPal reconciliation
  - [ ] Org-scoped SSE `/v1/stream` with heartbeats and reconnection
  - [ ] Red Team Arena 6 scenarios under `/v1/playground`
  - [ ] Org-level statistics and worker reputation
  - [ ] **Exit Gate**: Webhook signatures, retry schedule, SSRF protection, inbound deduplication, reconciliation discrepancy tests, and 6/6 playground runs pass.

- [ ] **P8: OpenAPI, CLI, and CI/CD Automation**
  - [ ] OpenAPI export script and schema verification
  - [ ] CLI tools (`gen-master-key`, `create-user`, `migrate-check`, `seed-dev`, `reconcile`, `expire-now`)
  - [ ] GitHub Actions workflow (linting, mypy, pytest coverage >= 80%, bandit, pip-audit, gitleaks)
  - [ ] Pre-commit configuration and Dependabot
  - [ ] **Exit Gate**: Full test suite passes with >= 80% coverage; all linters and security scanners clean.

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

### Uncertainties & Resolutions
- **PayPal Authorization Expiry Fields**: PayPal Orders v2 returns `expiration_time` inside the authorization object (ISO 8601). We will parse and store this as `authorization_expires_at`.
- **PayPal Inbound Webhooks**: Event types to handle include `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.CAPTURE.REVERSED`. These serve strictly as corroborative evidence.
- **Gemini Structured Output**: The Gemini arbiter will use the official Google GenAI API endpoint with JSON response schema enforcement and temperature 0.0.
