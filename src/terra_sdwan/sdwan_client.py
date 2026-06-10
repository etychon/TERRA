"""Probe Cisco Catalyst SD-WAN Manager (vManage) — JWT (preferred) or session login."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from terra.secret_store import decrypt_json
from terra_sdwan.sdwan_dataservice_rows import rows_from_dataservice_body

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    message: str
    http_status: int | None
    manager_version: str | None = None
    expires_at: datetime | None = None


def normalize_manager_base_url(raw: str) -> str:
    """Return https://host with no trailing slash (path on URL is dropped; host only)."""
    s = raw.strip()
    if not s:
        msg = "Manager URL is required"
        raise ValueError(msg)
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parsed = urlparse(s)
    if not parsed.netloc:
        msg = "Invalid manager URL"
        raise ValueError(msg)
    if parsed.scheme not in ("http", "https"):
        msg = "URL must use http or https"
        raise ValueError(msg)
    scheme = parsed.scheme
    return f"{scheme}://{parsed.netloc}".rstrip("/")


def jwt_expires_at(token: str) -> datetime | None:
    """Best-effort JWT `exp` without verifying the signature (display / UX only)."""
    parts = token.strip().split(".")
    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    pad = "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
    except (json.JSONDecodeError, binascii.Error, ValueError):
        return None
    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        ts = int(exp)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


_VERSION_KEYS: tuple[str, ...] = (
    "version",
    "serverVersion",
    "softwareVersion",
    "platformVersion",
    "mnemonic",
    "vmanageVersion",
    "vmanagedVersion",
    "vmanage_version",
    "buildVersion",
    "compositeVersion",
    "productVersion",
    "imageVersion",
    "defaultVersion",
    "versionStr",
    "applicationVersion",
    "managementSystemVersion",
    "softwareDisplayVersion",
    "runningVersion",
)


def _parse_server_payload(data: Any) -> tuple[str | None, str | None]:
    """Extract version / identity hints from /dataservice/client/server style JSON."""
    if not isinstance(data, dict):
        return None, None
    version = None
    for key in _VERSION_KEYS:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            version = val.strip()
            break
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            s = str(val).strip()
            if s:
                version = s
                break
    system_ip = None
    sip = data.get("system-ip") or data.get("system_ip")
    if isinstance(sip, str) and sip.strip():
        system_ip = sip.strip()
    return version, system_ip


def _manager_version_from_server_json(body: Any) -> str | None:
    """Best-effort Manager software version from /dataservice/client/server (or similar) JSON."""
    candidates: list[dict[str, Any]] = []

    if isinstance(body, list):
        for el in body:
            if isinstance(el, dict):
                candidates.append(el)
    elif isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            for el in data:
                if isinstance(el, dict):
                    candidates.append(el)
            if not data:
                candidates.append(body)
        elif isinstance(data, dict):
            # Multitenant / newer builds: ``data`` is a single object (version fields live here, not on the root).
            candidates.append(data)
            candidates.append(body)
        else:
            candidates.append(body)
        for nest_key in ("server", "vmanage", "about", "info", "organization"):
            nest = body.get(nest_key)
            if isinstance(nest, dict):
                candidates.append(nest)
        for row in rows_from_dataservice_body(body):
            candidates.append(row)

    seen: set[int] = set()
    unique: list[dict[str, Any]] = []
    for d in candidates:
        i = id(d)
        if i in seen:
            continue
        seen.add(i)
        unique.append(d)

    for d in unique:
        ver, _ = _parse_server_payload(d)
        if ver:
            return ver
    for d in unique:
        for k, v in d.items():
            if not isinstance(k, str) or "version" not in k.lower():
                continue
            if isinstance(v, str) and v.strip() and v.strip().lower() not in ("none", "n/a", "na", ""):
                return v.strip()
    return None


def read_manager_version(
    client: httpx.Client, base_url: str, *, request_timeout: float | None = None
) -> str | None:
    """GET /dataservice/client/server using an already-authenticated client; return Manager version if present."""
    base = base_url.rstrip("/")
    req_kw: dict[str, Any] = {"headers": {"Accept": "application/json"}}
    if request_timeout is not None:
        req_kw["timeout"] = request_timeout
    try:
        r = client.get(f"{base}/dataservice/client/server", **req_kw)
    except httpx.RequestError:
        return None
    if r.status_code >= 400:
        return None
    try:
        v = _manager_version_from_server_json(r.json())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return (v[:128] if v else None)


