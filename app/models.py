import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON
)
from sqlalchemy.orm import relationship
from app.db import Base


def generate_short_id() -> str:
    """Generate a clean 12-character hexadecimal ID."""
    return uuid.uuid4().hex[:12]


def utc_now() -> datetime:
    """Return timezone-naive UTC timestamp for consistent DB storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(String(36), primary_key=True, default=generate_short_id)
    title = Column(String(255), nullable=False)
    buyer_id = Column(String(128), nullable=False)
    worker_id = Column(String(128), nullable=False)
    worker_email = Column(String(255), nullable=False)
    total_cents = Column(Integer, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(String(32), nullable=False, default="CREATED")
    paypal_order_id = Column(String(128), nullable=True)
    paypal_authorization_id = Column(String(128), nullable=True)
    approve_url = Column(String(1024), nullable=True)
    mode = Column(String(16), nullable=False, default="demo")
    max_attempts = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    milestones = relationship("Milestone", back_populates="contract", cascade="all, delete-orphan", order_by="Milestone.idx")
    events = relationship("Event", back_populates="contract", order_by="Event.seq")


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(String(36), primary_key=True, default=generate_short_id)
    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=False, index=True)
    idx = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    spec = Column(Text, nullable=False)
    public_tests = Column(Text, nullable=False)
    hidden_tests = Column(Text, nullable=True)  # Never returned by API responses
    status = Column(String(32), nullable=False, default="PENDING")
    attempts = Column(Integer, default=0, nullable=False)
    capture_id = Column(String(128), nullable=True)
    payout_batch_id = Column(String(128), nullable=True)
    payout_status = Column(String(32), nullable=True)
    paid_at = Column(DateTime, nullable=True)

    contract = relationship("Contract", back_populates="milestones")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(String(36), ForeignKey("contracts.id"), nullable=True, index=True)
    seq = Column(Integer, nullable=False, unique=True, index=True)
    type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    simulated = Column(Boolean, default=False, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    contract = relationship("Contract", back_populates="events")
