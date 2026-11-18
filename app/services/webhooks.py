from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract, Event, Organization, WebhookDelivery, WebhookEndpoint

logger = logging.getLogger("paylap.webhooks")

# Retry backoffs in seconds: 1m, 5m, 30m, 2h, 5h
RETRY_BACKOFFS = [60, 300, 1800, 7200, 18000]


def is_safe_webhook_url(url: str, allow_test: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Strict SSRF validation: resolves hostname and ensures destination IP is not private,
    loopback, link-local, multicast, or reserved.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid URL scheme '{parsed.scheme}'; only http/https allowed"

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL"

    if (allow_test or settings.PAYLAP_ENV == "test") and hostname in ("testserver", "localhost", "127.0.0.1", "example.com"):
        return True, None

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return False, f"Could not resolve hostname '{hostname}': {exc}"

    for _, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False, f"Blocked private/reserved IP address: {ip_str}"
        except ValueError:
            return False, f"Invalid IP address returned: {ip_str}"

    return True, None


def compute_webhook_signature(secret: str, timestamp: int, payload_str: str) -> str:
    """Computes PayLap-Signature: t={timestamp},v1={hmac_sha256}."""
    content = f"{timestamp}.{payload_str}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), content, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def verify_webhook_signature(secret: str, signature_header: str, payload_str: str, tolerance_seconds: int = 300) -> bool:
    """Validates PayLap-Signature header and checks timestamp drift."""
    try:
        parts = dict(item.split("=", 1) for item in signature_header.split(","))
        timestamp = int(parts["t"])
        v1_sig = parts["v1"]
    except Exception:
        return False

    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - timestamp) > tolerance_seconds:
        return False

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload_str}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(v1_sig, expected_sig)


def enqueue_webhook_deliveries(db: Session, event: Event) -> List[WebhookDelivery]:
    """
    Finds all active webhook endpoints for the event's org and enqueues WebhookDelivery rows.
    """
    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.org_id == event.org_id,
            WebhookEndpoint.is_active.is_(True),
        )
    ).all()

    deliveries = []
    now = datetime.now(timezone.utc)
    for ep in endpoints:
        # Check event filter if specified
        if ep.events_filter and event.event_type not in ep.events_filter:
            continue

        deliv = WebhookDelivery(
            id=generate_id("del"),
            org_id=event.org_id,
            endpoint_id=ep.id,
            event_id=event.id,
            event_type=event.event_type,
            payload={
                "id": event.id,
                "contract_id": event.contract_id,
                "seq": event.seq,
                "type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat() if event.created_at else now.isoformat(),
            },
            status="PENDING",
            attempt_count=0,
            next_retry_at=now,
            created_at=now,
        )
        db.add(deliv)
        deliveries.append(deliv)

    if deliveries:
        db.commit()

    return deliveries


def deliver_webhook_sync(
    db: Session,
    delivery: WebhookDelivery,
    raw_secret: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> bool:
    """
    Attempts to dispatch a webhook delivery to its endpoint destination.
    Updates delivery record status, response status/body, and next retry time.
    """
    endpoint = db.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.endpoint_id))
    if not endpoint or not endpoint.is_active:
        delivery.status = "EXHAUSTED"
        delivery.response_body = "Endpoint deleted or inactive"
        db.commit()
        return False

    is_safe, err = is_safe_webhook_url(endpoint.url, allow_test=(settings.PAYLAP_ENV == "test"))
    if not is_safe:
        delivery.status = "FAILED"
        delivery.response_body = f"SSRF Block: {err}"
        db.commit()
        return False

    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload_str = json.dumps(delivery.payload, sort_keys=True)
    secret = raw_secret or endpoint.secret_hash
    signature = compute_webhook_signature(secret, now_ts, payload_str)

    headers = {
        "Content-Type": "application/json",
        "PayLap-Signature": signature,
        "PayLap-Event": delivery.event_type,
        "PayLap-Delivery-ID": delivery.id,
        "User-Agent": "PayLap-Webhook-Dispatcher/1.0",
    }

    delivery.attempt_count += 1
    http_client = client or httpx.Client(timeout=5.0)

    success = False
    try:
        resp = http_client.post(endpoint.url, content=payload_str.encode("utf-8"), headers=headers)
        delivery.response_status = resp.status_code
        delivery.response_body = resp.text[:1000]
        if 200 <= resp.status_code < 300:
            delivery.status = "SUCCESS"
            delivery.next_retry_at = None
            success = True
        else:
            delivery.status = "FAILED"
    except Exception as exc:
        delivery.status = "FAILED"
        delivery.response_body = f"Connection error: {str(exc)[:500]}"
    finally:
        if client is None:
            http_client.close()

    if not success:
        # Calculate backoff
        if delivery.attempt_count < len(RETRY_BACKOFFS):
            backoff_secs = RETRY_BACKOFFS[delivery.attempt_count - 1]
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_secs)
        else:
            delivery.status = "EXHAUSTED"
            delivery.next_retry_at = None

    db.commit()
    return success


def process_pending_webhooks(db: Session, max_batch: int = 50) -> int:
    """
    Picks up pending/failed webhook deliveries whose next_retry_at <= now() and delivers them.
    """
    now = datetime.now(timezone.utc)
    deliveries = db.scalars(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status.in_(["PENDING", "FAILED"]),
            WebhookDelivery.next_retry_at <= now,
        )
        .order_by(WebhookDelivery.created_at.asc())
        .limit(max_batch)
    ).all()

    delivered_count = 0
    for deliv in deliveries:
        if deliver_webhook_sync(db, deliv):
            delivered_count += 1

    return delivered_count
