# PayLap Non-Negotiable Engineering Rules

These rules govern all engineering, development, review, and deployment activities across the PayLap codebase.

1. **Secrets & Credentials Safety**
   - Never read, print, log, or commit secrets.
   - Never open, display, or echo `.env`.
   - Only `.env.example` holds documented placeholder values.
   - Credentials in memory or transit must be redacted in all logs, exceptions, and monitoring.

2. **Money Representation & Precision**
   - Money is strictly stored and handled internally as integer minor units (e.g., cents for USD) plus currency (`USD` only for now).
   - Decimal strings (e.g., `"10.00"`) exist only at the PayPal API boundary.
   - Floats are strictly prohibited for monetary calculations to prevent rounding inaccuracies.

3. **Environments & Separation**
   - Valid environments are strictly: `simulated`, `sandbox`, and `live`.
   - `simulated` is an explicit, labeled dry-run (`simulated=true` on every record and response, with a visible badge in the UI).
   - `sandbox` and `live` never fall back to fake behavior; failures must surface honestly as errors.
   - `live` operations strictly require `PAYLAP_ALLOW_LIVE=true` AND the organization's `live_enabled` flag AND the isolated remote runner.

4. **Zero Production Doubles & Test Isolation**
   - Test doubles (fake PayPal, fake clock, mock transports, mock LLM) exist ONLY under `tests/` and within the `simulated` environment provider.
   - The simulated provider is a real, documented product feature, not a mock of production.
   - Product code must contain zero mocks, stubs, hardcoded sample values, TODOs, "lorem ipsum", or demo-only branches.

5. **LLM Arbiter Governance (Fail-Closed, Veto-Only)**
   - The LLM arbiter can only VETO; it can never grant payment.
   - Deterministic gates (automated tests, syntax/AST rules, schema validators) make positive payment decisions.
   - If the arbiter is unavailable in `sandbox` or `live`, execution fails closed without consuming an attempt, leaving the milestone pending retry.

6. **Tenant Isolation & Row-Level Security (RLS)**
   - Every tenant table has `org_id NOT NULL`.
   - PostgreSQL Row-Level Security (RLS) is ENABLED and FORCED (`FORCE ROW LEVEL SECURITY`) with `USING` and `WITH CHECK (org_id = current_setting('app.current_org', true))`.
   - The application runtime role (`paylap_app`) is not the table owner and has `NOBYPASSRLS`.
   - Queries accessing foreign resources must return HTTP 404 (not 403) to prevent tenant resource enumeration.

7. **Zero Leakage of Hidden Tests**
   - Hidden test suites, assertions, fixtures, or specific error messages never appear in any API response, event, audit log, receipt, webhook payload, or user-facing error message.
   - Failures in hidden tests report strictly aggregated summaries (e.g., "N of M hidden checks failed").

8. **Append-Only Hash Chains & Idempotency**
   - Ledger event chains are append-only and cryptographically hash-chained (`sha256` sequence).
   - Every money-moving call is strictly idempotent, guarded by both deterministic PayPal `PayPal-Request-Id` headers and API `Idempotency-Key` tracking.

9. **Privacy & Identity Masking**
   - Worker emails and personally identifiable information (PII) are masked in all generated receipts, audit logs, and public/shared views.
