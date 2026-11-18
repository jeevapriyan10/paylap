import asyncio
import json
import time
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.auth import Principal, require_principal
from app.db import get_db
from app.models import Event

router = APIRouter(prefix="/v1/stream", tags=["Streaming"])


async def event_stream_generator(
    org_id: str,
    after_seq: int,
    db: Session,
    contract_id: Optional[str] = None,
    run_id: Optional[str] = None,
    heartbeat_interval: float = 15.0,
    poll_once: bool = False,
    max_events: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """
    Asynchronous event generator producing Server-Sent Events (SSE).
    Scoped strictly to org_id under PostgreSQL RLS.
    Outputs: `id: <seq>\nevent: <type>\ndata: <json>\n\n`
    Sends `: ping\n\n` periodically when idle.
    """
    cursor = after_seq
    delivered = 0
    last_heartbeat = time.time()

    # Ensure RLS org context is set for this session
    try:
        db.execute(
            text("SELECT set_config('app.current_org', :org_id, false)"),
            {"org_id": org_id},
        )
    except Exception:
        pass

    while True:
        try:
            db.expire_all()
            query = select(Event).where(
                Event.org_id == org_id,
                Event.seq > cursor,
            )
            if contract_id:
                query = query.where(Event.contract_id == contract_id)

            events = db.scalars(query.order_by(Event.seq.asc()).limit(50)).all()

            for event in events:
                if event.seq > cursor:
                    cursor = event.seq

                if run_id:
                    if not (isinstance(event.payload, dict) and event.payload.get("run_id") == run_id):
                        continue

                event_dict = {
                    "id": event.id,
                    "contract_id": event.contract_id,
                    "seq": event.seq,
                    "type": event.event_type,
                    "payload": event.payload,
                    "simulated": event.simulated,
                    "prev_hash": event.prev_hash,
                    "hash": event.event_hash,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }

                sse_chunk = (
                    f"id: {event.seq}\n"
                    f"event: {event.event_type}\n"
                    f"data: {json.dumps(event_dict, sort_keys=True)}\n\n"
                )
                yield sse_chunk
                delivered += 1
                last_heartbeat = time.time()

                if max_events is not None and delivered >= max_events:
                    return

        except Exception:
            pass

        if poll_once:
            return

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            yield ": ping\n\n"
            last_heartbeat = now

        await asyncio.sleep(0.3)


@router.get("")
async def sse_event_stream(
    after: Optional[int] = Query(None, description="Stream events strictly after this sequence number"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    contract_id: Optional[str] = Query(None, description="Filter events for specific contract"),
    run_id: Optional[str] = Query(None, description="Filter events for specific arena run"),
    poll_once: bool = Query(False, description="Internal test helper to close stream after one sweep"),
    max_events: Optional[int] = Query(None, description="Maximum events to yield before closing"),
    principal: Principal = Depends(require_principal("contracts:read")),
    db: Session = Depends(get_db),
):
    """
    Real-time Server-Sent Events (SSE) stream of PayLap ledger events.
    Supports reconnection via Last-Event-ID header or `?after=<seq>` query parameter.
    """
    cursor = 0
    if after is not None:
        cursor = after
    elif last_event_id and last_event_id.strip().isdigit():
        cursor = int(last_event_id.strip())

    return StreamingResponse(
        event_stream_generator(
            org_id=principal.org_id,
            after_seq=cursor,
            db=db,
            contract_id=contract_id,
            run_id=run_id,
            heartbeat_interval=15.0,
            poll_once=poll_once,
            max_events=max_events,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
