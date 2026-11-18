import base64
import os
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app.config import settings


class CryptoError(Exception):
    pass


class DecryptionError(CryptoError):
    pass


class KeyNotFoundError(CryptoError):
    pass


def get_master_key(key_id: Optional[str] = None) -> Tuple[str, bytes]:
    """Retrieve the specified master key or the active primary key."""
    keys = settings.parsed_master_keys
    if not keys:
        raise KeyNotFoundError("No master keys configured in settings.PAYLAP_MASTER_KEYS")

    if key_id is None:
        first_id = next(iter(keys.keys()))
        return first_id, keys[first_id]

    if key_id not in keys:
        raise KeyNotFoundError(f"Master key with id '{key_id}' not found")

    return key_id, keys[key_id]


def encrypt_credential(
    plaintext: str,
    org_id: str,
    environment: str,
    field: str,
    key_id: Optional[str] = None,
) -> str:
    """
    Encrypt a credential using AES-256-GCM.
    - Random 12-byte nonce
    - Associated Authenticated Data (AAD): org_id:environment:field
    - Envelope format: key_id.base64(nonce).base64(ciphertext)
    """
    kid, key_bytes = get_master_key(key_id)
    if len(key_bytes) != 32:
        raise CryptoError(f"Master key must be exactly 32 bytes for AES-256-GCM (got {len(key_bytes)})")

    nonce = os.urandom(12)  # 96-bit nonce for GCM
    aad = f"{org_id}:{environment}:{field}".encode("utf-8")

    aesgcm = AESGCM(key_bytes)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)

    b64_nonce = base64.b64encode(nonce).decode("utf-8")
    b64_ciphertext = base64.b64encode(ciphertext).decode("utf-8")

    return f"{kid}.{b64_nonce}.{b64_ciphertext}"


def decrypt_credential(
    envelope: str,
    org_id: str,
    environment: str,
    field: str,
) -> str:
    """
    Decrypt an AES-256-GCM envelope.
    Verifies AAD matches org_id:environment:field.
    Raises DecryptionError if corrupted or wrong AAD.
    """
    parts = envelope.split(".")
    if len(parts) != 3:
        raise DecryptionError("Invalid encryption envelope format. Expected key_id.nonce.ciphertext")

    kid, b64_nonce, b64_ciphertext = parts
    kid, key_bytes = get_master_key(kid)

    try:
        nonce = base64.b64decode(b64_nonce)
        ciphertext = base64.b64decode(b64_ciphertext)
    except Exception as exc:
        raise DecryptionError(f"Invalid base64 encoding in envelope: {exc}") from exc

    aad = f"{org_id}:{environment}:{field}".encode("utf-8")
    aesgcm = AESGCM(key_bytes)

    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:
        raise DecryptionError("Decryption failed: corrupted ciphertext or invalid authentication data (AAD)") from exc


def reencrypt_credential(
    envelope: str,
    org_id: str,
    environment: str,
    field: str,
    new_key_id: str,
) -> str:
    """Decrypt an existing envelope and re-encrypt with a new key ID."""
    plaintext = decrypt_credential(envelope, org_id, environment, field)
    return encrypt_credential(plaintext, org_id, environment, field, key_id=new_key_id)


def rotate_all_credentials_master_key(db: Session, target_key_id: str) -> int:
    """Rotate all stored PayPal client secrets in the DB to target_key_id."""
    from app.models import OrgPayPalCredential

    credentials = db.query(OrgPayPalCredential).all()
    count = 0
    for cred in credentials:
        cred.encrypted_client_secret = reencrypt_credential(
            cred.encrypted_client_secret,
            cred.org_id,
            cred.environment,
            "client_secret",
            new_key_id=target_key_id,
        )
        count += 1
    db.commit()
    return count
