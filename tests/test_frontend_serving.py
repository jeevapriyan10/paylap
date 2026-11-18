from fastapi.testclient import TestClient

from app.main import app


def test_frontend_spa_root_serving():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert '<div id="root">' in res.text
    assert "PayLap" in res.text


def test_frontend_spa_client_side_routing_fallback():
    client = TestClient(app)
    res = client.get("/contracts/ctr_mock123")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert '<div id="root">' in res.text

    res_receipt = client.get("/receipts/shr_mocktoken")
    assert res_receipt.status_code == 200
    assert "text/html" in res_receipt.headers["content-type"]


def test_api_routes_not_swallowed_by_spa_fallback():
    client = TestClient(app)
    res = client.get("/v1/nonexistent_route_test")
    assert res.status_code == 404
    data = res.json()
    assert "error" in data or "detail" in data
