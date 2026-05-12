"""Authenticated httpx client for a stored SD-WAN Manager profile (JWT or session)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from terra.models import SdWanManagerInstance
from terra.sdwan_operator_log import (
    clear_sdwan_http_log_tenant,
    log_outbound_sdwan_request,
    set_sdwan_http_log_cluster,
    set_sdwan_http_log_tenant,
)
from terra.secret_store import decrypt_json


def refresh_sdwan_dataservice_csrf_header(client: httpx.Client, base_url: str) -> bool:
    """
    Multitenant ``POST …/tenant/…/switch`` requires ``X-XSRF-TOKEN`` to match the server session.
    For **JWT** auth, that token is published on ``GET /dataservice/client/server`` (``data.CSRFToken`` or
    ``data[0].CSRFToken``). Session logins already set XSRF from ``/dataservice/client/token`` — skip refresh
    when ``Authorization`` is not a Bearer token so we do not overwrite a working session header.
    """
    auth = client.headers.get("Authorization") or ""
    if not (isinstance(auth, str) and auth.strip().lower().startswith("bearer")):
        return False
    base = base_url.rstrip("/")
    r = client.get(f"{base}/dataservice/client/server", headers={"Accept": "application/json"})
    if r.status_code >= 400:
        return False
    try:
        body = r.json()
    except ValueError:
        return False
    data = body.get("data") if isinstance(body, dict) else None
    tok: str | None = None
    if isinstance(data, dict):
        raw = data.get("CSRFToken")
        if isinstance(raw, str) and raw.strip():
            tok = raw.strip()
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        raw = data[0].get("CSRFToken")
        if isinstance(raw, str) and raw.strip():
            tok = raw.strip()
    if not tok:
        return False
    client.headers["X-XSRF-TOKEN"] = tok
    return True


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
def open_manager_http_client(
    secret_key: str,
    instance: SdWanManagerInstance,
    *,
    log_tenant: str | None = None,
) -> Iterator[httpx.Client]:
    """Yield a short-lived client authenticated to the given Manager instance."""
    payload = decrypt_json(secret_key, instance.credentials_encrypted)
    base = instance.base_url.rstrip("/")
    verify_tls = instance.verify_tls
    mode = str(payload.get("mode", "")).lower().strip()
    set_sdwan_http_log_cluster(instance.display_name)
    set_sdwan_http_log_tenant(log_tenant or "")
    hooks = {"request": [log_outbound_sdwan_request]}
    try:
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
                timeout=600.0,
                verify=verify_tls,
                follow_redirects=True,
                headers=headers,
                event_hooks=hooks,
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
            client = httpx.Client(
                timeout=600.0,
                verify=verify_tls,
                follow_redirects=True,
                event_hooks=hooks,
            )
            try:
                _session_login(client, base, user, pwd)
                yield client
            finally:
                client.close()
            return

        msg = f"Unknown credential mode: {mode!r}"
        raise ValueError(msg)
    finally:
        clear_sdwan_http_log_tenant()
        set_sdwan_http_log_cluster("")
