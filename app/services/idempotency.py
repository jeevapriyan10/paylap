import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import generate_id
from app.models import IdempotencyKey


def compute_request_hash(method: str, path: str, body: Any) -> str:
    """Compute deterministic SHA-256 hash of (method, path, body)."""
    if isinstance(body, dict):
        canonical_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
    elif isinstance(body, (bytes, bytearray)):
        canonical_body = body.decode("utf-8", errors="replace")
    elif body is None:
        canonical_body = ""
    else:
        canonical_body = str(body)

    content = f"{method.upper()}|{path.rstrip('/')}|{canonical_body}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def check_idempotency_key(
    db: Session,
    org_id: str,
    idempotency_key: Optional[str],
    method: str,
    path: str,
    body: Any,
) -> Optional[Tuple[int, Dict[str, Any], Dict[str, str]]]:
    """
    Checks if an idempotency key exists:
    - If key does not exist: returns None.
    - If key exists with matching hash: returns stored (status_code, json_body, headers).
    - If key exists with different hash: raises HTTP 422 Unprocessable Entity.
    - If key is currently being processed (in-flight): raises HTTP 409 Conflict.
    """
    if not idempotency_key or not idempotency_key.strip():
        return None

    key_str = idempotency_key.strip()
    req_hash = compute_request_hash(method, path, body)

    existing = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.org_id == org_id,
            IdempotencyKey.key == key_str,
        )
    )

    if not existing:
        return None

    # Verify request hash
    if existing.request_hash != req_hash:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency key reused with different request payload",
        )

    # In-flight check
    if existing.response_code == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A request with this Idempotency-Key is currently in-flight",
        )

    # Parse stored body
    try:
        parsed_body = json.loads(existing.response_body) if existing.response_body else {}
    except Exception:
        parsed_body = {"raw": existing.response_body}

    headers = dict(existing.response_headers or {})
    headers["Idempotent-Replayed"] = "true"

    return existing.response_code, parsed_body, headers


def store_idempotency_key(
    db: Session,
    org_id: str,
    idempotency_key: Optional[str],
    method: str,
    path: str,
    body: Any,
    response_code: int,
    response_body: Any,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """Store idempotency record in DB for replay protection."""
    if not idempotency_key or not idempotency_key.strip():
        return

    key_str = idempotency_key.strip()
    req_hash = compute_request_hash(method, path, body)

    if isinstance(response_body, (dict, list)):
        serialized_body = json.dumps(response_body)
    else:
        serialized_body = str(response_body)

    now = datetime.now(timezone.utc)
    record = IdempotencyKey(
        id=generate_id("idem"),
        org_id=org_id,
        key=key_str,
        method=method.upper(),
        path=path.rstrip("/"),
        request_hash=req_hash,
        response_code=response_code,
        response_headers=headers or {},
        response_body=serialized_body,
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.add(record)
    db.commit()
