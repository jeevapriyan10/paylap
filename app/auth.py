"""
PayLap Unified Authentication & Authorization Module.
Provides Principal models, FastAPI auth dependencies, and password security utilities.
"""

from app.routers.auth import Principal, get_current_principal, require_principal
from app.services.auth import (
    generate_api_key,
    generate_csrf_token,
    generate_session_token,
    has_permission,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_api_key_secret,
    verify_password,
)

# Canonical alias
get_password_hash = hash_password

__all__ = [
    "Principal",
    "get_current_principal",
    "require_principal",
    "hash_password",
    "get_password_hash",
    "verify_password",
    "validate_password_strength",
    "generate_session_token",
    "hash_token",
    "generate_csrf_token",
    "generate_api_key",
    "verify_api_key_secret",
    "has_permission",
]
