import pytest
from sqlalchemy import create_engine, text
from app.config import settings
from app.db import org_session
from app.ids import generate_id
from app.models import TENANT_TABLES, Contract, Organization


@pytest.fixture
def pg_app_engine():
    # Connect as runtime role paylap_app to paylap_test
    url = "postgresql+psycopg://paylap_app:paylap_app_pass@localhost:5432/paylap_test"
    return create_engine(url, pool_pre_ping=True)


@pytest.fixture
def pg_owner_engine():
    # Connect as owner role paylap_owner to paylap_test
    url = "postgresql+psycopg://paylap_owner:paylap_owner_pass@localhost:5432/paylap_test"
    return create_engine(url, pool_pre_ping=True)


def test_runtime_role_has_no_bypass_rls_and_is_not_owner(pg_app_engine):
    with pg_app_engine.connect() as conn:
        # 1. Assert runtime role has rolbypassrls=false and rolsuper=false
        res = conn.execute(
            text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'paylap_app'")
        ).fetchone()
        assert res is not None
        assert res[0] == "paylap_app"
        assert res[1] is False, "paylap_app must not be superuser"
        assert res[2] is False, "paylap_app must have rolbypassrls=false"

        # 2. Assert runtime role does NOT own any public tables
        tables = conn.execute(
            text("SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
        assert len(tables) > 0
        for tablename, tableowner in tables:
            assert tableowner != "paylap_app", f"Table {tablename} must not be owned by paylap_app"
            assert tableowner == "paylap_owner", f"Table {tablename} must be owned by paylap_owner"


def test_tenant_tables_have_rls_forced(pg_app_engine):
    with pg_app_engine.connect() as conn:
        res = conn.execute(
            text("""
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                WHERE pg_namespace.nspname = 'public' AND relkind = 'r'
            """)
        ).fetchall()

        rls_map = {row[0]: (row[1], row[2]) for row in res}
        for table in TENANT_TABLES:
            assert table in rls_map, f"Tenant table {table} not found in public schema"
            relrowsecurity, relforcerowsecurity = rls_map[table]
            assert relrowsecurity is True, f"Table {table} must have ENABLE ROW LEVEL SECURITY"
            assert relforcerowsecurity is True, f"Table {table} must have FORCE ROW LEVEL SECURITY"


def test_rls_isolation_and_zero_rows_without_org(pg_owner_engine, pg_app_engine):
    org_a_id = generate_id("org")
    org_b_id = generate_id("org")
    ctr_a_id = generate_id("ctr")
    ctr_b_id = generate_id("ctr")

    # 1. Seed two organizations and two contracts as owner
    with pg_owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO organizations (id, name, slug, live_enabled, arbiter_enabled, created_at, updated_at) VALUES (:id, :name, :slug, false, true, NOW(), NOW())"),
            [
                {"id": org_a_id, "name": "Org A", "slug": f"org-a-{org_a_id}"},
                {"id": org_b_id, "name": "Org B", "slug": f"org-b-{org_b_id}"},
            ]
        )
        conn.execute(
            text("""
                INSERT INTO contracts (
                    id, org_id, title, worker_id, worker_email, environment,
                    is_playground, needs_attention, total_cents, currency, status, capture_strategy,
                    created_at, updated_at
                ) VALUES (
                    :id, :org_id, :title, 'worker-1', 'worker@test.com', 'simulated',
                    false, false, 1000, 'USD', 'CREATED', 'partial', NOW(), NOW()
                )
            """),
            [
                {"id": ctr_a_id, "org_id": org_a_id, "title": "Contract A"},
                {"id": ctr_b_id, "org_id": org_b_id, "title": "Contract B"},
            ]
        )

    # 2. Runtime role query WITHOUT setting app.current_org -> MUST RETURN ZERO ROWS
    with pg_app_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, title FROM contracts")).fetchall()
        assert len(rows) == 0, f"Expected 0 rows without app.current_org set, got {len(rows)}"

    # 3. Runtime role query WITH app.current_org = org_a_id -> Sees ONLY Org A rows
    with pg_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": org_a_id})
            rows_a = conn.execute(text("SELECT id, title FROM contracts")).fetchall()
            assert len(rows_a) == 1
            assert rows_a[0][0] == ctr_a_id

    # 4. Runtime role query WITH app.current_org = org_b_id -> Sees ONLY Org B rows
    with pg_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": org_b_id})
            rows_b = conn.execute(text("SELECT id, title FROM contracts")).fetchall()
            assert len(rows_b) == 1
            assert rows_b[0][0] == ctr_b_id

    # 5. Runtime role attempting to insert a contract for org_b while scoped to org_a -> WITH CHECK fails
    with pg_app_engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SELECT set_config('app.current_org', :org_id, true)"), {"org_id": org_a_id})
            with pytest.raises(Exception) as exc_info:
                conn.execute(
                    text("""
                        INSERT INTO contracts (
                            id, org_id, title, worker_id, worker_email, environment,
                            is_playground, needs_attention, total_cents, currency, status, capture_strategy,
                            created_at, updated_at
                        ) VALUES (
                            :id, :org_id, 'Illegal Cross-Tenant', 'worker-1', 'worker@test.com',
                            'simulated', false, false, 1000, 'USD', 'CREATED', 'partial', NOW(), NOW()
                        )
                    """),
                    {"id": generate_id("ctr"), "org_id": org_b_id}
                )
            assert "violates row-level security policy" in str(exc_info.value).lower()
