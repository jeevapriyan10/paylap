import pytest
from pydantic import ValidationError
from app.config import Settings


def test_config_demo_mode_allows_missing_paypal_keys():
    s = Settings(
        PAYLAP_MODE="demo",
        PAYPAL_CLIENT_ID="",
        PAYPAL_CLIENT_SECRET="",
        PAYLAP_RECEIPT_SECRET="",
    )
    assert s.PAYLAP_MODE == "demo"
    secret, key_id = s.receipt_signing_info
    assert key_id == "dev-ephemeral"
    assert len(secret) > 0


def test_config_live_mode_fails_on_missing_paypal_keys():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            PAYLAP_MODE="live",
            PAYPAL_CLIENT_ID="",
            PAYPAL_CLIENT_SECRET="",
            PAYLAP_RECEIPT_SECRET="receipt-secret",
        )
    assert "required settings are missing" in str(exc_info.value)
    assert "PAYPAL_CLIENT_ID" in str(exc_info.value)


def test_config_live_mode_fails_on_missing_receipt_secret():
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            PAYLAP_MODE="live",
            PAYPAL_CLIENT_ID="id-123",
            PAYPAL_CLIENT_SECRET="sec-456",
            PAYLAP_RECEIPT_SECRET="",
        )
    assert "PAYLAP_RECEIPT_SECRET" in str(exc_info.value)


def test_config_live_mode_succeeds_with_all_live_keys():
    s = Settings(
        PAYLAP_MODE="live",
        PAYPAL_CLIENT_ID="client-123",
        PAYPAL_CLIENT_SECRET="secret-456",
        PAYLAP_RECEIPT_SECRET="receipt-secret-789",
    )
    assert s.PAYLAP_MODE == "live"
    assert s.PAYPAL_CLIENT_ID == "client-123"
    secret, key_id = s.receipt_signing_info
    assert key_id == "configured"
    assert secret == "receipt-secret-789"


def test_config_missing_gemini_key_does_not_fail():
    s = Settings(
        PAYLAP_MODE="demo",
        GEMINI_API_KEY="",
    )
    assert s.GEMINI_API_KEY == ""
