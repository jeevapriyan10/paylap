from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from app.config import settings

# Engine for standard application runtime operations (paylap_app role, NOBYPASSRLS)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

# Engine strictly for migrations and schema administrative tasks (paylap_owner role)
engine_migrate = create_engine(
    settings.DATABASE_URL_MIGRATE,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

SessionMigrate = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine_migrate,
    future=True,
)

Base = declarative_base()


def set_tenant_org(db: Session, org_id: str) -> None:
    """Sets PostgreSQL session variable app.current_org for RLS enforcement."""
    db.execute(
        text("SELECT set_config('app.current_org', :org_id, false)"),
        {"org_id": org_id},
    )


@contextmanager
def org_session(org_id: str) -> Generator[Session, None, None]:
    """
    Open an org-scoped database session inside a transaction.
    Sets PostgreSQL session setting `app.current_org` locally (is_local=true).
    Guarantees that Row-Level Security filters all queries to this org_id.
    """
    session = SessionLocal()
    try:
        session.execute(
            text("SELECT set_config('app.current_org', :org_id, true)"),
            {"org_id": org_id},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Standard DB dependency generator for routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
