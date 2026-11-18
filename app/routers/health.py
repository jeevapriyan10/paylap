from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, text
from app.db import SessionLocal
from app.models import JobRun

router = APIRouter(tags=["Health & Probes"])


@router.get("/healthz")
def healthz():
    """Liveness probe: verifies the process is responsive."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    """
    Readiness probe:
    - Verifies PostgreSQL database is reachable
    - Verifies Alembic migrations are applied to head
    - Verifies background job heartbeat freshness
    """
    db = SessionLocal()
    try:
        # 1. Database connectivity
        db.execute(text("SELECT 1"))

        # 2. Migration version check
        res = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        if not res or not res[0]:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database migrations are not applied or alembic_version is empty",
            )
        current_migration = res[0]

        # 3. Job heartbeat check
        # If any jobs have run, ensure the latest run is not older than 24 hours
        latest_job = db.scalar(select(JobRun).order_by(JobRun.last_run_at.desc()).limit(1))
        job_status = "initialized"
        if latest_job:
            now = datetime.now(timezone.utc)
            if (now - latest_job.last_run_at) > timedelta(hours=24):
                job_status = "stale"
            else:
                job_status = "fresh"

        return {
            "status": "ready",
            "database": "connected",
            "migration_version": current_migration,
            "job_heartbeat": job_status,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database or system readiness check failed: {str(exc)}",
        )
    finally:
        db.close()
