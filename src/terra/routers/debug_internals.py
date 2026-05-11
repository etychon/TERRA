"""Opt-in diagnostic HTTP API (lab / Compose debug profile only — never enable on the public Internet)."""

from __future__ import annotations

import platform
import sys
from typing import Annotated, Any
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from terra.config import Settings, get_settings
from terra.db import get_db
from terra.models import SdWanManagerInstance, SyncedDevice, User

router = APIRouter(prefix="/debug", tags=["debug"])


def _effective_settings(request: Request) -> Settings:
    raw = getattr(request.app.state, "terra_settings", None)
    if isinstance(raw, Settings):
        return raw
    return get_settings()


def _redact_database_url(url: str) -> str:
    """Mask user:password in netloc; leave sqlite file paths readable."""
    try:
        p = urlparse(url)
    except ValueError:
        return "<unparseable>"
    if p.scheme.startswith("sqlite"):
        return urlunparse((p.scheme, "", p.path, "", "", ""))
    if not p.netloc:
        return urlunparse((p.scheme, "", p.path, "", "", ""))
    host = p.netloc
    if "@" in host:
        _, rest = host.split("@", 1)
        host = f"***:***@{rest}"
    return urlunparse((p.scheme, host, p.path, "", "", ""))


def require_debug_token(request: Request) -> None:
    s = _effective_settings(request)
    expected = (s.debug_token or "").strip()
    if not s.debug_expose_internals or not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    got = (
        request.headers.get("x-terra-debug-token")
        or request.headers.get("X-Terra-Debug-Token")
        or request.query_params.get("debug_token")
        or ""
    ).strip()
    if got != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing debug token")


@router.get("/summary")
def debug_summary(
    request: Request,
    _auth: Annotated[None, Depends(require_debug_token)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Non-secret runtime snapshot for local diagnostics (Compose debug profile)."""
    s = _effective_settings(request)
    n_users = db.scalar(select(func.count()).select_from(User)) or 0
    n_managers = db.scalar(select(func.count()).select_from(SdWanManagerInstance)) or 0
    n_devices = db.scalar(select(func.count()).select_from(SyncedDevice)) or 0
    return {
        "terra": {
            "database_url_redacted": _redact_database_url(s.database_url),
            "mail_mode": s.mail_mode,
            "session_cookie_secure": s.session_cookie_secure,
            "sdwan_background_sync": s.sdwan_background_sync,
            "sdwan_sync_interval_seconds": s.sdwan_sync_interval_seconds,
            "sdwan_sync_startup_delay_seconds": s.sdwan_sync_startup_delay_seconds,
            "admin_email": s.admin_email,
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "counts": {
            "users": int(n_users),
            "sdwan_manager_instances": int(n_managers),
            "synced_devices": int(n_devices),
        },
    }


@router.get("/sdwan-managers")
def debug_sdwan_managers(
    _auth: Annotated[None, Depends(require_debug_token)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manager rows without credentials (URLs and status only)."""
    rows = db.scalars(select(SdWanManagerInstance).order_by(SdWanManagerInstance.id.asc())).all()
    return {
        "managers": [
            {
                "id": m.id,
                "user_id": m.user_id,
                "display_name": m.display_name,
                "base_url": m.base_url,
                "auth_mode": m.auth_mode,
                "verify_tls": m.verify_tls,
                "link_status": m.link_status,
                "manager_version": m.manager_version,
                "token_expires_at": m.token_expires_at.isoformat() if m.token_expires_at else None,
                "last_http_status": m.last_http_status,
                "last_error": m.last_error,
                "last_verified_at": m.last_verified_at.isoformat() if m.last_verified_at else None,
                "devices_last_sync_at_utc": m.devices_last_sync_at_utc.isoformat()
                if m.devices_last_sync_at_utc
                else None,
            }
            for m in rows
        ]
    }


@router.get("/devices-sample")
def debug_devices_sample(
    _auth: Annotated[None, Depends(require_debug_token)],
    db: Session = Depends(get_db),
    limit: int = 50,
) -> dict[str, Any]:
    """First N synced devices joined to manager display name (no raw JSON)."""
    lim = max(1, min(limit, 500))
    q = (
        select(SyncedDevice, SdWanManagerInstance.display_name)
        .join(SdWanManagerInstance, SyncedDevice.sdwan_instance_id == SdWanManagerInstance.id)
        .order_by(SyncedDevice.id.asc())
        .limit(lim)
    )
    out: list[dict[str, Any]] = []
    for d, mgr_name in db.execute(q).all():
        out.append(
            {
                "id": d.id,
                "manager": mgr_name,
                "source_device_uuid": d.source_device_uuid,
                "hostname": d.hostname,
                "serial_number": d.serial_number,
                "reachability": d.reachability,
                "synced_at_utc": d.synced_at_utc.isoformat(),
            }
        )
    return {"limit": lim, "devices": out}


@router.get("/sqlite-meta")
def debug_sqlite_meta(
    request: Request,
    _auth: Annotated[None, Depends(require_debug_token)],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Table names and row estimates when using SQLite (empty when not SQLite)."""
    s = _effective_settings(request)
    if not s.database_url.strip().lower().startswith("sqlite"):
        return {"backend": "non-sqlite", "detail": "sqlite-meta only applies to SQLite URLs"}
    tables = [
        {"name": r[0], "type": r[1]}
        for r in db.execute(
            text("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        ).all()
    ]
    counts: dict[str, int] = {}
    for t in tables:
        if t["type"] != "table":
            continue
        name = t["name"]
        if name.startswith("sqlite_"):
            continue
        if not name.replace("_", "").isalnum():
            continue
        q = text(f'SELECT COUNT(*) AS c FROM "{name}"')
        counts[name] = int(db.execute(q).scalar_one())
    return {"backend": "sqlite", "tables": tables, "row_counts": counts}


def attach_debug_routes(app_settings: Settings, app: FastAPI) -> None:
    """Register debug router when flag and token are both set (called from create_app)."""
    if not app_settings.debug_expose_internals:
        return
    token = (app_settings.debug_token or "").strip()
    if not token:
        return
    app.include_router(router)
