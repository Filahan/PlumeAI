"""AES-GCM encryption — binary-compatible with the existing Node.js Web Crypto ciphertexts.

The Node.js code stores `iv` (12 bytes) and `ct` (ciphertext + 16-byte auth tag appended)
as base64 strings. Python's `cryptography` AESGCM produces the same format, so we can
decrypt every secret that was written by the previous Node-based backend with no rewrite.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


@lru_cache(maxsize=1)
def _key() -> AESGCM:
    raw = base64.b64decode(get_settings().encryption_key_b64)
    if len(raw) != 32:
        raise RuntimeError(f"ENCRYPTION_KEY must decode to exactly 32 bytes (got {len(raw)}).")
    return AESGCM(raw)


def encrypt(plaintext: str) -> dict[str, str]:
    """Encrypt `plaintext` and return `{iv, ct}` (base64-encoded strings)."""
    aesgcm = _key()
    iv = base64_random_bytes(12)
    iv_bytes = base64.b64decode(iv)
    ct_bytes = aesgcm.encrypt(iv_bytes, plaintext.encode("utf-8"), None)
    return {"iv": iv, "ct": base64.b64encode(ct_bytes).decode("ascii")}


def decrypt(iv: str, ct: str) -> str:
    """Decrypt a `{iv, ct}` pair produced by either Node Web Crypto or our `encrypt()`."""
    aesgcm = _key()
    plain = aesgcm.decrypt(base64.b64decode(iv), base64.b64decode(ct), None)
    return plain.decode("utf-8")


def base64_random_bytes(n: int) -> str:
    import os

    return base64.b64encode(os.urandom(n)).decode("ascii")
