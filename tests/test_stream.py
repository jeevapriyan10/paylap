import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from app.db import get_db
from app.ledger import append_event
from app.main import app
from app.routers.stream import event_stream_generator


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_stream_returns_events(client, db_session):
    e1 = append_event(db_session, "STREAM_TEST_1", {"message": "hello"}, contract_id="c_s1")
    e2 = append_event(db_session, "STREAM_TEST_2", {"message": "world"}, contract_id="c_s1")

    res = client.get("/api/stream?poll_once=true")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    content = res.text
    assert f"id: {e1.seq}" in content
    assert f"event: {e1.type}" in content
    assert f"id: {e2.seq}" in content
    assert f"event: {e2.type}" in content


def test_stream_reconnection_after_query_param(client, db_session):
    e1 = append_event(db_session, "RECON_1", {"idx": 1}, contract_id="c_recon")
    e2 = append_event(db_session, "RECON_2", {"idx": 2}, contract_id="c_recon")
    e3 = append_event(db_session, "RECON_3", {"idx": 3}, contract_id="c_recon")

    # Reconnect after e2.seq
    res = client.get(f"/api/stream?after={e2.seq}&poll_once=true")
    assert res.status_code == 200
    content = res.text

    assert f"id: {e1.seq}" not in content
    assert f"id: {e2.seq}" not in content
    assert f"id: {e3.seq}" in content
    assert f"event: {e3.type}" in content


def test_stream_last_event_id_header(client, db_session):
    e1 = append_event(db_session, "HDR_1", {"idx": 1}, contract_id="c_hdr")
    e2 = append_event(db_session, "HDR_2", {"idx": 2}, contract_id="c_hdr")

    res = client.get(
        "/api/stream?poll_once=true",
        headers={"Last-Event-ID": str(e1.seq)},
    )
    assert res.status_code == 200
    content = res.text

    assert f"id: {e1.seq}" not in content
    assert f"id: {e2.seq}" in content


def test_stream_filter_by_contract_id(client, db_session):
    e_a = append_event(db_session, "EVT_A", {"target": "A"}, contract_id="contract_A")
    e_b = append_event(db_session, "EVT_B", {"target": "B"}, contract_id="contract_B")

    res = client.get("/api/stream?contract_id=contract_A&poll_once=true")
    assert res.status_code == 200
    content = res.text

    assert "contract_A" in content
    assert "EVT_A" in content
    assert "contract_B" not in content
    assert "EVT_B" not in content


@pytest.mark.anyio
async def test_stream_heartbeat_emission(db_session):
    # Test generator with very small heartbeat interval
    gen = event_stream_generator(after_seq=9999, db=db_session, heartbeat_interval=0.1, poll_once=False)
    # Give generator a moment to produce heartbeat
    items = []
    async for chunk in gen:
        items.append(chunk)
        if len(items) >= 1:
            break

    assert any(": heartbeat" in item for item in items)
