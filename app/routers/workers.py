from typing import Any, Dict, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.services.reputation import compute_worker_reputation, list_worker_reputations

router = APIRouter(prefix="/api/workers", tags=["Workers"])


@router.get("", response_model=List[Dict[str, Any]])
def get_workers(db: Session = Depends(get_db)):
    """List reputation scores and statistics for all workers."""
    return list_worker_reputations(db)


@router.get("/{worker_id}", response_model=Dict[str, Any])
def get_worker(worker_id: str, db: Session = Depends(get_db)):
    """Get reputation details and security penalty breakdown for a specific worker."""
    return compute_worker_reputation(db, worker_id)
