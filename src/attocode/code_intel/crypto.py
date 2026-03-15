"""Encryption utilities for credential storage using Fernet."""

from __future__ import annotations

import base64
import hashlib


def _get_fernet():
    """Get Fernet instance using SECRET_KEY from config."""
    from cryptography.fernet import Fernet

    from attocode.code_intel.api.deps import get_config

    config = get_config()
    key = hashlib.sha256(config.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_credential(plaintext: str) -> bytes:
    """Encrypt a credential value for storage."""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_credential(encrypted: bytes) -> str:
    """Decrypt a stored credential value."""
    return _get_fernet().decrypt(encrypted).decode()
