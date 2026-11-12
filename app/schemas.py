from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional
import re
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict


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
    # Matches positive decimal numbers with optional 1 or 2 decimal digits: e.g. "5", "5.0", "5.00"
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
    amount: str = Field(..., description="USD amount as string, e.g. '2.50'")
    spec: str = Field(..., min_length=1, description="Task specification and requirements")
    public_tests: str = Field(..., min_length=1, description="Public test suite run against submitted solution")
    hidden_tests: Optional[str] = Field(None, description="Optional hidden test suite (never returned in responses)")
    verifier_type: str = Field("python_code", description="Verifier plugin name: python_code, json_data, text_rules")
    verifier_config: Optional[dict] = Field(None, description="Optional configuration for verifiers (schema, word counts, regex rules)")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        cents = usd_str_to_cents(v)
        return cents_to_usd_str(cents)


class ContractCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    buyer_id: str = Field(..., min_length=1, max_length=128)
    worker_id: str = Field(..., min_length=1, max_length=128)
    worker_email: str = Field(..., min_length=3, max_length=255)
    milestones: List[MilestoneCreate] = Field(default_factory=list)
    max_attempts: int = Field(1, ge=1, le=10)

    @field_validator("worker_email")
    @classmethod
    def validate_worker_email(cls, v: str) -> str:
        v_clean = v.strip()
        if "@" not in v_clean or "." not in v_clean.split("@")[-1]:
            raise ValueError(f"Invalid email address '{v}'")
        return v_clean


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
    paypal_order_id: Optional[str] = None
    paypal_authorization_id: Optional[str] = None
    approve_url: Optional[str] = None
    mode: str
    max_attempts: int
    milestones: List[MilestoneResponse]
    created_at: datetime
    updated_at: datetime


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
    version: str = "0.2.0"
    mode: str
    payout_mode: str
    arbiter_mode: str
    paypal_configured: bool
    ledger_chain_valid: bool
    verifiers: List[str] = Field(default_factory=list)
