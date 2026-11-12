import os
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_live_credentials(self) -> "Settings":
        if self.PAYLAP_MODE == "live":
            missing = []
            if not self.PAYPAL_CLIENT_ID or not self.PAYPAL_CLIENT_ID.strip():
                missing.append("PAYPAL_CLIENT_ID")
            if not self.PAYPAL_CLIENT_SECRET or not self.PAYPAL_CLIENT_SECRET.strip():
                missing.append("PAYPAL_CLIENT_SECRET")
            if missing:
                raise ValueError(
                    f"PAYLAP_MODE is set to 'live' but required PayPal credentials are missing: {', '.join(missing)}. "
                    f"Please provide them in the environment or set PAYLAP_MODE=demo."
                )
        return self


settings = Settings()
