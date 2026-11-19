"""PayLap Synchronous and Asynchronous HTTP Clients."""

import base64
import json
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paylap.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    PayLapError,
    ReceiptVerificationError,
    SpendPolicyError,
    ValidationError,
)


def canonicalize_json(data: Any) -> bytes:
    """RFC 8785 Canonical JSON bytes."""
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def verify_receipt_data(receipt: Dict[str, Any]) -> bool:
    """
    Offline cryptographic verification of a PayLap receipt (Receipt v2).
    Verifies that Ed25519 signature is valid against the signer public key
    over RFC 8785 canonical JSON bytes of the receipt payload.
    """
    try:
        signature_b64 = receipt.get("signature") or receipt.get("ed25519_signature")
        pubkey_b64 = receipt.get("signer_public_key") or receipt.get("public_key")

        if not signature_b64 or not pubkey_b64:
            raise ReceiptVerificationError("Receipt missing signature or signer_public_key")

        # Strip signature field before canonicalizing
        payload_to_verify = {k: v for k, v in receipt.items() if k not in ("signature", "ed25519_signature")}
        canonical_bytes = canonicalize_json(payload_to_verify)

        pub_bytes = base64.b64decode(pubkey_b64)
        sig_bytes = base64.b64decode(signature_b64)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(sig_bytes, canonical_bytes)
        return True
    except Exception as exc:
        if isinstance(exc, ReceiptVerificationError):
            raise
        raise ReceiptVerificationError(f"Verification failed: {exc}") from exc


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error status codes to PayLap exceptions."""
    if response.is_success:
        return

    status = response.status_code
    try:
        payload = response.json()
        error_info = payload.get("error", {})
        message = error_info.get("message") or response.text
        details = error_info.get("details")
    except Exception:
        message = response.text
        details = None

    if status == 401:
        raise AuthenticationError(message, status_code=status, details=details)
    elif status == 403:
        raise AuthorizationError(message, status_code=status, details=details)
    elif status == 404:
        raise NotFoundError(message, status_code=status, details=details)
    elif status == 422:
        if "spend policy" in message.lower() or "budget" in message.lower():
            raise SpendPolicyError(message, status_code=status, details=details)
        raise ValidationError(message, status_code=status, details=details)
    else:
        raise PayLapError(message, status_code=status, details=details)


class BaseClient:
    """Shared base client logic for PayLap."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "paylap-python-sdk/0.3.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if custom_headers:
            headers.update(custom_headers)
        return headers


