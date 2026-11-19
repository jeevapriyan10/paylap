import base64
from typing import Any, Dict, List, Literal, Set, Tuple

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core Environment & Database
    PAYLAP_ENV: Literal["development", "test", "production"] = "development"
    DATABASE_URL: str = "postgresql+psycopg://paylap_app:paylap_app_pass@localhost:5432/paylap"
    DATABASE_URL_MIGRATE: str = "postgresql+psycopg://paylap_owner:paylap_owner_pass@localhost:5432/paylap"

    # Cryptography & Security Keys
    # Format: "key_id:base64_encoded_32_bytes_key,key_id2:base64_key2"
    PAYLAP_MASTER_KEYS: str = "k1:cGF5bGFwLW1hc3Rlci1rZXktYXV0by1kZXYtMzJieXRlcw=="
    PAYLAP_SECRET_KEY: str = "dev-secret-key-must-be-at-least-32-bytes-long-for-security"

    # Access, Auth & Signups
    PAYLAP_SIGNUP_MODE: Literal["closed", "open"] = "closed"
    PAYLAP_SIGNUP_CODE: str = ""
    PAYLAP_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:3000"]
    PAYLAP_ENABLE_DOCS: bool = True
    PAYLAP_ALLOW_LIVE: bool = False

    # Execution Runner
    PAYLAP_RUNNER: Literal["process", "remote"] = "process"
    PAYLAP_RUNNER_URL: str = "http://localhost:8001"
    PAYLAP_RUNNER_TOKEN: str = ""
    PAYLAP_ALLOW_INSECURE_RUNNER: bool = False

    # Background Operations & Safety Margins
    PAYLAP_JOBS_ENABLED: bool = True
    PAYLAP_MAX_CONTRACT_DAYS: int = 28
    PAYLAP_AUTH_SAFETY_MARGIN_HOURS: int = 24
    PAYLAP_RECONCILE_HOUR_UTC: int = 2

    # LLM Arbiter Configuration
    PAYLAP_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3-flash-preview"
    PAYLAP_LLM_HOURLY_CAP_PER_ORG: int = 60

    # Backwards-compatible / Stage 2 aliases
    PAYLAP_MODE: Literal["demo", "live"] = "demo"
    PAYLAP_PAYOUT_MODE: Literal["live", "simulated"] = "live"
    PAYLAP_PUBLIC_URL: str = "http://localhost:8000"
    PAYLAP_DB_URL: str = "sqlite:///./paylap.db"
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_WORKER_EMAIL: str = ""
    PAYLAP_ARBITER_MODE: Literal["auto", "gemini", "mock", "off"] = "auto"
    PAYLAP_ARBITER_FAIL: Literal["closed"] = "closed"
    PAYLAP_CAPTURE_STRATEGY: Literal["partial", "batch_at_end"] = "partial"
    PAYLAP_RECEIPT_SECRET: str = ""
    PAYLAP_POLICY_MAX_TASK_USD: int = 25
    PAYLAP_POLICY_DAILY_USD: int = 100
    PAYLAP_POLICY_ALLOWLIST: str = ""
    ARENA_WORKER_SOURCE: Literal["auto", "gemini", "canned"] = "canned"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("PAYLAP_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            parts = [s.strip() for s in v.split(",") if s.strip()]
            for p in parts:
                if p == "*":
                    raise ValueError("CORS origin cannot be '*' in PayLap")
            return parts
        elif isinstance(v, list):
            for p in v:
                if p == "*":
                    raise ValueError("CORS origin cannot be '*' in PayLap")
            return v
        return []

    @property
    def parsed_master_keys(self) -> Dict[str, bytes]:
        """Parse PAYLAP_MASTER_KEYS into a dict of {key_id: 32_byte_raw_bytes}."""
        result: Dict[str, bytes] = {}
        if not self.PAYLAP_MASTER_KEYS:
            return result
        entries = [e.strip() for e in self.PAYLAP_MASTER_KEYS.split(",") if e.strip()]
        for entry in entries:
            if ":" not in entry:
                raise ValueError(f"Invalid master key entry format '{entry}', expected 'id:base64'")
            kid, b64val = entry.split(":", 1)
            try:
                decoded = base64.b64decode(b64val)
            except Exception as exc:
                raise ValueError(f"Invalid base64 in master key '{kid}': {exc}") from exc
            result[kid.strip()] = decoded
        return result

    @property
    def active_master_key(self) -> Tuple[str, bytes]:
        """Returns (key_id, raw_key_bytes) of the primary (first) active master key."""
        keys = self.parsed_master_keys
        if not keys:
            raise ValueError("No master keys configured in PAYLAP_MASTER_KEYS")
        first_id = next(iter(keys.keys()))
        return first_id, keys[first_id]

    @model_validator(mode="after")
    def validate_production_guards(self) -> "Settings":
        if self.PAYLAP_ENV == "production":
            # 1. Secret key verification
            if not self.PAYLAP_SECRET_KEY or len(self.PAYLAP_SECRET_KEY.encode("utf-8")) < 32:
                raise ValueError("PAYLAP_SECRET_KEY must be configured and at least 32 bytes in production")

            # 2. Master keys verification
            keys = self.parsed_master_keys
            if not keys:
                raise ValueError("PAYLAP_MASTER_KEYS must be configured in production")
            first_id, first_bytes = self.active_master_key
            if len(first_bytes) < 32:
                raise ValueError(f"Active master key '{first_id}' must be at least 32 bytes (got {len(first_bytes)})")

            # 3. Insecure runner rejection
            if self.PAYLAP_RUNNER == "process" and not self.PAYLAP_ALLOW_INSECURE_RUNNER:
                raise ValueError("Production refuses process runner unless PAYLAP_ALLOW_INSECURE_RUNNER=true")

        return self

    @property
    def resolved_arbiter_mode(self) -> str:
        if self.PAYLAP_ARBITER_MODE == "auto":
            return "gemini" if (self.GEMINI_API_KEY and self.GEMINI_API_KEY.strip()) else "mock"
        return self.PAYLAP_ARBITER_MODE

    @property
    def resolved_arena_worker_source(self) -> str:
        if self.ARENA_WORKER_SOURCE == "auto":
            return "gemini" if (self.GEMINI_API_KEY and self.GEMINI_API_KEY.strip()) else "canned"
        return self.ARENA_WORKER_SOURCE

    @property
    def receipt_signing_info(self) -> Tuple[str, str]:
        if self.PAYLAP_RECEIPT_SECRET and self.PAYLAP_RECEIPT_SECRET.strip():
            return self.PAYLAP_RECEIPT_SECRET.strip(), "configured"
        return self.PAYLAP_SECRET_KEY, "active-secret"

    @property
    def policy_allowlist_set(self) -> Set[str]:
        if not self.PAYLAP_POLICY_ALLOWLIST:
            return set()
        return {email.strip().lower() for email in self.PAYLAP_POLICY_ALLOWLIST.split(",") if email.strip()}


settings = Settings()
