import json
import httpx
import pytest
from app.services.paypal_base import PayPalError
from app.services.paypal_client import PayPalClient
from app.services.paypal_fake import FakePayPal


def make_oauth_response():
    return httpx.Response(
        200,
        json={"access_token": "mock-token-abc", "token_type": "Bearer", "expires_in": 3600},
    )


def test_token_caching():
    call_counts = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            call_counts["token"] += 1
            return make_oauth_response()
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = PayPalClient(
        client_id="id-1",
        client_secret="sec-1",
        base_url="https://api-m.sandbox.paypal.com",
        transport=transport,
    )

    t1 = client._get_access_token()
    t2 = client._get_access_token()
    assert t1 == "mock-token-abc"
    assert t2 == "mock-token-abc"
    assert call_counts["token"] == 1  # Token was cached!


def test_create_escrow_order_approve_link():
    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        if "/v2/checkout/orders" in str(request.url):
            body = json.loads(request.content.decode("utf-8"))
            assert body["intent"] == "AUTHORIZE"
            assert body["purchase_units"][0]["amount"]["value"] == "5.00"
            assert body["purchase_units"][0]["amount"]["currency_code"] == "USD"
            return httpx.Response(
                201,
                json={
                    "id": "ORD-LIVE-1",
                    "status": "CREATED",
                    "links": [
                        {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORD-LIVE-1"},
                        {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORD-LIVE-1"},
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.create_escrow_order(
        contract_id="c-001",
        amount_cents=500,
        return_url="http://localhost:8000/return",
        cancel_url="http://localhost:8000/cancel",
        request_id="req-order-1",
    )

    assert res["order_id"] == "ORD-LIVE-1"
    assert res["status"] == "CREATED"
    assert res["approve_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORD-LIVE-1"
    assert res["simulated"] is False


def test_create_escrow_order_payer_action_link_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        return httpx.Response(
            201,
            json={
                "id": "ORD-LIVE-2",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [
                    {"rel": "payer-action", "href": "https://www.sandbox.paypal.com/payment?token=ORD-LIVE-2"},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.create_escrow_order("c-002", 1000, "http://r", "http://c")
    assert res["approve_url"] == "https://www.sandbox.paypal.com/payment?token=ORD-LIVE-2"


def test_authorize_order_success():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        if "/v2/checkout/orders/ORD-123/authorize" in str(request.url):
            return httpx.Response(
                201,
                json={
                    "id": "ORD-123",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "authorizations": [
                                    {"id": "AUTH-789", "status": "CREATED"}
                                ]
                            }
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.authorize_order("ORD-123")
    assert res["authorization_id"] == "AUTH-789"
    assert res["status"] == "CREATED"


def test_capture_with_idempotency_and_final_flag():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        if "/v2/payments/authorizations/AUTH-789/capture" in str(request.url):
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={"id": "CAP-100", "status": "COMPLETED"},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.capture(
        authorization_id="AUTH-789",
        amount_cents=250,
        final_capture=True,
        request_id="capture-c-001-m1",
    )

    assert res["capture_id"] == "CAP-100"
    assert res["status"] == "COMPLETED"
    assert res["amount_cents"] == 250
    assert captured["headers"]["paypal-request-id"] == "capture-c-001-m1"
    assert captured["body"]["amount"]["value"] == "2.50"
    assert captured["body"]["final_capture"] is True


def test_void_authorization():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        if "/v2/payments/authorizations/AUTH-789/void" in str(request.url):
            captured["headers"] = dict(request.headers)
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.void_authorization("AUTH-789", request_id="void-c-001")
    assert res["status"] == "VOIDED"
    assert captured["headers"]["paypal-request-id"] == "void-c-001"


def test_send_payout_and_status():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        if request.method == "POST" and "/v1/payments/payouts" in str(request.url):
            captured["post_body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={"batch_header": {"payout_batch_id": "BATCH-999", "batch_status": "PENDING"}},
            )
        if request.method == "GET" and "/v1/payments/payouts/BATCH-999" in str(request.url):
            return httpx.Response(
                200,
                json={"batch_header": {"payout_batch_id": "BATCH-999", "batch_status": "SUCCESS"}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    res = client.send_payout("worker@test.com", 250, request_id="payout-c-001-m1")
    assert res["payout_batch_id"] == "BATCH-999"
    assert res["status"] == "PENDING"
    assert captured["post_body"]["items"][0]["amount"]["value"] == "2.50"
    assert captured["post_body"]["items"][0]["receiver"] == "worker@test.com"

    status_res = client.get_payout_status("BATCH-999")
    assert status_res["status"] == "SUCCESS"


def test_structured_error_with_debug_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v1/oauth2/token" in str(request.url):
            return make_oauth_response()
        return httpx.Response(
            422,
            headers={"paypal-debug-id": "dbg-xyz-123"},
            json={"name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be performed."},
        )

    transport = httpx.MockTransport(handler)
    client = PayPalClient(client_id="id", client_secret="sec", transport=transport)

    with pytest.raises(PayPalError) as exc_info:
        client.capture("AUTH-BAD", 100, False, "req-1")

    err = exc_info.value
    assert err.status_code == 422
    assert err.debug_id == "dbg-xyz-123"
    assert "The requested action could not be performed" in str(err)


def test_fake_paypal_provider():
    fake = FakePayPal(delay_seconds=0.0)

    order = fake.create_escrow_order("c-demo", 500, "http://r", "http://c")
    assert order["order_id"].startswith("DEMO-ORD-")
    assert order["simulated"] is True
    assert order["approve_url"] is None

    auth = fake.authorize_order(order["order_id"])
    assert auth["authorization_id"].startswith("DEMO-AUTH-")
    assert auth["simulated"] is True

    cap = fake.capture(auth["authorization_id"], 250, False, "req-cap")
    assert cap["capture_id"].startswith("DEMO-CAP-")
    assert cap["simulated"] is True

    payout = fake.send_payout("w@demo.com", 250, "req-pay")
    assert payout["payout_batch_id"].startswith("DEMO-BATCH-")
    assert payout["simulated"] is True

    void_res = fake.void_authorization(auth["authorization_id"], "req-void")
    assert void_res["status"] == "VOIDED"
    assert void_res["simulated"] is True
