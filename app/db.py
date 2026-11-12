from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

connect_args = {}
if "sqlite" in settings.PAYLAP_DB_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.PAYLAP_DB_URL,
    connect_args=connect_args,
    future=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Safe SQLite schema upgrade for Stage 2 columns
    if "sqlite" in settings.PAYLAP_DB_URL:
        with engine.connect() as conn:
            try:
                # Check milestones columns
                res = conn.exec_driver_sql("PRAGMA table_info(milestones)").fetchall()
                existing_cols = {row[1] for row in res}
                if existing_cols:
                    if "verifier_type" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE milestones ADD COLUMN verifier_type VARCHAR(32) DEFAULT 'python_code'")
                    if "verifier_config" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE milestones ADD COLUMN verifier_config JSON")
                    if "hidden_commitment" not in existing_cols:
                        conn.exec_driver_sql("ALTER TABLE milestones ADD COLUMN hidden_commitment VARCHAR(64)")

                # Check contracts columns
                res_c = conn.exec_driver_sql("PRAGMA table_info(contracts)").fetchall()
                existing_c_cols = {row[1] for row in res_c}
                if existing_c_cols:
                    if "hidden_commitment" not in existing_c_cols:
                        conn.exec_driver_sql("ALTER TABLE contracts ADD COLUMN hidden_commitment VARCHAR(64)")
                conn.commit()
            except Exception:
                pass
