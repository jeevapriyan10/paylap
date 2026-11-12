import pytest
from app.config import settings
from app.models import Contract, Milestone, Event
from app.services.paypal_fake import FakePayPal
from app.services.settlement import settle_milestone
from app.state import ContractStatus, MilestoneStatus


class MockFailingVoidPayPal(FakePayPal):
    def void_authorization(self, authorization_id: str, request_id: str):
        from app.services.paypal_base import PayPalError
        raise PayPalError(
            message="AUTHORIZATION_ALREADY_CAPTURED",
            status_code=422,
            debug_id="dbg-void-fail-789"
        )


def create_test_contract(db_session, num_milestones=2, max_attempts=1):
    c = Contract(
        id="c-strat-1",
        title="Strategy Test Contract",
        buyer_id="b-strat",
        worker_id="w-strat",
        worker_email="w@strat.com",
        total_cents=num_milestones * 200,
        currency="USD",
        status=ContractStatus.FUNDED.value,
        paypal_authorization_id="DEMO-AUTH-STRAT",
        mode="demo",
        max_attempts=max_attempts
    )
    db_session.add(c)
    for idx in range(1, num_milestones + 1):
        m = Milestone(
            id=f"m-strat-{idx}",
            contract_id=c.id,
            idx=idx,
            title=f"Milestone {idx}",
            amount_cents=200,
            spec="add(a, b)",
            public_tests="from solution import add\ndef test_add(): assert add(1, 1) == 2",
            status=MilestoneStatus.PENDING.value
        )
        db_session.add(m)
    db_session.commit()
    db_session.refresh(c)
    return c


def test_batch_at_end_capture_strategy(db_session):
    original_strategy = settings.PAYLAP_CAPTURE_STRATEGY
    original_arbiter = settings.PAYLAP_ARBITER_MODE
    settings.PAYLAP_CAPTURE_STRATEGY = "batch_at_end"
    settings.PAYLAP_ARBITER_MODE = "mock"
    try:
        c = create_test_contract(db_session, num_milestones=2)
        fake_prov = FakePayPal()

        # Submit Milestone 1
        res1 = settle_milestone(
            db=db_session,
            contract_id=c.id,
            milestone_idx=1,
            code="def add(a, b): return a + b\n",
            custom_provider=fake_prov
        )
        assert res1.passed is True
        assert res1.status == MilestoneStatus.VERIFIED_PENDING_SETTLEMENT.value
        # No captures yet!
        assert len(fake_prov.captures) == 0

        # Submit Milestone 2 (all milestones now verified)
        res2 = settle_milestone(
            db=db_session,
            contract_id=c.id,
            milestone_idx=2,
            code="def add(a, b): return a + b\n",
            custom_provider=fake_prov
        )
        assert res2.passed is True
        assert res2.status == MilestoneStatus.PAID.value

        # Exactly 1 capture for total amount (400 cents)
        assert len(fake_prov.captures) == 1
        cap_val = list(fake_prov.captures.values())[0]
        assert cap_val["amount_cents"] == 400
        assert cap_val["final_capture"] is True

        # Exactly 2 payouts dispatched
        assert len(fake_prov.payouts) == 2

        # Contract completed
        db_session.refresh(c)
        assert c.status == ContractStatus.COMPLETED.value
    finally:
        settings.PAYLAP_CAPTURE_STRATEGY = original_strategy
        settings.PAYLAP_ARBITER_MODE = original_arbiter


def test_void_fallback_handling_on_failure(db_session):
    c = create_test_contract(db_session, num_milestones=1, max_attempts=1)
    failing_prov = MockFailingVoidPayPal()

    # Submit bad code that triggers rejection and voiding
    res = settle_milestone(
        db=db_session,
        contract_id=c.id,
        milestone_idx=1,
        code="def add(a, b): return 0\n",
        custom_provider=failing_prov
    )
    assert res.passed is False
    assert res.status == MilestoneStatus.REJECTED.value

    # Contract should still transition to VOIDED
    db_session.refresh(c)
    assert c.status == ContractStatus.VOIDED.value

    # Check that VOID_FALLBACK_ERROR event was recorded with debug_id
    err_event = (
        db_session.query(Event)
        .filter(Event.contract_id == c.id, Event.type == "VOID_FALLBACK_ERROR")
        .first()
    )
    assert err_event is not None
    assert err_event.payload["debug_id"] == "dbg-void-fail-789"
    assert "remainder will be released at authorization expiry" in err_event.payload["note"]
