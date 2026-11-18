import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.logging_conf import (
    RedactingJsonFormatter,
    register_hidden_test_sentinel,
)
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_standard_error_format_404_and_request_id(client):
    # Request non-existent endpoint
    res = client.get("/v1/non_existent_route_404", headers={"X-Request-ID": "req_custom_test_123"})
    assert res.status_code == 404
    assert res.headers.get("X-Request-ID") == "req_custom_test_123"

    data = res.json()
    assert "error" in data
    err = data["error"]
    assert err["type"] == "not_found_error"
    assert err["code"] == "not_found"
    assert err["request_id"] == "req_custom_test_123"
    assert "message" in err
    # Assert zero stack traces in response
    assert "Traceback" not in res.text
    assert 'File "' not in res.text


def test_security_headers(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in res.headers.get("Content-Security-Policy", "")
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_healthz_and_readyz_probes(client):
    # Liveness probe
    res_liveness = client.get("/healthz")
    assert res_liveness.status_code == 200
    assert res_liveness.json() == {"status": "ok"}

    # Readiness probe
    res_readiness = client.get("/readyz")
    assert res_readiness.status_code == 200
    data = res_readiness.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert "migration_version" in data
    assert data["job_heartbeat"] in ("fresh", "initialized")


def test_redaction_filter_scrubs_all_sentinels():
    # 1. Define planted sentinels
    api_key_sentinel = "pl_live_1234567890abcdef_fedcba09876543211234567890abcdef"
    password_sentinel = "SuperSecretMasterPassword123!"
    auth_header_sentinel = "Authorization: Bearer secret_bearer_token_xyz"
    session_sentinel = "paylap_session=secret_session_token_cookie_val"
    hidden_test_sentinel = "def test_hidden_secret_eval_suite(): assert secret_oracle() == 42"

    register_hidden_test_sentinel(hidden_test_sentinel)

    # 2. Setup logger with RedactingJsonFormatter
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(RedactingJsonFormatter())

    test_logger = logging.getLogger("test.redaction")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)

    # 3. Log planted sentinels
    test_logger.info(f"Generated user API key: {api_key_sentinel}")
    test_logger.info(f'User login payload: {{"password": "{password_sentinel}", "email": "test@example.com"}}')
    test_logger.info(f"Incoming request header: {auth_header_sentinel}")
    test_logger.info(f"Cookie received: {session_sentinel}; Path=/")
    test_logger.info(f"Running milestone suite: {hidden_test_sentinel}")

    handler.flush()
    logged_output = log_stream.getvalue()

    # 4. Assert NONE of the raw planted sentinels exist in the logged output
    assert api_key_sentinel not in logged_output
    assert password_sentinel not in logged_output
    assert "secret_bearer_token_xyz" not in logged_output
    assert "secret_session_token_cookie_val" not in logged_output
    assert hidden_test_sentinel not in logged_output

    # 5. Assert redaction markers are present
    assert "[REDACTED_API_KEY]" in logged_output
    assert "[REDACTED]" in logged_output
    assert "[REDACTED_HIDDEN_TEST]" in logged_output

    # 6. Verify each line parses as valid JSON
    for line in logged_output.strip().split("\n"):
        if line.strip():
            parsed = json.loads(line)
            assert "timestamp" in parsed
            assert "level" in parsed
            assert "message" in parsed


def test_token_bucket_rate_limiting(client):
    # Test rate limiting using a specific IP
    headers = {"X-Forwarded-For": "198.51.100.42"}

    # Rapid requests to trigger rate limit (IP capacity is 60)
    throttled = False
    for i in range(70):
        res = client.get("/v1/system/health", headers=headers)
        if res.status_code == 429:
            throttled = True
            assert "Retry-After" in res.headers
            err = res.json()["error"]
            assert err["type"] == "rate_limit_error"
            assert err["code"] == "rate_limit_exceeded"
            break

    assert throttled is True, "Expected rate limit (429) was not triggered after 70 rapid requests"
