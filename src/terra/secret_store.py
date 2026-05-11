"""Encrypt small JSON blobs (SD-WAN credentials) at rest using the app secret key."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet


def _fernet(secret_key: str) -> Fernet:
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_json(secret_key: str, payload: dict[str, Any]) -> str:
    """Serialize JSON and return a url-safe ASCII ciphertext string."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _fernet(secret_key).encrypt(raw).decode("ascii")


def decrypt_json(secret_key: str, blob: str) -> dict[str, Any]:
    raw = _fernet(secret_key).decrypt(blob.encode("ascii"))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        msg = "Invalid credential payload"
        raise ValueError(msg)
    return data
