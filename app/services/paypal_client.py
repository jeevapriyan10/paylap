import threading
import time
from typing import Any, Dict, Optional
import httpx
from app.config import settings
from app.schemas import cents_to_usd_str
from app.services.paypal_base import PayPalBase, PayPalError


class PayPalClient(PayPalBase):
    """
    Live PayPal API client using httpx (sync) with token caching, deterministic
    idempotency headers, and structured error reporting.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 15.0
    ):
        self.client_id = client_id or settings.PAYPAL_CLIENT_ID
        self.client_secret = client_secret or settings.PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(transport=transport, timeout=self.timeout)

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()

    def _get_access_token(self) -> str:
        """Fetch or return cached OAuth2 access token."""
        now = time.time()
        with self._lock:
            if self._token and now < (self._token_expires_at - 60):
                return self._token

            token_url = f"{self.base_url}/v1/oauth2/token"
            try:
                response = self.client.post(
                    token_url,
                    auth=(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials"},
                    headers={
                        "Accept": "application/json",
                        "Accept-Language": "en_US"
                    }
                )
            except httpx.RequestError as exc:
                raise PayPalError(f"Network error during PayPal OAuth token fetch: {exc}") from exc

            if response.status_code != 200:
                self._handle_error_response(response, "PayPal authentication failed")

            data = response.json()
            self._token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = now + float(expires_in)
            return self._token

    def _auth_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        return headers

    def _handle_error_response(self, response: httpx.Response, context_msg: str):
        debug_id = response.headers.get("paypal-debug-id")
        try:
            error_data = response.json()
        except Exception:
            error_data = response.text

        msg = f"{context_msg} (status: {response.status_code})"
        if isinstance(error_data, dict):
            detail_msg = error_data.get("message") or error_data.get("error_description") or error_data.get("name")
            if detail_msg:
                msg = f"{context_msg}: {detail_msg}"
            if "debug_id" in error_data and not debug_id:
                debug_id = error_data["debug_id"]

        raise PayPalError(
            message=msg,
            status_code=response.status_code,
            debug_id=debug_id,
            details=error_data
        )

    def create_escrow_order(
        self,
        contract_id: str,
        amount_cents: int,
        return_url: str,
        cancel_url: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a PayPal order with intent=AUTHORIZE and buyer-approval redirect URLs.
        """
        url = f"{self.base_url}/v2/checkout/orders"
        amount_val = cents_to_usd_str(amount_cents)

        payload = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": contract_id,
                    "description": f"PayLap Escrow Hold for Contract {contract_id}",
                    "amount": {
                        "currency_code": "USD",
                        "value": amount_val
                    }
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "brand_name": "PayLap",
                        "locale": "en-US",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url
                    }
                }
            }
        }

        headers = self._auth_headers(request_id)
        try:
            response = self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error creating escrow order: {exc}") from exc

        if response.status_code not in (200, 201):
            self._handle_error_response(response, "Failed to create escrow order")

        data = response.json()
        order_id = data.get("id")

        # Extract approval link handling both 'approve' and 'payer-action'
        approve_url = None
        for link in data.get("links", []):
            rel = link.get("rel")
            if rel in ("approve", "payer-action"):
                approve_url = link.get("href")
                break

        return {
            "order_id": order_id,
            "status": data.get("status"),
            "approve_url": approve_url,
            "raw": data,
            "simulated": False
        }

    def authorize_order(
        self,
        order_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Authorize the payment for an approved order.
        Extracts authorization id from purchase_units[0].payments.authorizations[0].id.
        """
        url = f"{self.base_url}/v2/checkout/orders/{order_id}/authorize"
        headers = self._auth_headers(request_id)
        try:
            response = self.client.post(url, json={}, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error authorizing order: {exc}") from exc

        if response.status_code not in (200, 201):
            self._handle_error_response(response, "Failed to authorize order")

        data = response.json()
        try:
            auth_obj = data["purchase_units"][0]["payments"]["authorizations"][0]
            auth_id = auth_obj["id"]
            auth_status = auth_obj.get("status", "CREATED")
        except (KeyError, IndexError) as exc:
            raise PayPalError(
                f"Unexpected authorization response structure: {data}",
                details=data
            ) from exc

        return {
            "authorization_id": auth_id,
            "status": auth_status,
            "raw": data,
            "simulated": False
        }

    def capture(
        self,
        authorization_id: str,
        amount_cents: int,
        final_capture: bool,
        request_id: str
    ) -> Dict[str, Any]:
        """
        Capture a specific amount from an authorization hold.
        """
        url = f"{self.base_url}/v2/payments/authorizations/{authorization_id}/capture"
        payload = {
            "amount": {
                "currency_code": "USD",
                "value": cents_to_usd_str(amount_cents)
            },
            "final_capture": final_capture
        }
        headers = self._auth_headers(request_id)
        try:
            response = self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error capturing funds: {exc}") from exc

        if response.status_code not in (200, 201):
            self._handle_error_response(response, "Failed to capture funds from authorization")

        data = response.json()
        return {
            "capture_id": data.get("id"),
            "status": data.get("status"),
            "amount_cents": amount_cents,
            "raw": data,
            "simulated": False
        }

    def void_authorization(
        self,
        authorization_id: str,
        request_id: str
    ) -> Dict[str, Any]:
        """
        Void the authorization hold.
        """
        url = f"{self.base_url}/v2/payments/authorizations/{authorization_id}/void"
        headers = self._auth_headers(request_id)
        try:
            response = self.client.post(url, json={}, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error voiding authorization: {exc}") from exc

        if response.status_code not in (200, 204):
            self._handle_error_response(response, "Failed to void authorization")

        data = response.json() if response.content else {}
        return {
            "authorization_id": authorization_id,
            "status": data.get("status", "VOIDED"),
            "raw": data,
            "simulated": False
        }

    def send_payout(
        self,
        recipient_email: str,
        amount_cents: int,
        request_id: str,
        note: str = "Milestone payout"
    ) -> Dict[str, Any]:
        """
        Send single payout via PayPal Payouts batch API.
        """
        url = f"{self.base_url}/v1/payments/payouts"
        amount_val = cents_to_usd_str(amount_cents)

        payload = {
            "sender_batch_header": {
                "sender_batch_id": request_id,
                "email_subject": "PayLap Milestone Payment",
                "email_message": "Payment for verified milestone completion on PayLap."
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": amount_val,
                        "currency": "USD"
                    },
                    "receiver": recipient_email,
                    "note": note,
                    "sender_item_id": f"item-{request_id}"
                }
            ]
        }

        headers = self._auth_headers(request_id)
        try:
            response = self.client.post(url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error sending payout: {exc}") from exc

        if response.status_code not in (200, 201):
            self._handle_error_response(response, "Failed to send payout")

        data = response.json()
        batch_header = data.get("batch_header", {})
        return {
            "payout_batch_id": batch_header.get("payout_batch_id"),
            "status": batch_header.get("batch_status", "PENDING"),
            "raw": data,
            "simulated": False
        }

    def get_payout_status(
        self,
        payout_batch_id: str
    ) -> Dict[str, Any]:
        """
        Query status of a payout batch.
        """
        url = f"{self.base_url}/v1/payments/payouts/{payout_batch_id}"
        headers = self._auth_headers()
        try:
            response = self.client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise PayPalError(f"Network error getting payout status: {exc}") from exc

        if response.status_code != 200:
            self._handle_error_response(response, "Failed to get payout status")

        data = response.json()
        batch_header = data.get("batch_header", {})
        return {
            "payout_batch_id": payout_batch_id,
            "status": batch_header.get("batch_status", "UNKNOWN"),
            "raw": data,
            "simulated": False
        }
