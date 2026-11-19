# Core Concepts

## 1. Contracts & Milestones

A **Contract** defines an agreement between a customer organization and a worker to deliver verified software or services.
- Each contract is divided into sequential or independent **Milestones**.
- Milestones specify a delivery specification, assertion tests (public and hidden), and a release budget (in integer USD minor units / cents).

## 2. Environments

PayLap supports three distinct execution environments:
- **`simulated`**: Full dry-run execution with zero external network calls. Simulated records carry `simulated: true` and are stamped on receipts.
- **`sandbox`**: Uses PayPal Developer Sandbox and real code runner sandbox. Fails if real credentials are missing or invalid.
- **`live`**: Production settlement with real money movement. Requires:
  1. `PAYLAP_ALLOW_LIVE=true`
  2. Organization `live_enabled=true`
  3. Remote secure execution runner

## 3. Two-Stage Settlement Pipeline

1. **Deterministic Verification (AST & Sandbox)**:
   - Worker submission code is statically analyzed for forbidden AST patterns (e.g. `import os`, `subprocess`, file access).
   - Code runs against public assertions in an isolated process with scrubbed environment and strict timeout.
   - If public assertions pass, code is evaluated against **hidden test assertions**.
2. **Fail-Closed LLM Arbiter**:
   - The LLM reviewer (Gemini) evaluates the submission for prompt injection, policy bypass, or deceptive malicious behavior.
   - Invariant: The LLM can **only VETO**. It can never force a milestone to pass. If the LLM is unreachable or errors, it fails closed without penalizing worker attempts.

## 4. Spend Policy

Every organization configures spend policies:
- Single contract limit (e.g., \$500.00)
- Daily organization cap
- Worker daily cap
Transactions that breach spend limits fail immediately with HTTP 422 before any hold or execution occurs.
