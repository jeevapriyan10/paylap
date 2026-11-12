import os
import secrets
from typing import Literal, Set
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ephemeral secret for demo mode when PAYLAP_RECEIPT_SECRET is omitted
_EPHEMERAL_DEV_SECRET = secrets.token_hex(32)


class Settings(BaseSettings):
    PAYLAP_MODE: Literal["demo", "live"] = "demo"
    PAYLAP_PAYOUT_MODE: Literal["live", "simulated"] = "live"
    PAYLAP_PUBLIC_URL: str = "http://localhost:8000"
    PAYLAP_DB_URL: str = "sqlite:///./paylap.db"

    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_CLIENT_SECRET: str = ""
    PAYPAL_BASE_URL: str = "https://api-m.sandbox.paypal.com"
    PAYPAL_WORKER_EMAIL: str = ""

    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Stage 2 Settings
    PAYLAP_ARBITER_MODE: Literal["auto", "gemini", "mock", "off"] = "auto"
    PAYLAP_ARBITER_FAIL: Literal["closed"] = "closed"
    PAYLAP_CAPTURE_STRATEGY: Literal["partial", "batch_at_end"] = "partial"
    PAYLAP_RECEIPT_SECRET: str = ""
    PAYLAP_POLICY_MAX_TASK_USD: int = 50
    PAYLAP_POLICY_DAILY_USD: int = 200
    PAYLAP_POLICY_ALLOWLIST: str = ""
    ARENA_WORKER_SOURCE: Literal["auto", "gemini", "canned"] = "auto"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_live_settings(self) -> "Settings":
        if self.PAYLAP_MODE == "live":
            missing = []
            if not self.PAYPAL_CLIENT_ID or not self.PAYPAL_CLIENT_ID.strip():
                missing.append("PAYPAL_CLIENT_ID")
            if not self.PAYPAL_CLIENT_SECRET or not self.PAYPAL_CLIENT_SECRET.strip():
                missing.append("PAYPAL_CLIENT_SECRET")
            if not self.PAYLAP_RECEIPT_SECRET or not self.PAYLAP_RECEIPT_SECRET.strip():
                missing.append("PAYLAP_RECEIPT_SECRET")
            if missing:
                raise ValueError(
                    f"PAYLAP_MODE is set to 'live' but required settings are missing: {', '.join(missing)}. "
                    f"Please provide them in the environment or set PAYLAP_MODE=demo."
                )
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
    def receipt_signing_info(self) -> tuple[str, str]:
        """Returns (signing_secret, signing_key_id)."""
        if self.PAYLAP_RECEIPT_SECRET and self.PAYLAP_RECEIPT_SECRET.strip():
            return self.PAYLAP_RECEIPT_SECRET.strip(), "configured"
        return _EPHEMERAL_DEV_SECRET, "dev-ephemeral"

    @property
    def policy_allowlist_set(self) -> Set[str]:
        if not self.PAYLAP_POLICY_ALLOWLIST:
            return set()
        return {
            email.strip().lower()
            for email in self.PAYLAP_POLICY_ALLOWLIST.split(",")
            if email.strip()
        }


settings = Settings()
