from enum import Enum
from typing import Optional


class ContractStatus(str, Enum):
    CREATED = "CREATED"
    AWAITING_FUNDING = "AWAITING_FUNDING"
    FUNDED = "FUNDED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    PAID = "PAID"
    REJECTED = "REJECTED"


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state machine transition is attempted."""
    pass


# Legal Contract transitions:
# CREATED -> AWAITING_FUNDING -> FUNDED -> COMPLETED
# In demo mode, CREATED can also transition directly to FUNDED
# FUNDED -> VOIDED (attempts exhausted or buyer cancellation)
# AWAITING_FUNDING -> CANCELLED (buyer abandoned/cancelled at PayPal)
# Any state -> ERROR (must have error event/reason)
CONTRACT_TRANSITIONS = {
    ContractStatus.CREATED: {ContractStatus.AWAITING_FUNDING, ContractStatus.FUNDED, ContractStatus.ERROR},
    ContractStatus.AWAITING_FUNDING: {ContractStatus.FUNDED, ContractStatus.CANCELLED, ContractStatus.ERROR},
    ContractStatus.FUNDED: {ContractStatus.COMPLETED, ContractStatus.VOIDED, ContractStatus.ERROR},
    ContractStatus.COMPLETED: {ContractStatus.ERROR},
    ContractStatus.VOIDED: {ContractStatus.ERROR},
    ContractStatus.CANCELLED: {ContractStatus.ERROR},
    ContractStatus.ERROR: set(),
}

# Legal Milestone transitions:
# PENDING -> SUBMITTED -> VERIFYING -> PAID
# VERIFYING -> REJECTED
# REJECTED -> PENDING (when retried) or back to SUBMITTED if re-submitted
MILESTONE_TRANSITIONS = {
    MilestoneStatus.PENDING: {MilestoneStatus.SUBMITTED},
    MilestoneStatus.SUBMITTED: {MilestoneStatus.VERIFYING},
    MilestoneStatus.VERIFYING: {MilestoneStatus.PAID, MilestoneStatus.REJECTED},
    MilestoneStatus.REJECTED: {MilestoneStatus.PENDING, MilestoneStatus.SUBMITTED},
    MilestoneStatus.PAID: set(),
}


def transition_contract(
    current_status: str,
    target_status: ContractStatus,
    error_reason: Optional[str] = None
) -> ContractStatus:
    """Validate and perform a state transition on a contract."""
    curr = ContractStatus(current_status)
    if target_status == ContractStatus.ERROR:
        if not error_reason or not error_reason.strip():
            raise InvalidStateTransitionError("Transition to ERROR requires a non-empty error reason.")
        return target_status

    allowed = CONTRACT_TRANSITIONS.get(curr, set())
    if target_status not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal contract transition from {curr.value} to {target_status.value}."
        )
    return target_status


def transition_milestone(
    current_status: str,
    target_status: MilestoneStatus
) -> MilestoneStatus:
    """Validate and perform a state transition on a milestone."""
    curr = MilestoneStatus(current_status)
    allowed = MILESTONE_TRANSITIONS.get(curr, set())
    if target_status not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal milestone transition from {curr.value} to {target_status.value}."
        )
    return target_status
