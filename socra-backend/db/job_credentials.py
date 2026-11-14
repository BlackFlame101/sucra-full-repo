"""Encrypt provider credentials for durable, server-only jobs."""
from __future__ import annotations

import os
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_job_key(value: str, resource_id: str) -> str | None:
    if not value.strip():
        return None
    try:
        secret = b64decode(os.environ.get("SOCRA_JOB_ENCRYPTION_KEY", ""), validate=True)
        if len(secret) != 32:
            raise ValueError
        nonce = os.urandom(12)
        ciphertext = AESGCM(secret).encrypt(nonce, value.strip().encode(), resource_id.encode())
        return ".".join(b64encode(part).decode() for part in (nonce, ciphertext))
    except (ValueError, TypeError):
        raise ValueError("Custom exam API keys require the server's job encryption key.") from None


def decrypt_key(encrypted: str | None, resource_id: str) -> str | None:
    if not encrypted:
        return None
    secret = os.environ.get("SOCRA_JOB_ENCRYPTION_KEY", "")
    try:
        nonce, ciphertext = encrypted.split(".", 1)
        return AESGCM(b64decode(secret, validate=True)).decrypt(
            b64decode(nonce, validate=True), b64decode(ciphertext, validate=True), resource_id.encode(),
        ).decode()
    except Exception:
        raise ValueError("The saved API key could not be read. Check Settings and retry.") from None
