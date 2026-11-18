import base64
from datetime import datetime, timezone
from typing import Optional, Tuple


def encode_cursor(created_at: datetime, item_id: str) -> str:
    """Encodes created_at and item_id into an opaque URL-safe base64 cursor."""
    raw = f"{created_at.isoformat()}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: Optional[str]) -> Tuple[Optional[datetime], Optional[str]]:
    """Decodes an opaque cursor into (created_at, item_id). Returns (None, None) if invalid."""
    if not cursor or not cursor.strip():
        return None, None

    try:
        raw = base64.urlsafe_b64decode(cursor.strip().encode("utf-8")).decode("utf-8")
        parts = raw.split("|", 1)
        if len(parts) != 2:
            return None, None
        dt_str, item_id = parts
        dt = datetime.fromisoformat(dt_str)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, item_id
    except Exception:
        return None, None
