# Threat Model & Security Invariants

PayLap was designed from ground-zero under an adversarial threat model where workers, customers, LLMs, and network transport may be hostile or compromised.

## Non-Negotiable Defensive Invariants

1. **No Custody of Funds**: PayLap never handles customer fiat balances or intermediate settlement accounts. All holds exist on the customer's own PayPal merchant account (`AUTHORIZE`).
2. **Deterministic Precedence**: AI/LLM models **can never grant money**. An LLM may only issue a veto. Deterministic test suites and AST analyzers are the sole authority for passing code.
3. **Fail-Closed Arbiter**: If the LLM Arbiter fails (rate limit, downtime, network timeout, invalid schema), the evaluation fails closed without burning the worker's attempt quota.
4. **Tenant Isolation via PostgreSQL RLS**: Tenant boundaries are enforced inside the database engine (`ENABLE ROW LEVEL SECURITY; FORCE ROW LEVEL SECURITY`). Even with arbitrary SQL injection in application logic, cross-tenant reads or writes are impossible.
5. **Zero Secret Leaks**: Hidden tests, salt commitments, and master key material never appear in any API response, webhook payload, or public receipt.
6. **Worker Privacy**: Worker email addresses are masked on receipts (`a***e@example.com`) and public shares.

## Red Team Arena

PayLap includes a self-testing adversarial arena (`/v1/arena/run`) simulating six real attack vectors:
1. **Prompt Injection**: Injected adversarial instructions attempting to hijack the LLM Arbiter.
2. **AST Breakout**: Code attempting to bypass sandbox isolation using forbidden OS syscalls and reflection.
3. **Infinite Loops & Resource Exhaustion**: DoS attempts terminated strictly by process timeouts.
4. **Time Travel / Expiry Manipulation**: Spoofed client deadlines blocked by authoritative server timestamps.
5. **Hidden Test Oracle Probing**: Cheating attempts hardcoding answers for public tests intercepted by cryptographic commitments.
6. **Concurrent Race Double-Spend**: Parallel capture requests prevented by PostgreSQL row-level locks and advisory transaction locks.
