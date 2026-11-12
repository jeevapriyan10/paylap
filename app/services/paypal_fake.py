import time
import uuid
from typing import Any, Dict, Optional
from app.services.paypal_base import PayPalBase


class FakePayPal(PayPalBase):
    """
    In-memory simulated PayPal provider for demo mode.
    Every ID generated begins with 'DEMO-' and every response carries simulated=True.
    """

    def __init__(self, delay_seconds: float = 0.01):
        self.delay_seconds = delay_seconds
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.authorizations: Dict[str, Dict[str, Any]] = {}
        self.captures: Dict[str, Dict[str, Any]] = {}
        self.payouts: Dict[str, Dict[str, Any]] = {}

    def _sleep(self):
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

    def create_escrow_order(
        self,
        contract_id: str,
        amount_cents: int,
        return_url: str,
        cancel_url: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        self._sleep()
        order_id = f"DEMO-ORD-{uuid.uuid4().hex[:8].upper()}"
        data = {
            "order_id": order_id,
            "status": "APPROVED",
            "approve_url": None,  # Demo mode auto-funds without user approval
            "amount_cents": amount_cents,
            "contract_id": contract_id,
            "simulated": True,
        }
        self.orders[order_id] = data
        return data

    def authorize_order(
        self,
        order_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        self._sleep()
        auth_id = f"DEMO-AUTH-{uuid.uuid4().hex[:8].upper()}"
        data = {
            "authorization_id": auth_id,
            "status": "CREATED",
            "order_id": order_id,
            "simulated": True,
        }
        self.authorizations[auth_id] = data
        return data

    def capture(
        self,
        authorization_id: str,
        amount_cents: int,
        final_capture: bool,
        request_id: str
    ) -> Dict[str, Any]:
        self._sleep()
        cap_id = f"DEMO-CAP-{uuid.uuid4().hex[:8].upper()}"
        data = {
            "capture_id": cap_id,
            "authorization_id": authorization_id,
            "amount_cents": amount_cents,
            "final_capture": final_capture,
            "status": "COMPLETED",
            "simulated": True,
        }
        self.captures[cap_id] = data
        return data

    def void_authorization(
        self,
        authorization_id: str,
        request_id: str
    ) -> Dict[str, Any]:
        self._sleep()
        data = {
            "authorization_id": authorization_id,
            "status": "VOIDED",
            "simulated": True,
        }
        if authorization_id in self.authorizations:
            self.authorizations[authorization_id]["status"] = "VOIDED"
        return data

    def send_payout(
        self,
        recipient_email: str,
        amount_cents: int,
        request_id: str,
        note: str = "Milestone payout"
    ) -> Dict[str, Any]:
        self._sleep()
        batch_id = f"DEMO-BATCH-{uuid.uuid4().hex[:8].upper()}"
        data = {
            "payout_batch_id": batch_id,
            "status": "SUCCESS",
            "recipient_email": recipient_email,
            "amount_cents": amount_cents,
            "note": note,
            "simulated": True,
        }
        self.payouts[batch_id] = data
        return data

    def get_payout_status(
        self,
        payout_batch_id: str
    ) -> Dict[str, Any]:
        self._sleep()
        payout = self.payouts.get(payout_batch_id, {})
        status = payout.get("status", "SUCCESS")
        return {
            "payout_batch_id": payout_batch_id,
            "status": status,
            "simulated": True,
        }
