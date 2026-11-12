import asyncio
import json
import time
from typing import AsyncGenerator, Optional
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Event

router = APIRouter(prefix="/api/stream", tags=["Streaming"])


async def event_stream_generator(
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
    Outputs events with `id: <seq>`, `event: <type>`, and `data: <json>`.
    Sends `: heartbeat\n\n` periodically when idle.
    """
    cursor = after_seq
    delivered = 0
    last_heartbeat = time.time()

    while True:
        try:
            db.expire_all()
            query = db.query(Event).filter(Event.seq > cursor)
            if contract_id:
                query = query.filter(Event.contract_id == contract_id)

            events = query.order_by(Event.seq.asc()).limit(50).all()

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
                    "type": event.type,
                    "payload": event.payload,
                    "simulated": event.simulated,
                    "prev_hash": event.prev_hash,
                    "hash": event.hash,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }

                sse_chunk = (
                    f"id: {event.seq}\n"
                    f"event: {event.type}\n"
                    f"data: {json.dumps(event_dict)}\n\n"
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
            yield ": heartbeat\n\n"
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