class PayLap(BaseClient):
    """Synchronous PayLap client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
    ):
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=self.timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PayLap":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def create_contract(
        self,
        title: str,
        milestones: List[Dict[str, Any]],
        worker_email: Optional[str] = None,
        deadline_days: int = 14,
        max_attempts: int = 3,
        environment: str = "simulated",
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new settlement contract."""
        payload: Dict[str, Any] = {
            "title": title,
            "milestones": milestones,
            "worker_email": worker_email,
            "deadline_days": deadline_days,
            "max_attempts": max_attempts,
            "environment": environment,
            "metadata": metadata or {},
        }
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        resp = self._client.post("/v1/contracts", json=payload, headers=headers)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def get_contract(self, contract_id: str) -> Dict[str, Any]:
        """Retrieve a contract by ID."""
        resp = self._client.get(f"/v1/contracts/{contract_id}")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def list_contracts(
        self,
        status: Optional[str] = None,
        environment: Optional[str] = None,
        worker_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List contracts for the tenant with optional filtering."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if environment:
            params["environment"] = environment
        if worker_id:
            params["worker_id"] = worker_id
        if cursor:
            params["cursor"] = cursor

        resp = self._client.get("/v1/contracts", params=params)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def fund_contract(self, contract_id: str) -> Dict[str, Any]:
        """Trigger funding authorization capture for a contract."""
        resp = self._client.post(f"/v1/contracts/{contract_id}/fund")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def cancel_contract(self, contract_id: str) -> Dict[str, Any]:
        """Cancel an unfunded or funded contract, voiding holds."""
        resp = self._client.post(f"/v1/contracts/{contract_id}/cancel")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def submit_milestone(
        self,
        contract_id: str,
        sequence: int,
        submission_code: str,
        worker_id: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit deliverable work for milestone verification."""
        payload: Dict[str, Any] = {
            "code": submission_code,
            "worker_id": worker_id or "anonymous_worker",
            "explanation": explanation,
        }
        resp = self._client.post(f"/v1/contracts/{contract_id}/milestones/{sequence}/submit", json=payload)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def get_receipt(self, contract_id: str) -> Dict[str, Any]:
        """Retrieve the cryptographic receipt for a completed contract."""
        resp = self._client.get(f"/v1/contracts/{contract_id}/receipt")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def verify_public_receipt(self, share_token: str) -> Dict[str, Any]:
        """Verify and inspect a public receipt via share token."""
        resp = self._client.get(f"/v1/receipts/{share_token}")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def get_worker_stats(self, worker_id: str) -> Dict[str, Any]:
        """Fetch worker reputation and completion metrics."""
        resp = self._client.get(f"/v1/workers/{worker_id}/stats")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def get_org_stats(self) -> Dict[str, Any]:
        """Fetch tenant statistics and settlement volumes."""
        resp = self._client.get("/v1/org/stats")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    def run_arena(self, scenario: str = "all", sync: bool = True) -> Dict[str, Any]:
        """Execute Red Team Arena adversarial tests."""
        payload = {"scenario": scenario, "sync": sync}
        resp = self._client.post("/v1/arena/run", json=payload, timeout=60.0)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    @staticmethod
    def verify_receipt_offline(receipt: Dict[str, Any]) -> bool:
        """Offline verification of receipt signature and hash."""
        return verify_receipt_data(receipt)


class AsyncPayLap(BaseClient):
    """Asynchronous PayLap client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
    ):
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=self.timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncPayLap":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def create_contract(
        self,
        title: str,
        milestones: List[Dict[str, Any]],
        worker_email: Optional[str] = None,
        deadline_days: int = 14,
        max_attempts: int = 3,
        environment: str = "simulated",
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "title": title,
            "milestones": milestones,
            "worker_email": worker_email,
            "deadline_days": deadline_days,
            "max_attempts": max_attempts,
            "environment": environment,
            "metadata": metadata or {},
        }
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        resp = await self._client.post("/v1/contracts", json=payload, headers=headers)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def get_contract(self, contract_id: str) -> Dict[str, Any]:
        resp = await self._client.get(f"/v1/contracts/{contract_id}")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def list_contracts(
        self,
        status: Optional[str] = None,
        environment: Optional[str] = None,
        worker_id: Optional[str] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if environment:
            params["environment"] = environment
        if worker_id:
            params["worker_id"] = worker_id
        if cursor:
            params["cursor"] = cursor

        resp = await self._client.get("/v1/contracts", params=params)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def fund_contract(self, contract_id: str) -> Dict[str, Any]:
        resp = await self._client.post(f"/v1/contracts/{contract_id}/fund")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def cancel_contract(self, contract_id: str) -> Dict[str, Any]:
        resp = await self._client.post(f"/v1/contracts/{contract_id}/cancel")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def submit_milestone(
        self,
        contract_id: str,
        sequence: int,
        submission_code: str,
        worker_id: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "code": submission_code,
            "worker_id": worker_id or "anonymous_worker",
            "explanation": explanation,
        }
        resp = await self._client.post(f"/v1/contracts/{contract_id}/milestones/{sequence}/submit", json=payload)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def get_receipt(self, contract_id: str) -> Dict[str, Any]:
        resp = await self._client.get(f"/v1/contracts/{contract_id}/receipt")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def verify_public_receipt(self, share_token: str) -> Dict[str, Any]:
        resp = await self._client.get(f"/v1/receipts/{share_token}")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def get_worker_stats(self, worker_id: str) -> Dict[str, Any]:
        resp = await self._client.get(f"/v1/workers/{worker_id}/stats")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def get_org_stats(self) -> Dict[str, Any]:
        resp = await self._client.get("/v1/org/stats")
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    async def run_arena(self, scenario: str = "all", sync: bool = True) -> Dict[str, Any]:
        payload = {"scenario": scenario, "sync": sync}
        resp = await self._client.post("/v1/arena/run", json=payload, timeout=60.0)
        _raise_for_status(resp)
        # pyrefly: ignore[no-any-return-explicit]
        return resp.json()

    @staticmethod
    def verify_receipt_offline(receipt: Dict[str, Any]) -> bool:
        return verify_receipt_data(receipt)
