import base64
import pytest
from pydantic import ValidationError
from app.config import Settings


def test_config_defaults():
    s = Settings(PAYLAP_ENV="development")
    assert s.PAYLAP_ENV == "development"
    assert s.PAYLAP_SIGNUP_MODE == "closed"
    assert s.PAYLAP_ALLOW_LIVE is False
    assert s.PAYLAP_RUNNER == "process"
    assert s.PAYLAP_MAX_CONTRACT_DAYS == 28
    assert s.PAYLAP_AUTH_SAFETY_MARGIN_HOURS == 24
    assert s.PAYLAP_LLM_PROVIDER == "gemini"
    assert "http://localhost:3000" in s.PAYLAP_CORS_ORIGINS


def test_cors_origins_wildcard_rejected():
    with pytest.raises(ValidationError) as exc:
        Settings(PAYLAP_CORS_ORIGINS="http://localhost:3000,*")
    assert "cannot be '*'" in str(exc.value)

    with pytest.raises(ValidationError) as exc2:
        Settings(PAYLAP_CORS_ORIGINS=["*"])
    assert "cannot be '*'" in str(exc2.value)


def test_master_keys_parsing_and_active():
    key1_bytes = b"01234567890123456789012345678901"  # 32 bytes
    key2_bytes = b"abcdefghijklmnopqrstuvwxyz012345"  # 32 bytes
    b64_1 = base64.b64encode(key1_bytes).decode()
    b64_2 = base64.b64encode(key2_bytes).decode()

    s = Settings(PAYLAP_MASTER_KEYS=f"k1:{b64_1},k2:{b64_2}")
    parsed = s.parsed_master_keys
    assert len(parsed) == 2
    assert parsed["k1"] == key1_bytes
    assert parsed["k2"] == key2_bytes

    active_id, active_bytes = s.active_master_key
    assert active_id == "k1"
    assert active_bytes == key1_bytes


def test_production_fails_on_short_secret_key():
    valid_master = base64.b64encode(b"a" * 32).decode()
    with pytest.raises(ValidationError) as exc:
        Settings(
            PAYLAP_ENV="production",
            PAYLAP_SECRET_KEY="short-secret-under-32-bytes",
            PAYLAP_MASTER_KEYS=f"k1:{valid_master}",
            PAYLAP_RUNNER="remote",
        )
    assert "at least 32 bytes in production" in str(exc.value)


def test_production_fails_on_short_master_key():
    short_master = base64.b64encode(b"short-master-key").decode()
    with pytest.raises(ValidationError) as exc:
        Settings(
            PAYLAP_ENV="production",
            PAYLAP_SECRET_KEY="a" * 32,
            PAYLAP_MASTER_KEYS=f"k1:{short_master}",
            PAYLAP_RUNNER="remote",
        )
    assert "must be at least 32 bytes" in str(exc.value)


def test_production_refuses_insecure_process_runner():
    valid_master = base64.b64encode(b"a" * 32).decode()
    with pytest.raises(ValidationError) as exc:
        Settings(
            PAYLAP_ENV="production",
            PAYLAP_SECRET_KEY="a" * 32,
            PAYLAP_MASTER_KEYS=f"k1:{valid_master}",
            PAYLAP_RUNNER="process",
            PAYLAP_ALLOW_INSECURE_RUNNER=False,
        )
    assert "refuses process runner" in str(exc.value)


def test_production_succeeds_with_valid_keys_and_remote_runner():
    valid_master = base64.b64encode(b"a" * 32).decode()
    s = Settings(
        PAYLAP_ENV="production",
        PAYLAP_SECRET_KEY="a" * 32,
        PAYLAP_MASTER_KEYS=f"k1:{valid_master}",
        PAYLAP_RUNNER="remote",
    )
    assert s.PAYLAP_ENV == "production"
    assert s.PAYLAP_RUNNER == "remote"
