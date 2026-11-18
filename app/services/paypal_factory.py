from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Organization, OrgPayPalCredential
from app.services.crypto import decrypt_credential
from app.services.paypal_base import PayPalBase, PayPalError
from app.services.paypal_client import PayPalClient
from app.services.paypal_fake import FakePayPal

# Hardcoded, non-user-configurable PayPal base URLs
PAYPAL_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
PAYPAL_LIVE_BASE_URL = "https://api-m.paypal.com"


class LiveEnvironmentDisabledError(PayPalError):
    pass


def get_provider(org: Organization, environment: str, db: Session) -> PayPalBase:
    """
    Provider factory returning the appropriate PayPal client for the given environment.
    Environments:
      - simulated: labeled dry-run provider (simulated=True on all outputs)
      - sandbox: live sandbox API client using org BYO credentials
      - live: live production API client using org BYO credentials, strictly requiring:
              1. PAYLAP_ALLOW_LIVE=true
              2. org.live_enabled=true
              3. PAYLAP_RUNNER=remote
    """
    if environment == "simulated":
        return FakePayPal()

    if environment == "sandbox":
        stmt = select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == org.id,
            OrgPayPalCredential.environment == "sandbox",
        )
        cred = db.scalar(stmt)
        if not cred:
            raise PayPalError(f"No PayPal credentials configured for organization '{org.id}' in environment 'sandbox'")

        secret = decrypt_credential(
            cred.encrypted_client_secret,
            org_id=org.id,
            environment="sandbox",
            field="client_secret",
        )
        return PayPalClient(
            client_id=cred.client_id,
            client_secret=secret,
            base_url=PAYPAL_SANDBOX_BASE_URL,
        )

    if environment == "live":
        # Strict security gates for live environment
        if not settings.PAYLAP_ALLOW_LIVE:
            raise LiveEnvironmentDisabledError("Live PayPal environment is globally disabled (PAYLAP_ALLOW_LIVE=false)")
        if not org.live_enabled:
            raise LiveEnvironmentDisabledError(
                f"Organization '{org.id}' has not enabled live transactions (live_enabled=false)"
            )
        if settings.PAYLAP_RUNNER != "remote":
            raise LiveEnvironmentDisabledError(
                "Live PayPal transactions strictly require an isolated remote code runner (PAYLAP_RUNNER=remote)"
            )

        stmt = select(OrgPayPalCredential).where(
            OrgPayPalCredential.org_id == org.id,
            OrgPayPalCredential.environment == "live",
        )
        cred = db.scalar(stmt)
        if not cred:
            raise PayPalError(f"No PayPal credentials configured for organization '{org.id}' in environment 'live'")

        secret = decrypt_credential(
            cred.encrypted_client_secret,
            org_id=org.id,
            environment="live",
            field="client_secret",
        )
        return PayPalClient(
            client_id=cred.client_id,
            client_secret=secret,
            base_url=PAYPAL_LIVE_BASE_URL,
        )

    raise PayPalError(f"Unknown environment: '{environment}'. Expected 'simulated', 'sandbox', or 'live'.")