def probe_jwt(base_url: str, token: str, *, verify_tls: bool) -> ProbeResult:
    """Call a lightweight authenticated endpoint using Bearer JWT."""
    base = base_url.rstrip("/")
    url = f"{base}/dataservice/client/server"
    headers = {"Authorization": f"Bearer {token.strip()}", "Accept": "application/json"}
    exp = jwt_expires_at(token)
    try:
        with httpx.Client(timeout=25.0, verify=verify_tls, follow_redirects=True) as client:
            r = client.get(url, headers=headers)
    except httpx.RequestError as e:
        logger.info("SD-WAN JWT probe transport error: %s", e)
        return ProbeResult(False, f"Network error: {e!s}", None, expires_at=exp)

    if r.status_code == 401:
        return ProbeResult(False, "JWT rejected (401). Regenerate the API token in Manager.", 401, expires_at=exp)
    if r.status_code == 403:
        return ProbeResult(False, "JWT forbidden (403). Token may lack API scope.", 403, expires_at=exp)
    if r.status_code >= 400:
        return ProbeResult(False, f"Manager returned HTTP {r.status_code}.", r.status_code, expires_at=exp)

    version: str | None = None
    try:
        body = r.json()
        version = _manager_version_from_server_json(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        version = None

    return ProbeResult(True, "Connected with JWT.", r.status_code, manager_version=version, expires_at=exp)


def probe_session(base_url: str, username: str, password: str, *, verify_tls: bool) -> ProbeResult:
    """Establish a session via j_security_check and call /dataservice/client/server."""
    base = base_url.rstrip("/")
    headers_json = {"Accept": "application/json"}
    try:
        with httpx.Client(timeout=25.0, verify=verify_tls, follow_redirects=True) as client:
            login = client.post(
                f"{base}/j_security_check",
                data={"j_username": username.strip(), "j_password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if login.status_code >= 400:
                return ProbeResult(
                    False,
                    f"Login POST failed (HTTP {login.status_code}).",
                    login.status_code,
                )
            tok = client.get(f"{base}/dataservice/client/token", headers=headers_json)
            xsrf: str | None = tok.headers.get("X-XSRF-TOKEN") or tok.headers.get("x-xsrf-token")
            if xsrf is None and tok.headers.get("content-type", "").startswith("application/json"):
                try:
                    tj = tok.json()
                    if isinstance(tj, dict):
                        xsrf = tj.get("token") or tj.get("xsrf_token") or tj.get("xsrfToken")
                        if isinstance(xsrf, str):
                            xsrf = xsrf.strip() or None
                except (json.JSONDecodeError, TypeError, ValueError):
                    xsrf = None
            req_headers = {**headers_json}
            if xsrf:
                req_headers["X-XSRF-TOKEN"] = xsrf
            srv = client.get(f"{base}/dataservice/client/server", headers=req_headers)
    except httpx.RequestError as e:
        logger.info("SD-WAN session probe transport error: %s", e)
        return ProbeResult(False, f"Network error: {e!s}", None)

    if srv.status_code == 401:
        return ProbeResult(False, "Session not authorized (401). Check username and password.", 401)
    if srv.status_code >= 400:
        return ProbeResult(False, f"Manager returned HTTP {srv.status_code} after login.", srv.status_code)

    version: str | None = None
    try:
        body = srv.json()
        version = _manager_version_from_server_json(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        version = None

    return ProbeResult(
        True,
        "Connected with username/password session.",
        srv.status_code,
        manager_version=version,
        expires_at=None,
    )


def probe_from_credentials(
    secret_key: str,
    *,
    base_url: str,
    auth_mode: str,
    credentials_encrypted: str,
    verify_tls: bool,
) -> ProbeResult:
    """Decrypt stored credentials and probe the manager."""
    try:
        payload = decrypt_json(secret_key, credentials_encrypted)
    except Exception:
        return ProbeResult(False, "Could not decrypt stored credentials (wrong TERRA_SECRET_KEY?).", None)

    mode = str(payload.get("mode", "")).lower().strip()
    if mode != auth_mode.strip().lower():
        return ProbeResult(False, "Stored credential type does not match this profile.", None)
    if mode == "jwt":
        token = str(payload.get("token", "")).strip()
        if not token:
            return ProbeResult(False, "Stored JWT is empty.", None)
        return probe_jwt(base_url, token, verify_tls=verify_tls)
    if mode == "session":
        user = str(payload.get("username", "")).strip()
        pwd = str(payload.get("password", ""))
        if not user or not pwd:
            return ProbeResult(False, "Stored session username/password incomplete.", None)
        return probe_session(base_url, user, pwd, verify_tls=verify_tls)
    return ProbeResult(False, f"Unknown auth mode in storage: {mode!r}.", None)
