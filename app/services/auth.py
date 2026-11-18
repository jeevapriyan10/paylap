import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from app.config import settings

# Argon2id password hasher instance
ph = PasswordHasher()

# Top common passwords to reject
COMMON_PASSWORDS: Set[str] = {
    "password1234", "123456789012", "qwertyuiop12", "administrator",
    "password12345", "welcome123456", "changeme1234", "letmein12345",
    "iloveyou1234", "admin1234567", "password2024", "password2025", "password2026",
}

# Dummy hash used to equalize response timing when email is not found
_DUMMY_PASSWORD_HASH = ph.hash("dummy_timing_equalization_password_12345")

# Permission Matrix by Role
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "viewer": {
        "contracts:read",
        "workers:read",
        "policy:read",
        "receipts:read",
        "stats:read",
        "audit:read",
    },
    "developer": {
        "contracts:read",
        "contracts:write",
        "workers:read",
        "policy:read",
        "receipts:read",
        "stats:read",
        "audit:read",
        "playground:run",
        "api_keys:own",
    },
    "admin": {
        "contracts:read",
        "contracts:write",
        "workers:read",
        "policy:read",
        "policy:write",
        "receipts:read",
        "stats:read",
        "audit:read",
        "playground:run",
        "api_keys:own",
        "api_keys:manage",
        "credentials:manage",
        "webhooks:manage",
        "reconcile:run",
    },
    "owner": {
        "contracts:read",
        "contracts:write",
        "workers:read",
        "policy:read",
        "policy:write",
        "receipts:read",
        "stats:read",
        "audit:read",
        "playground:run",
        "api_keys:own",
        "api_keys:manage",
        "credentials:manage",
        "webhooks:manage",
        "reconcile:run",
        "org:manage",
        "members:manage",
        "live:enable",
    },
}

VALID_API_KEY_SCOPES = {
    "contracts:read",
    "contracts:write",
    "workers:read",
    "policy:read",
    "receipts:read",
    "webhooks:manage",
    "playground:run",
}


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return ph.hash(password)


def verify_password(password: str, hashed: str) -> Tuple[bool, bool]:
    """
    Verify password against Argon2id hash.
    Returns (is_valid, needs_rehash).
    """
    try:
        ph.verify(hashed, password)
        needs_rehash = ph.check_needs_rehash(hashed)
        return True, needs_rehash
    except VerifyMismatchError:
        return False, False
    except Exception:
        return False, False


def dummy_verify_password(password: str) -> None:
    """Run dummy verify to equalize response time for non-existent users."""
    try:
        ph.verify(_DUMMY_PASSWORD_HASH, password)
    except Exception:
        pass


def validate_password_strength(password: str) -> Optional[str]:
    """Validate password length and common passwords blacklist."""
    if len(password) < 12:
        return "Password must be at least 12 characters long"
    if password.lower() in COMMON_PASSWORDS:
        return "Password is too common; please choose a stronger password"
    return None


def generate_session_token() -> Tuple[str, str]:
    """
    Generates a 256-bit random session token.
    Returns (raw_token, sha256_hash).
    """
    raw_token = secrets.token_urlsafe(32)  # 256 bits of entropy
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_hex(32)


def generate_api_key(env_class: str = "test") -> Tuple[str, str, str, str, str]:
    """
    Generates a structured API key:
    Format: pl_<env_class>_<lookup_id>_<secret>
    Returns (full_key, lookup_id, secret_hash, prefix, last4).
    """
    prefix = f"pl_{env_class}"
    lookup_id = secrets.token_hex(8)  # 16 chars
    secret = secrets.token_hex(16)    # 32 chars
    full_key = f"{prefix}_{lookup_id}_{secret}"
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    last4 = secret[-4:]
    return full_key, lookup_id, secret_hash, prefix, last4


def verify_api_key_secret(provided_secret: str, stored_hash: str) -> bool:
    """Constant-time comparison of hashed API key secret."""
    computed_hash = hashlib.sha256(provided_secret.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed_hash, stored_hash)


def has_permission(role: str, permission: str) -> bool:
    """Check if an org role has a given permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms
