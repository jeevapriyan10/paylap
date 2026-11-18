from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Organization, Policy
from app.routers.auth import Principal, get_current_principal
from app.services.policy import get_or_create_policy

router = APIRouter(prefix="/v1/org/policy", tags=["Organization Spend Policy"])


class UpdatePolicyRequest(BaseModel):
    max_task_cents: int = Field(..., gt=0, le=1000000)
    daily_cap_cents: int = Field(..., gt=0, le=10000000)
    max_milestones: int = Field(..., ge=1, le=5)
    worker_allowlist: Optional[List[str]] = None
    require_hidden_tests: bool = True
    max_contract_days: int = Field(..., ge=1, le=29)


@router.get("/{environment}")
def get_policy(
    environment: str,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if environment not in ("simulated", "sandbox", "live"):
        raise HTTPException(status_code=422, detail="Invalid environment")

    policy = get_or_create_policy(db, principal.org_id, environment)
    return {
        "org_id": policy.org_id,
        "environment": policy.environment,
        "max_task_cents": policy.max_task_cents,
        "daily_cap_cents": policy.daily_cap_cents,
        "max_milestones": policy.max_milestones,
        "worker_allowlist": policy.worker_allowlist,
        "require_hidden_tests": policy.require_hidden_tests,
        "max_contract_days": policy.max_contract_days,
        "updated_at": policy.updated_at,
    }


@router.put("/{environment}")
def update_policy(
    environment: str,
    payload: UpdatePolicyRequest,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    if environment not in ("simulated", "sandbox", "live"):
        raise HTTPException(status_code=422, detail="Invalid environment")

    # Only admin or owner can modify policies
    if not principal.is_api_key and principal.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Only admin or owner can modify spend policies")

    policy = get_or_create_policy(db, principal.org_id, environment)
    policy.max_task_cents = payload.max_task_cents
    policy.daily_cap_cents = payload.daily_cap_cents
    policy.max_milestones = payload.max_milestones
    policy.worker_allowlist = payload.worker_allowlist
    policy.require_hidden_tests = payload.require_hidden_tests
    policy.max_contract_days = payload.max_contract_days
    policy.updated_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "status": "updated",
        "policy": {
            "environment": policy.environment,
            "max_task_cents": policy.max_task_cents,
            "daily_cap_cents": policy.daily_cap_cents,
            "max_milestones": policy.max_milestones,
            "worker_allowlist": policy.worker_allowlist,
            "require_hidden_tests": policy.require_hidden_tests,
            "max_contract_days": policy.max_contract_days,
            "updated_at": policy.updated_at,
        }
    }
