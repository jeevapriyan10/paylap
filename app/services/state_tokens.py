import hashlib
import hmac
import time
from typing import Optional, Tuple

from app.config import settings


def create_signed_funding_state(contract_id: str, org_id: str, ttl_seconds: int = 3600) -> str:
    """
    Creates an HMAC-SHA256 signed state token covering contract_id, org_id, and expiry.
    Format: contract_id.org_id.expiry_unix.hmac_signature
    """
    expiry_unix = int(time.time()) + ttl_seconds
    message = f"{contract_id}:{org_id}:{expiry_unix}".encode("utf-8")
    secret = settings.PAYLAP_SECRET_KEY.encode("utf-8")
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    return f"{contract_id}.{org_id}.{expiry_unix}.{signature}"


def verify_signed_funding_state(token: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Verifies a signed funding state token.
    Returns (is_valid, contract_id, org_id).
    """
    if not token or not token.strip():
        return False, None, None

    parts = token.strip().split(".")
    if len(parts) != 4:
        return False, None, None

    contract_id, org_id, expiry_unix_str, signature = parts
    try:
        expiry_unix = int(expiry_unix_str)
    except ValueError:
        return False, None, None

    # Expiration check
    if time.time() > expiry_unix:
        return False, None, None

    message = f"{contract_id}:{org_id}:{expiry_unix}".encode("utf-8")
    secret = settings.PAYLAP_SECRET_KEY.encode("utf-8")
    expected_sig = hmac.new(secret, message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False, None, None

    return True, contract_id, org_id
