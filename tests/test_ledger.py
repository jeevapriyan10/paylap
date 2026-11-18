import hashlib

from app.ids import generate_id
from app.ledger import append_event, verify_chain
from app.models import Contract, Event, Organization


def _create_test_contract(db_session):
    org_id = generate_id("org")
    org = Organization(
        id=org_id,
        name="Ledger Test Org",
        slug=f"slug_{org_id}",
    )
    db_session.add(org)
    db_session.commit()

    cid = generate_id("ctr")
    c = Contract(
        id=cid,
        org_id=org_id,
        title="Ledger Test Contract",
        worker_id="w-ledger",
        worker_email="w@ledger.com",
        environment="simulated",
        total_cents=1000,
        currency="USD",
        status="FUNDED",
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_empty_ledger_is_valid(db_session):
    c = _create_test_contract(db_session)
    is_valid, err, broken_seq = verify_chain(db_session, contract_id=c.id)
    assert is_valid is True
    assert err is None
    assert broken_seq is None


def test_append_events_creates_valid_hash_chain(db_session):
    c = _create_test_contract(db_session)
    e1 = append_event(
        db_session,
        event_type="CONTRACT_CREATED",
        payload={"title": "Test Task", "total_cents": 500},
        contract_id=c.id,
        org_id=c.org_id,
        simulated=False,
    )
    assert e1.seq == 1
    expected_genesis = hashlib.sha256(f"paylap:genesis:{c.id}".encode("utf-8")).hexdigest()
    assert e1.prev_hash == expected_genesis
    assert len(e1.event_hash) == 64

    e2 = append_event(
        db_session,
        event_type="ORDER_CREATED",
        payload={"order_id": "ORD-123"},
        contract_id=c.id,
        org_id=c.org_id,
        simulated=False,
    )
    assert e2.seq == 2
    assert e2.prev_hash == e1.event_hash

    e3 = append_event(
        db_session,
        event_type="MILESTONE_PAID",
        payload={"amount_cents": 250, "payout_batch_id": "BATCH-1"},
        contract_id=c.id,
        org_id=c.org_id,
        simulated=True,
    )
    assert e3.seq == 3
    assert e3.prev_hash == e2.event_hash

    is_valid, err, broken_seq = verify_chain(db_session, contract_id=c.id)
    assert is_valid is True
    assert err is None
    assert broken_seq is None


def test_tamper_payload_detected(db_session):
    c = _create_test_contract(db_session)
    append_event(db_session, "EVENT_1", {"data": "ok"}, contract_id=c.id, org_id=c.org_id)
    append_event(db_session, "EVENT_2", {"data": "important"}, contract_id=c.id, org_id=c.org_id)
    append_event(db_session, "EVENT_3", {"data": "final"}, contract_id=c.id, org_id=c.org_id)
    db_session.commit()

    # Tamper with the second event payload directly in the database
    e2 = db_session.query(Event).filter(Event.contract_id == c.id, Event.seq == 2).first()
    e2.payload = {"data": "hacked"}
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session, contract_id=c.id)
    assert is_valid is False
    assert broken_seq == 2
    assert "Corrupted hash at seq 2" in err or "Tampered event at seq 2" in err


def test_tamper_prev_hash_detected(db_session):
    c = _create_test_contract(db_session)
    append_event(db_session, "EVENT_1", {"data": 1}, contract_id=c.id, org_id=c.org_id)
    append_event(db_session, "EVENT_2", {"data": 2}, contract_id=c.id, org_id=c.org_id)
    db_session.commit()

    e2 = db_session.query(Event).filter(Event.contract_id == c.id, Event.seq == 2).first()
    e2.prev_hash = "a" * 64
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session, contract_id=c.id)
    assert is_valid is False
    assert broken_seq == 2
    assert "Broken link at seq 2" in err


def test_deletion_gap_detected(db_session):
    c = _create_test_contract(db_session)
    append_event(db_session, "EVENT_1", {"data": 1}, contract_id=c.id, org_id=c.org_id)
    append_event(db_session, "EVENT_2", {"data": 2}, contract_id=c.id, org_id=c.org_id)
    append_event(db_session, "EVENT_3", {"data": 3}, contract_id=c.id, org_id=c.org_id)
    db_session.commit()

    # Delete the middle event
    e2 = db_session.query(Event).filter(Event.contract_id == c.id, Event.seq == 2).first()
    db_session.delete(e2)
    db_session.commit()

    is_valid, err, broken_seq = verify_chain(db_session, contract_id=c.id)
    assert is_valid is False
    assert broken_seq == 3
    assert "Sequence gap" in err or "Sequence break" in err
