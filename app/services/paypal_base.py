from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class PayPalError(Exception):
    """Custom exception for PayPal API errors without exposing credentials."""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        debug_id: Optional[str] = None,
        details: Optional[Any] = None
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.debug_id = debug_id
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"HTTP Status: {self.status_code}")
        if self.debug_id:
            parts.append(f"PayPal Debug-ID: {self.debug_id}")
        return " | ".join(parts)


class PayPalBase(ABC):
    """Abstract interface for PayPal money operations."""

    @abstractmethod
    def create_escrow_order(
        self,
        contract_id: str,
        amount_cents: int,
        return_url: str,
        cancel_url: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create an order with intent=AUTHORIZE and return order details with approval URL."""
        pass

    @abstractmethod
    def authorize_order(
        self,
        order_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Authorize the approved order and return authorization details."""
        pass

    @abstractmethod
    def capture(
        self,
        authorization_id: str,
        amount_cents: int,
        final_capture: bool,
        request_id: str
    ) -> Dict[str, Any]:
        """Capture a specific amount from the authorization."""
        pass

    @abstractmethod
    def void_authorization(
        self,
        authorization_id: str,
        request_id: str
    ) -> Dict[str, Any]:
        """Void an authorization, releasing any remaining hold."""
        pass

    @abstractmethod
    def send_payout(
        self,
        recipient_email: str,
        amount_cents: int,
        request_id: str,
        note: str = "Milestone payout"
    ) -> Dict[str, Any]:
        """Send a payout to the worker via PayPal Payouts."""
        pass

    @abstractmethod
    def get_payout_status(
        self,
        payout_batch_id: str
    ) -> Dict[str, Any]:
        """Retrieve latest payout batch status."""
        pass
