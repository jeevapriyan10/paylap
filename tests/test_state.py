import pytest
from app.state import (
    ContractStatus,
    MilestoneStatus,
    InvalidStateTransitionError,
    transition_contract,
    transition_milestone,
)


def test_contract_legal_happy_path():
    s = ContractStatus.CREATED
    s = transition_contract(s, ContractStatus.AWAITING_FUNDING)
    assert s == ContractStatus.AWAITING_FUNDING
    s = transition_contract(s, ContractStatus.FUNDED)
    assert s == ContractStatus.FUNDED
    s = transition_contract(s, ContractStatus.COMPLETED)
    assert s == ContractStatus.COMPLETED


def test_contract_demo_auto_funded_path():
    s = ContractStatus.CREATED
    s = transition_contract(s, ContractStatus.FUNDED)
    assert s == ContractStatus.FUNDED


def test_contract_buyer_cancellation_paths():
    # Cancellation from AWAITING_FUNDING
    s = transition_contract(ContractStatus.AWAITING_FUNDING, ContractStatus.CANCELLED)
    assert s == ContractStatus.CANCELLED

    # Voiding from FUNDED
    s = transition_contract(ContractStatus.FUNDED, ContractStatus.VOIDED)
    assert s == ContractStatus.VOIDED


def test_contract_illegal_transitions():
    # Cannot jump directly from CREATED to COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        transition_contract(ContractStatus.CREATED, ContractStatus.COMPLETED)

    # Cannot go from COMPLETED to FUNDED
    with pytest.raises(InvalidStateTransitionError):
        transition_contract(ContractStatus.COMPLETED, ContractStatus.FUNDED)

    # Cannot cancel after completion
    with pytest.raises(InvalidStateTransitionError):
        transition_contract(ContractStatus.COMPLETED, ContractStatus.CANCELLED)


def test_contract_error_transition_requires_reason():
    with pytest.raises(InvalidStateTransitionError):
        transition_contract(ContractStatus.FUNDED, ContractStatus.ERROR, error_reason="")

    s = transition_contract(
        ContractStatus.FUNDED, ContractStatus.ERROR, error_reason="PayPal network crash"
    )
    assert s == ContractStatus.ERROR


def test_milestone_legal_transitions():
    s = MilestoneStatus.PENDING
    s = transition_milestone(s, MilestoneStatus.SUBMITTED)
    assert s == MilestoneStatus.SUBMITTED
    s = transition_milestone(s, MilestoneStatus.VERIFYING)
    assert s == MilestoneStatus.VERIFYING
    s = transition_milestone(s, MilestoneStatus.PAID)
    assert s == MilestoneStatus.PAID


def test_milestone_rejection_and_retry():
    s = MilestoneStatus.VERIFYING
    s = transition_milestone(s, MilestoneStatus.REJECTED)
    assert s == MilestoneStatus.REJECTED

    # Retry resets back to PENDING or resubmits directly to SUBMITTED
    s = transition_milestone(s, MilestoneStatus.PENDING)
    assert s == MilestoneStatus.PENDING

    s2 = transition_milestone(MilestoneStatus.REJECTED, MilestoneStatus.SUBMITTED)
    assert s2 == MilestoneStatus.SUBMITTED


def test_milestone_illegal_transitions():
    # Cannot jump directly from PENDING to PAID
    with pytest.raises(InvalidStateTransitionError):
        transition_milestone(MilestoneStatus.PENDING, MilestoneStatus.PAID)

    # Cannot transition out of PAID
    with pytest.raises(InvalidStateTransitionError):
        transition_milestone(MilestoneStatus.PAID, MilestoneStatus.PENDING)
