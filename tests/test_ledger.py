import pytest
from app.ledger import append_event, verify_chain
from app.models import Event


def test_empty_ledger_is_valid(db_session):
    is_valid, err, broken_seq = verify_chain(db_session)
    assert is_valid is True
    assert err is None
    assert broken_seq is None


def test_append_events_creates_valid_hash_chain(db_session):
    e1 = append_event(
        db_session,
        event_type="CONTRACT_CREATED",
        payload={"title": "Test Task", "total_cents": 500},
        contract_id="c-001",
        simulated=False,
    )
    assert e1.seq == 1
    assert e1.prev_hash == "0" * 64
    assert len(e1.hash) == 64

    e2 = append_event(
        db_session,
        event_type="ORDER_CREATED",
        payload={"order_id": "ORD-123"},
        contract_id="c-001",
        simulated=False,
    )
    assert e2.seq == 2
    assert e2.prev_hash == e1.hash

    e3 = append_event(
        db_session,
        event_type="MILESTONE_PAID",
        payload={"amount_cents": 250, "payout_batch_id": "BATCH-1"},
        contract_id="c-001",
        simulated=True,
    )
    assert e3.seq == 3
    assert e3.prev_hash == e2.hash

    is_valid, err, broken_seq = verify_chain(db_session)
    assert is_valid is True
    assert err is None
    assert broken_seq is None


def test_tamper_payload_detected(db_session):
    append_event(db_session, "EVENT_1", {"data": "ok"})
    append_event(db_session, "EVENT_2", {"data": "important"})
    append_event(db_session, "EVENT_3", {"data": "final"})

    # Tamper with the second event payload directly in the database
    e2 = db_session.query(Event).filter(Event.seq == 2).first()
    e2.payload = {"data": "hacked"}
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session)
    assert is_valid is False
    assert broken_seq == 2
    assert "Tampered event at seq 2" in err


def test_tamper_prev_hash_detected(db_session):
    append_event(db_session, "EVENT_1", {"data": 1})
    append_event(db_session, "EVENT_2", {"data": 2})

    e2 = db_session.query(Event).filter(Event.seq == 2).first()
    e2.prev_hash = "a" * 64
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session)
    assert is_valid is False
    assert broken_seq == 2
    assert "Broken link at seq 2" in err


def test_deletion_gap_detected(db_session):
    append_event(db_session, "EVENT_1", {"data": 1})
    append_event(db_session, "EVENT_2", {"data": 2})
    append_event(db_session, "EVENT_3", {"data": 3})

    # Delete the middle event
    e2 = db_session.query(Event).filter(Event.seq == 2).first()
    db_session.delete(e2)
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session)
    assert is_valid is False
    assert broken_seq == 3
    assert "Sequence break" in err
