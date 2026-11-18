import secrets


def generate_id(prefix: str, entropy_bytes: int = 16) -> str:
    """
    Generate an unguessable prefixed ID with at least 128 bits of cryptographic entropy.
    16 bytes = 128 bits of entropy -> 32 hex characters.
    Format: <prefix>_<32 hex chars>
    """
    hex_entropy = secrets.token_hex(entropy_bytes)
    return f"{prefix}_{hex_entropy}"
