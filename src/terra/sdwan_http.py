"""Authenticated httpx client for a stored SD-WAN Manager profile (JWT or session)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from terra.models import SdWanManagerInstance
from terra.secret_store import decrypt_json


def _session_login(client: httpx.Client, base: str, username: str, password: str) -> None:
    """Perform j_security_check and attach XSRF default header for subsequent requests."""
    login = client.post(
        f"{base}/j_security_check",
        data={"j_username": username.strip(), "j_password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if login.status_code >= 400:
        msg = f"SD-WAN session login failed (HTTP {login.status_code})"
        raise RuntimeError(msg)
    tok = client.get(f"{base}/dataservice/client/token", headers={"Accept": "application/json"})
    xsrf: str | None = tok.headers.get("X-XSRF-TOKEN") or tok.headers.get("x-xsrf-token")
    if xsrf is None and tok.headers.get("content-type", "").startswith("application/json"):
        try:
            tj = tok.json()
            if isinstance(tj, dict):
                raw = tj.get("token") or tj.get("xsrf_token") or tj.get("xsrfToken")
                if isinstance(raw, str):
                    xsrf = raw.strip() or None
        except (ValueError, TypeError):
            xsrf = None
    if xsrf:
        client.headers["X-XSRF-TOKEN"] = xsrf
    client.headers.setdefault("Accept", "application/json")


@contextmanager
def open_manager_http_client(secret_key: str, instance: SdWanManagerInstance) -> Iterator[httpx.Client]:
    """Yield a short-lived client authenticated to the given Manager instance."""
    payload = decrypt_json(secret_key, instance.credentials_encrypted)
    base = instance.base_url.rstrip("/")
    verify_tls = instance.verify_tls
    mode = str(payload.get("mode", "")).lower().strip()

    if mode == "jwt":
        token = str(payload.get("token", "")).strip()
        if not token:
            msg = "Missing JWT in stored credentials"
            raise ValueError(msg)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        client = httpx.Client(
            timeout=120.0,
            verify=verify_tls,
            follow_redirects=True,
            headers=headers,
        )
        try:
            yield client
        finally:
            client.close()
        return

    if mode == "session":
        user = str(payload.get("username", "")).strip()
        pwd = str(payload.get("password", ""))
        if not user or not pwd:
            msg = "Incomplete session credentials"
            raise ValueError(msg)
        client = httpx.Client(timeout=120.0, verify=verify_tls, follow_redirects=True)
        try:
            _session_login(client, base, user, pwd)
            yield client
        finally:
            client.close()
        return

    msg = f"Unknown credential mode: {mode!r}"
    raise ValueError(msg)
