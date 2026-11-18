import base64
import os
import secrets
from typing import Optional

import typer
from sqlalchemy import create_engine, select

from app.auth import get_password_hash, validate_password_strength
from app.config import settings
from app.db import SessionLocal, SessionMigrate
from app.ids import generate_id
from app.models import ApiKey, Contract, Membership, Milestone, Organization, User
from app.services.crypto import rotate_all_credentials_master_key
from app.services.expiry import expire_due_contracts
from app.services.policy import get_or_create_policy
from app.services.reconciliation import run_reconciliation

cli_app = typer.Typer(name="paylap", help="PayLap Settlement Engine Administrative CLI")


@cli_app.command("gen-master-key")
def gen_master_key(
    key_id: Optional[str] = typer.Option(None, "--id", help="Optional key identifier (default: key_<hex>)"),
):
    """Generate a cryptographically secure 32-byte master key for AES-256-GCM encryption."""
    kid = key_id or f"key_{secrets.token_hex(4)}"
    key_bytes = os.urandom(32)
    b64_key = base64.b64encode(key_bytes).decode("utf-8")
    entry = f"{kid}:{b64_key}"
    typer.echo(entry)


@cli_app.command("create-user")
def create_user(
    email: str = typer.Option(..., "--email", "-e", help="User email address"),
    password: str = typer.Option(..., "--password", "-p", help="User password (min 12 chars)"),
    org_name: str = typer.Option(..., "--org-name", "-o", help="Organization display name"),
    role: str = typer.Option("owner", "--role", "-r", help="Role: owner | admin | developer | viewer"),
):
    """Create a new user, organization, and membership."""
    err = validate_password_strength(password)
    if err:
        typer.secho(f"Error: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    normalized_email = email.strip().lower()

    with SessionMigrate() as db:
        existing_user = db.scalar(select(User).where(User.email == normalized_email))
        if existing_user:
            typer.secho(f"Error: User with email '{normalized_email}' already exists.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        slug_base = "".join(c if c.isalnum() else "-" for c in org_name.lower()).strip("-")
        slug = f"{slug_base}-{secrets.token_hex(3)}"

        org_id = generate_id("org")
        org = Organization(
            id=org_id,
            name=org_name,
            slug=slug,
            live_enabled=False,
            arbiter_enabled=True,
        )
        db.add(org)
        db.flush()

        user_id = generate_id("usr")
        user = User(
            id=user_id,
            email=normalized_email,
            password_hash=get_password_hash(password),
        )
        db.add(user)
        db.flush()

        membership = Membership(
            id=generate_id("mem"),
            user_id=user_id,
            org_id=org_id,
            role=role,
        )
        db.add(membership)
        db.commit()

        typer.secho("✓ User and organization created successfully:", fg=typer.colors.GREEN)
        typer.echo(f"  User ID: {user.id}")
        typer.echo(f"  Email: {user.email}")
        typer.echo(f"  Organization ID: {org.id}")
        typer.echo(f"  Org Slug: {org.slug}")
        typer.echo(f"  Role: {membership.role}")


@cli_app.command("migrate-check")
def migrate_check():
    """Verify that the database schema is migrated to Alembic head."""
    try:
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory

        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        migrate_url = settings.DATABASE_URL_MIGRATE or settings.DATABASE_URL
        engine = create_engine(migrate_url)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

        if current_rev == head_rev:
            typer.secho(f"✓ Database is up to date at head revision: {current_rev}", fg=typer.colors.GREEN)
            return

        typer.secho(
            f"✗ Database migration pending! Current: {current_rev}, Head: {head_rev}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    except Exception as exc:
        typer.secho(f"Error checking migrations: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@cli_app.command("seed-dev")
def seed_dev():
    """Seed the database with development organization, user, API keys, and contracts."""
    with SessionMigrate() as db:
        # Check if already seeded
        existing_org = db.scalar(select(Organization).where(Organization.slug == "acme-dev"))
        if existing_org:
            typer.echo("Database already contains dev seed (acme-dev).")
            return

        org_id = generate_id("org")
        org = Organization(
            id=org_id,
            name="Acme Corporation (Dev)",
            slug="acme-dev",
            live_enabled=False,
            arbiter_enabled=True,
        )
        db.add(org)
        db.flush()

        user_id = generate_id("usr")
        user = User(
            id=user_id,
            email="dev@paylap.local",
            password_hash=get_password_hash("Development1234!"),
        )
        db.add(user)
        db.flush()

        membership = Membership(
            id=generate_id("mem"),
            user_id=user_id,
            org_id=org_id,
            role="owner",
        )
        db.add(membership)

        # Create development API key
        import hashlib

        raw_key = "pl_test_devkey00000000_1234567890abcdef1234567890abcdef"
        lookup_id = "devkey00000000"
        secret = "1234567890abcdef1234567890abcdef"
        api_key = ApiKey(
            id=generate_id("key"),
            org_id=org_id,
            created_by=user_id,
            lookup_id=lookup_id,
            secret_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            prefix="pl_test_",
            last4=secret[-4:],
            scopes=[
                "contracts:read",
                "contracts:write",
                "workers:read",
                "policy:read",
                "receipts:read",
                "webhooks:manage",
                "playground:run",
            ],
            environment_class="test",
        )
        db.add(api_key)

        # Create policies
        get_or_create_policy(db, org_id, "simulated")
        get_or_create_policy(db, org_id, "sandbox")

        # Create sample contract
        cid = generate_id("ctr")
        contract = Contract(
            id=cid,
            org_id=org_id,
            title="Sample Dev Contract",
            worker_id="dev-worker",
            worker_email="dev-worker@example.com",
            environment="simulated",
            total_cents=1000,
            currency="USD",
            status="AWAITING_FUNDING",
        )
        db.add(contract)

        mid = generate_id("mst")
        milestone = Milestone(
            id=mid,
            org_id=org_id,
            contract_id=cid,
            sequence=1,
            title="Milestone 1: Hello World",
            amount_cents=1000,
            spec="Implement return_hello() returning 'hello'",
            public_tests="from solution import return_hello\ndef test_hello(): assert return_hello() == 'hello'\n",
            hidden_tests="from solution import return_hello\ndef test_h(): assert isinstance(return_hello(), str)\n",
            hidden_commitment_hash="a" * 64,
            status="PENDING",
        )
        db.add(milestone)
        db.commit()

        typer.secho("✓ Successfully seeded development environment:", fg=typer.colors.GREEN)
        typer.echo(f"  Org ID: {org.id}")
        typer.echo("  User: dev@paylap.local / Development1234!")
        typer.echo(f"  API Key: {raw_key}")
        typer.echo(f"  Contract: {contract.id}")


@cli_app.command("rotate-master-key")
def rotate_master_key_cmd(
    new_key_id: str = typer.Option(..., "--new-key-id", "-k", help="The new target master key ID"),
):
    """Re-encrypt all stored PayPal client secrets under a newly added master key ID."""
    with SessionMigrate() as db:
        rotated = rotate_all_credentials_master_key(db, target_key_id=new_key_id)
        typer.secho(
            f"✓ Master key rotation complete. Rotated {rotated} credentials to '{new_key_id}'.", fg=typer.colors.GREEN
        )


@cli_app.command("reconcile")
def reconcile_cmd(
    org_id: str = typer.Option(..., "--org-id", "-o", help="Organization ID to reconcile"),
    environment: str = typer.Option("simulated", "--env", "-e", help="Environment: simulated | sandbox | live"),
):
    """Execute on-demand reconciliation of contract holds against PayPal provider."""
    from app.ledger import set_tenant_org

    with SessionLocal() as db:
        set_tenant_org(db, org_id)
        run_record = run_reconciliation(db, org_id=org_id, environment=environment)
        typer.secho(f"✓ Reconciliation run '{run_record.id}' finished:", fg=typer.colors.GREEN)
        typer.echo(f"  Contracts checked: {run_record.contracts_checked}")
        typer.echo(f"  Discrepancies found: {run_record.discrepancies_found}")


@cli_app.command("expire-now")
def expire_now():
    """Immediately scan and expire contracts past their deadline or auth safety margin."""
    with SessionMigrate() as db:
        expired_ids = expire_due_contracts(db)
        typer.secho(f"✓ Expiry check completed. Expired {len(expired_ids)} contracts.", fg=typer.colors.GREEN)
        for cid in expired_ids:
            typer.echo(f"  - {cid}")


if __name__ == "__main__":
    cli_app()
