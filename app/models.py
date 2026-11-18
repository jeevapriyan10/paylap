import enum
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from app.ids import generate_id


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_short_id() -> str:
    """Backwards-compatible short id generator."""
    return generate_id("id")


class Base(DeclarativeBase):
    pass


# ==============================================================================
# AUTH & GLOBAL TABLES (NO RLS)
# ==============================================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("usr"))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    memberships: Mapped[List["Membership"]] = relationship("Membership", back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[List["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("org"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    arbiter_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    memberships: Mapped[List["Membership"]] = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("mem"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # owner | admin | developer | viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="memberships")
    user: Mapped["User"] = relationship("User", back_populates="memberships")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("ses"))
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("key"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    lookup_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # pl_test | pl_live
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    scopes: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    environment_class: Mapped[str] = mapped_column(String(16), nullable=False)  # test | live
    created_by: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class SigningKey(Base):
    __tablename__ = "signing_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # key id (e.g., ed25519_2026_01)
    public_key_bytes: Mapped[str] = mapped_column(String(128), nullable=False)  # hex or base64
    encrypted_private_key: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


# ==============================================================================
# TENANT TABLES (RLS ENABLED AND FORCED)
# ==============================================================================

class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("ctr"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    worker_email: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="simulated")  # simulated | sandbox | live
    is_playground: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="CREATED", nullable=False)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    paypal_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    paypal_authorization_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    approve_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    capture_strategy: Mapped[str] = mapped_column(String(32), default="partial", nullable=False)
    hidden_commitment: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Backwards-compatible aliases
    @property
    def mode(self) -> str:
        return "demo" if self.environment == "simulated" else self.environment

    @mode.setter
    def mode(self, val: str) -> None:
        self.environment = "simulated" if val == "demo" else val

    @property
    def buyer_id(self) -> str:
        return self.org_id

    @buyer_id.setter
    def buyer_id(self, val: str) -> None:
        self.org_id = val

    milestones: Mapped[List["Milestone"]] = relationship("Milestone", back_populates="contract", cascade="all, delete-orphan", order_by="Milestone.sequence")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="contract", order_by="Event.seq")


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("contract_id", "sequence", name="uq_milestone_contract_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("mst"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(64), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[str] = mapped_column(Text, nullable=False)
    verifier_type: Mapped[str] = mapped_column(String(32), default="python_code", nullable=False)
    verifier_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    public_tests: Mapped[str] = mapped_column(Text, nullable=False)
    hidden_tests: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hidden_commitment_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    capture_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payout_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payout_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    contract: Mapped["Contract"] = relationship("Contract", back_populates="milestones")

    # Backwards-compatible aliases
    @property
    def idx(self) -> int:
        return self.sequence

    @idx.setter
    def idx(self, val: int) -> None:
        self.sequence = val

    @property
    def attempts(self) -> int:
        return self.attempts_count

    @attempts.setter
    def attempts(self, val: int) -> None:
        self.attempts_count = val

    @property
    def payout_batch_id(self) -> Optional[str]:
        return self.payout_id

    @payout_batch_id.setter
    def payout_batch_id(self, val: Optional[str]) -> None:
        self.payout_id = val

    @property
    def hidden_commitment(self) -> Optional[str]:
        return self.hidden_commitment_hash

    @hidden_commitment.setter
    def hidden_commitment(self, val: Optional[str]) -> None:
        self.hidden_commitment_hash = val


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("contract_id", "seq", name="uq_event_contract_seq"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("evt"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(64), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    contract: Mapped["Contract"] = relationship("Contract", back_populates="events")

    # Backwards-compatible aliases
    @property
    def type(self) -> str:
        return self.event_type

    @type.setter
    def type(self, val: str) -> None:
        self.event_type = val

    @property
    def hash(self) -> str:
        return self.event_hash

    @hash.setter
    def hash(self, val: str) -> None:
        self.event_hash = val

    @property
    def simulated(self) -> bool:
        return bool(self.payload.get("simulated", False)) if isinstance(self.payload, dict) else False

    @property
    def simulated(self) -> bool:
        if isinstance(self.payload, dict):
            return self.payload.get("simulated", False)
        return False


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("org_id", "environment", name="uq_policy_org_env"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("pol"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)  # simulated | sandbox | live
    max_task_cents: Mapped[int] = mapped_column(Integer, default=2500, nullable=False)
    daily_cap_cents: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    max_milestones: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    worker_allowlist: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    require_hidden_tests: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_contract_days: Mapped[int] = mapped_column(Integer, default=28, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class OrgPayPalCredential(Base):
    __tablename__ = "org_paypal_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "environment", name="uq_paypal_cred_org_env"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("cred"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)  # sandbox | live
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_client_secret: Mapped[str] = mapped_column(String(1024), nullable=False)
    webhook_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("ep"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    events_filter: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("del"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)  # PENDING | SUCCESS | FAILED
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_idempotency_org_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("idem"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("rec"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    contracts_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discrepancies_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OrgAuditLog(Base):
    __tablename__ = "org_audit_log"
    __table_args__ = (
        UniqueConstraint("org_id", "seq", name="uq_org_audit_seq"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("aud"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShareToken(Base):
    __tablename__ = "share_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("tok"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(64), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint("org_id", "worker_id", name="uq_worker_org_worker_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("wrk"))
    org_id: Mapped[str] = mapped_column(String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    email_masked: Mapped[str] = mapped_column(String(255), nullable=False)
    total_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reputation_score: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


# List of all tenant table names that require Row-Level Security
TENANT_TABLES = [
    "contracts",
    "milestones",
    "events",
    "policies",
    "org_paypal_credentials",
    "webhook_endpoints",
    "webhook_deliveries",
    "idempotency_keys",
    "reconciliation_runs",
    "org_audit_log",
    "share_tokens",
    "workers",
]
