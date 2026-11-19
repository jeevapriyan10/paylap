# ADR 0001: PostgreSQL Row-Level Security for Multi-Tenancy

## Status
Accepted

## Context
PayLap handles financial authorizations and milestone settlement across distinct organizations. Leaking contracts, worker identities, or verification test suites across tenants is unacceptable. Relying on application-level `WHERE org_id = ...` clauses is prone to human error and developer omission.

## Decision
Enforce tenant isolation strictly at the PostgreSQL database level using Row-Level Security (RLS):
1. All tenant tables have `org_id VARCHAR NOT NULL`.
2. Tables are configured with:
   ```sql
   ALTER TABLE contracts ENABLE ROW LEVEL SECURITY;
   ALTER TABLE contracts FORCE ROW LEVEL SECURITY;
   CREATE POLICY contracts_org_isolation ON contracts
     FOR ALL
     USING (org_id = current_setting('app.current_org', true))
     WITH CHECK (org_id = current_setting('app.current_org', true));
   ```
3. The runtime role `paylap_app` is explicitly created with `NOBYPASSRLS` and `NOSUPERUSER`.
4. Schema migrations are performed exclusively by the `paylap_owner` role.

## Consequences
- Impossible for cross-tenant data leaks to occur, even if application code contains missing WHERE clauses.
- Queries without an active `app.current_org` session return zero rows.
