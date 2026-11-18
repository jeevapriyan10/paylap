import pytest

from app.ids import generate_id
from app.ledger import append_event
from app.models import Contract
from app.routers.stream import event_stream_generator


def _make_contract(db_session, auth_org, cid=None):
    contract_id = cid or generate_id("ctr")
    c = Contract(
        id=contract_id,
        org_id=auth_org["org_id"],
        title="Stream Test Contract",
        worker_id="w-stream",
        worker_email="w@stream.com",
        environment="simulated",
        total_cents=1000,
        currency="USD",
        status="FUNDED",
    )
    db_session.add(c)
    db_session.commit()
    return c


def test_stream_returns_events(client, db_session, auth_org):
    c = _make_contract(db_session, auth_org)
    e1 = append_event(db_session, "STREAM_TEST_1", {"message": "hello"}, contract_id=c.id, org_id=auth_org["org_id"])
    e2 = append_event(db_session, "STREAM_TEST_2", {"message": "world"}, contract_id=c.id, org_id=auth_org["org_id"])
    db_session.commit()

    res = client.get("/v1/stream?poll_once=true")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    content = res.text
    assert f"id: {e1.seq}" in content
    assert f"event: {e1.event_type}" in content
    assert f"id: {e2.seq}" in content
    assert f"event: {e2.event_type}" in content


def test_stream_reconnection_after_query_param(client, db_session, auth_org):
    c = _make_contract(db_session, auth_org)
    e1 = append_event(db_session, "RECON_1", {"idx": 1}, contract_id=c.id, org_id=auth_org["org_id"])
    e2 = append_event(db_session, "RECON_2", {"idx": 2}, contract_id=c.id, org_id=auth_org["org_id"])
    e3 = append_event(db_session, "RECON_3", {"idx": 3}, contract_id=c.id, org_id=auth_org["org_id"])
    db_session.commit()

    # Reconnect after e2.seq
    res = client.get(f"/v1/stream?after={e2.seq}&poll_once=true")
    assert res.status_code == 200
    content = res.text

    assert f"id: {e1.seq}" not in content
    assert f"id: {e2.seq}" not in content
    assert f"id: {e3.seq}" in content
    assert f"event: {e3.event_type}" in content


def test_stream_last_event_id_header(client, db_session, auth_org):
    c = _make_contract(db_session, auth_org)
    e1 = append_event(db_session, "HDR_1", {"idx": 1}, contract_id=c.id, org_id=auth_org["org_id"])
    e2 = append_event(db_session, "HDR_2", {"idx": 2}, contract_id=c.id, org_id=auth_org["org_id"])
    db_session.commit()

    res = client.get(
        "/v1/stream?poll_once=true",
        headers={"Last-Event-ID": str(e1.seq)},
    )
    assert res.status_code == 200
    content = res.text

    assert f"id: {e1.seq}" not in content
    assert f"id: {e2.seq}" in content


def test_stream_filter_by_contract_id(client, db_session, auth_org):
    c_a = _make_contract(db_session, auth_org)
    c_b = _make_contract(db_session, auth_org)
    e_a = append_event(db_session, "EVT_A", {"target": "A"}, contract_id=c_a.id, org_id=auth_org["org_id"])
    e_b = append_event(db_session, "EVT_B", {"target": "B"}, contract_id=c_b.id, org_id=auth_org["org_id"])
    db_session.commit()

    res = client.get(f"/v1/stream?contract_id={c_a.id}&poll_once=true")
    assert res.status_code == 200
    content = res.text

    assert c_a.id in content
    assert "EVT_A" in content
    assert c_b.id not in content
    assert "EVT_B" not in content


@pytest.mark.anyio
async def test_stream_heartbeat_emission(db_session, auth_org):
    # Test generator with very small heartbeat interval
    gen = event_stream_generator(
        org_id=auth_org["org_id"],
        after_seq=999999,
        db=db_session,
        heartbeat_interval=0.05,
        poll_once=False,
    )
    items = []
    async for chunk in gen:
        items.append(chunk)
        if len(items) >= 2:
            break

    assert len(items) >= 2
    assert any(": ping" in item for item in items)
