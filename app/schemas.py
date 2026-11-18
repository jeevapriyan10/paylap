import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def cents_to_usd_str(cents: int) -> str:
    """Format integer cents as an exact USD decimal string with 2 decimal places."""
    if not isinstance(cents, int):
        raise TypeError(f"cents must be an integer, got {type(cents)}")
    dec = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    return f"{dec:.2f}"


def usd_str_to_cents(amount_str: str) -> int:
    """
    Parse a USD currency string into integer cents.
    Strictly forbids floats and accepts only strings formatted with up to two decimal places.
    """
    if not isinstance(amount_str, str):
        raise TypeError(f"Amount must be a string representation of currency, got {type(amount_str).__name__}")

    amount_clean = amount_str.strip()
    if not re.match(r"^\d+(\.\d{1,2})?$", amount_clean):
        raise ValueError(f"Invalid USD amount format '{amount_str}'. Must be a positive decimal string with up to 2 decimal places.")

    try:
        dec = Decimal(amount_clean)
    except InvalidOperation:
        raise ValueError(f"Invalid decimal string '{amount_str}'")

    if dec <= 0:
        raise ValueError(f"Amount must be positive, got {dec}")

    cents = int((dec * Decimal(100)).quantize(Decimal("1")))
    return cents


class MilestoneCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    amount: Optional[str] = Field(None, description="USD amount as string, e.g. '2.50'")
    amount_minor: Optional[int] = Field(None, description="Integer minor units (cents)")
    amount_cents: Optional[int] = Field(None, description="Alias for amount_minor")
    spec: str = Field(..., min_length=1, description="Task specification and requirements")
    public_tests: str = Field(..., min_length=1, description="Public test suite run against submitted solution")
    hidden_tests: Optional[str] = Field(None, description="Optional hidden test suite (never returned in responses)")
    verifier_type: str = Field("python_code", description="Verifier plugin name: python_code, json_data, text_rules")
    verifier_config: Optional[dict] = Field(None, description="Optional configuration for verifiers")

    @model_validator(mode="after")
    def resolve_amount_cents(self) -> "MilestoneCreate":
        if self.amount_minor is not None:
            cents = self.amount_minor
        elif self.amount_cents is not None:
            cents = self.amount_cents
        elif self.amount is not None:
            cents = usd_str_to_cents(self.amount)
        else:
            raise ValueError("Milestone must have either 'amount_minor', 'amount_cents', or 'amount' (USD string)")
        
        self.amount_minor = cents
        self.amount_cents = cents
        self.amount = cents_to_usd_str(cents)
        return self


class ContractCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    buyer_id: Optional[str] = Field(None, max_length=128)
    worker_id: str = Field(..., min_length=1, max_length=128)
    worker_email: str = Field(..., min_length=3, max_length=255)
    environment: str = Field("simulated", pattern="^(simulated|sandbox|live|demo)$")
    deadline_at: Optional[datetime] = None
    external_reference: Optional[str] = Field(None, max_length=255)
    metadata: Optional[Dict[str, Any]] = None
    capture_strategy: str = Field("partial", pattern="^(partial|batch_at_end)$")
    milestones: List[MilestoneCreate] = Field(..., min_length=1, max_length=5)
    max_attempts: int = Field(2, ge=1, le=10)

    @field_validator("worker_email")
    @classmethod
    def validate_worker_email(cls, v: str) -> str:
        v_clean = v.strip()
        if "@" not in v_clean or "." not in v_clean.split("@")[-1]:
            raise ValueError(f"Invalid email address '{v}'")
        return v_clean

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is not None:
            if len(v) > 16:
                raise ValueError("Contract metadata cannot exceed 16 keys")
            serialized = json.dumps(v)
            if len(serialized.encode("utf-8")) > 4096:
                raise ValueError("Contract metadata cannot exceed 4 KB")
        return v


class MilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    idx: int
    title: str
    amount_cents: int
    amount_usd: str
    spec: str
    public_tests: str
    verifier_type: str = "python_code"
    verifier_config: Optional[dict] = None
    status: str
    attempts: int
    capture_id: Optional[str] = None
    payout_batch_id: Optional[str] = None
    payout_status: Optional[str] = None
    paid_at: Optional[datetime] = None
    # NOTE: hidden_tests is explicitly omitted and NEVER returned!


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    buyer_id: str
    worker_id: str
    worker_email: str
    total_cents: int
    total_usd: str
    currency: str
    status: str
    environment: str = "simulated"
    paypal_order_id: Optional[str] = None
    paypal_authorization_id: Optional[str] = None
    authorization_expires_at: Optional[datetime] = None
    approve_url: Optional[str] = None
    mode: str = "demo"
    max_attempts: int
    capture_strategy: str = "partial"
    external_reference: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    hidden_commitment: Optional[str] = None
    milestones: List[MilestoneResponse]
    created_at: datetime
    updated_at: datetime


class PaginatedContractsResponse(BaseModel):
    items: List[ContractResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    total: Optional[int] = None


class MilestoneSubmit(BaseModel):
    code: str = Field(..., min_length=1, description="Solution code or text submission to verify")


class MilestoneOutcome(BaseModel):
    contract_id: str
    milestone_idx: int
    status: str
    passed: bool
    sandbox_summary: dict
    capture_id: Optional[str] = None
    payout_batch_id: Optional[str] = None
    payout_status: Optional[str] = None
    simulated: bool
    error: Optional[str] = None
    gate_decided: Optional[str] = None
    risk_flags: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    mode: str
    payout_mode: str
    arbiter_mode: str
    paypal_configured: bool
    ledger_chain_valid: bool
    verifiers: List[str] = Field(default_factory=list)
