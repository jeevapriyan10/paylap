"""PayLap SDK Exceptions."""

from typing import Any, Optional


class PayLapError(Exception):
    """Base exception for all PayLap SDK errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message


class AuthenticationError(PayLapError):
    """Raised when API key or session is missing or invalid (HTTP 401)."""


class AuthorizationError(PayLapError):
    """Raised when access is forbidden or lacking required scope (HTTP 403)."""


class NotFoundError(PayLapError):
    """Raised when a resource does not exist or belongs to another tenant (HTTP 404)."""


class ValidationError(PayLapError):
    """Raised when input validation fails (HTTP 422)."""


class SpendPolicyError(PayLapError):
    """Raised when contract creation exceeds org spend policy limits (HTTP 422)."""


class ReceiptVerificationError(PayLapError):
    """Raised when digital receipt cryptographic verification fails."""
