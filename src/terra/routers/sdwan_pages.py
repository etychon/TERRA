"""Administration: Catalyst SD-WAN Manager (vManage) connections per user."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.crud import user_to_public
from terra.crud_sdwan import (
    count_synced_devices_for_manager,
    delete_sdwan_manager,
    edge_inventory_labels_for_manager,
    get_sdwan_manager,
    list_sdwan_managers,
)
from terra.db import get_db
from terra.deps import ensure_csrf, get_current_user, require_csrf, user_is_admin
from terra.inventory_extract import utc_iso_for_json
from terra.models import SdWanAuthMode, SdWanLinkStatus, SdWanManagerInstance, User
from terra.secret_store import decrypt_json, encrypt_json
from terra_sdwan.sdwan_client import (
    ProbeResult,
    jwt_expires_at,
    normalize_manager_base_url,
    probe_from_credentials,
    probe_jwt,
    probe_session,
)
from terra_sdwan.sdwan_credential_scope import credential_scope_public_label, detect_credential_scope
from terra_sdwan.sdwan_http import open_manager_http_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/administration", tags=["administration"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _apply_probe(inst: SdWanManagerInstance, result: ProbeResult, *, auth_mode: str, secret_key: str) -> None:
    now = datetime.now(tz=UTC)
    inst.updated_at = now
    inst.last_verified_at = now
    inst.last_http_status = result.http_status
    inst.last_error = None if result.ok else (result.message[:1000] if result.message else None)
    if result.ok:
        inst.link_status = SdWanLinkStatus.connected.value
        inst.manager_version = result.manager_version
        if auth_mode == SdWanAuthMode.jwt.value:
            inst.token_expires_at = result.expires_at or jwt_expires_at(
                _jwt_from_encrypted(secret_key, inst.credentials_encrypted) or ""
            )
        else:
            inst.token_expires_at = None
    else:
        inst.credential_scope = None
        inst.credential_scope_detail = None
        inst.manager_version = None
        if auth_mode == SdWanAuthMode.jwt.value:
            inst.token_expires_at = jwt_expires_at(
                _jwt_from_encrypted(secret_key, inst.credentials_encrypted) or ""
            )
        else:
            inst.token_expires_at = None
        if result.http_status in (401, 403):
            inst.link_status = SdWanLinkStatus.auth_failed.value
        else:
            inst.link_status = SdWanLinkStatus.unreachable.value


def _detect_and_store_credential_scope(secret_key: str, inst: SdWanManagerInstance) -> None:
    """Best-effort multitenant vs single-tenant classification (does not change link_status)."""
    try:
        with open_manager_http_client(secret_key, inst) as client:
            det = detect_credential_scope(client, inst.base_url)
        inst.credential_scope = det.code
        d = det.detail.strip()
        inst.credential_scope_detail = d[:512] if d else None
    except Exception as exc:
        logger.warning("SD-WAN credential scope detection failed for instance %s: %s", inst.id, exc)
        inst.credential_scope = "unknown"
        inst.credential_scope_detail = str(exc)[:512]


def _jwt_from_encrypted(secret_key: str, blob: str) -> str | None:
    try:
        data = decrypt_json(secret_key, blob)
    except Exception:
        return None
    if str(data.get("mode")) != SdWanAuthMode.jwt.value:
        return None
    t = str(data.get("token", "")).strip()
    return t or None


def _rows_for_template(db: Session, rows: list[SdWanManagerInstance]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in rows:
        edge_total, edge_labels = edge_inventory_labels_for_manager(db, m.id)
        synced_total = count_synced_devices_for_manager(db, m.id)
        out.append(
            {
                "id": m.id,
                "display_name": m.display_name,
                "base_url": m.base_url,
                "auth_mode": m.auth_mode,
                "verify_tls": m.verify_tls,
                "link_status": m.link_status,
                "token_expires_at": m.token_expires_at,
                "manager_version": m.manager_version,
                "last_http_status": m.last_http_status,
                "last_error": m.last_error,
                "last_verified_at": m.last_verified_at,
                "devices_last_sync_at_utc_iso": (
                    utc_iso_for_json(m.devices_last_sync_at_utc) if m.devices_last_sync_at_utc else None
                ),
                "edge_device_count": edge_total,
                "synced_device_total": synced_total,
                "edge_device_labels": edge_labels,
                "credential_scope_label": credential_scope_public_label(m.credential_scope),
                "credential_scope_detail": m.credential_scope_detail or "",
            }
        )
    return out


@router.get("/sd-wan", response_class=HTMLResponse)
def sdwan_administration_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    rows = list_sdwan_managers(db, user.id)
    return templates.TemplateResponse(
        request,
        "sdwan_managers.html",
        {
            "title": "Administration — SD-WAN Manager — TERRA",
            "user": user_to_public(user),
            "is_admin": user_is_admin(user),
            "show_app_shell": True,
            "nav_is_admin": user_is_admin(user),
            "nav_active": "sdwan",
            "csrf_token": ensure_csrf(request),
            "instances": _rows_for_template(db, rows),
            "form_error": None,
        },
    )


@router.post("/sd-wan/add", response_model=None)
def sdwan_add_instance(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    csrf_token: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    base_url: Annotated[str, Form()],
    auth_mode: Annotated[str, Form()] = SdWanAuthMode.jwt.value,
    jwt_token: Annotated[str, Form()] = "",
    sdwan_username: Annotated[str, Form()] = "",
    sdwan_password: Annotated[str, Form()] = "",
    verify_tls: Annotated[str | None, Form()] = None,
) -> RedirectResponse | HTMLResponse:
    require_csrf(request, csrf_token)
    settings = get_settings()
    verify_tls_on = verify_tls == "on"

    name = display_name.strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid display name.")
    mode = auth_mode.strip().lower()
    if mode not in (SdWanAuthMode.jwt.value, SdWanAuthMode.session.value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid auth mode.")

    try:
        norm_url = normalize_manager_base_url(base_url)
    except ValueError as e:
        return _form_error_response(request, db, user, str(e))

    if mode == SdWanAuthMode.jwt.value:
        tok = jwt_token.strip()
        if not tok:
            return _form_error_response(
                request,
                db,
                user,
                "Paste the API JWT from SD-WAN Manager (Admin → My Profile).",
            )
        payload = {"mode": SdWanAuthMode.jwt.value, "token": tok}
    else:
        u = sdwan_username.strip()
        p = sdwan_password
        if not u or not p:
            return _form_error_response(
                request,
                db,
                user,
                "Username and password are required for session authentication.",
            )
        payload = {"mode": SdWanAuthMode.session.value, "username": u, "password": p}

    try:
        blob = encrypt_json(settings.secret_key, payload)
    except Exception:
        return _form_error_response(request, db, user, "Could not encrypt credentials.")

    inst = SdWanManagerInstance(
        user_id=user.id,
        display_name=name,
        base_url=norm_url,
        auth_mode=mode,
        credentials_encrypted=blob,
        verify_tls=verify_tls_on,
        link_status=SdWanLinkStatus.unknown.value,
        token_expires_at=jwt_expires_at(jwt_token) if mode == SdWanAuthMode.jwt.value else None,
    )
    db.add(inst)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _form_error_response(request, db, user, "You already have a manager with this display name.")

    if mode == SdWanAuthMode.jwt.value:
        result = probe_jwt(norm_url, jwt_token.strip(), verify_tls=verify_tls_on)
    else:
        result = probe_session(norm_url, sdwan_username.strip(), sdwan_password, verify_tls=verify_tls_on)

    _apply_probe(inst, result, auth_mode=mode, secret_key=settings.secret_key)
    if result.ok:
        _detect_and_store_credential_scope(settings.secret_key, inst)
    db.add(inst)
    db.commit()

    if not result.ok:
        return RedirectResponse(
            url="/administration/sd-wan?added=1&probe=warn",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url="/administration/sd-wan?added=1", status_code=status.HTTP_303_SEE_OTHER)


def _form_error_response(request: Request, db: Session, user: User, message: str) -> HTMLResponse:
    rows = list_sdwan_managers(db, user.id)
    return templates.TemplateResponse(
        request,
        "sdwan_managers.html",
        {
            "title": "Administration — SD-WAN Manager — TERRA",
            "user": user_to_public(user),
            "is_admin": user_is_admin(user),
            "show_app_shell": True,
            "nav_is_admin": user_is_admin(user),
            "nav_active": "sdwan",
            "csrf_token": ensure_csrf(request),
            "instances": _rows_for_template(db, rows),
            "form_error": message,
        },
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/sd-wan/{instance_id}/verify", response_model=None)
def sdwan_verify_instance(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    instance_id: int,
    csrf_token: Annotated[str, Form()],
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    settings = get_settings()
    inst = get_sdwan_manager(db, user.id, instance_id)
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
    result = probe_from_credentials(
        settings.secret_key,
        base_url=inst.base_url,
        auth_mode=inst.auth_mode,
        credentials_encrypted=inst.credentials_encrypted,
        verify_tls=inst.verify_tls,
    )
    _apply_probe(inst, result, auth_mode=inst.auth_mode, secret_key=settings.secret_key)
    if result.ok:
        _detect_and_store_credential_scope(settings.secret_key, inst)
    db.add(inst)
    db.commit()
    q = "verified=ok" if result.ok else "verified=fail"
    return RedirectResponse(url=f"/administration/sd-wan?{q}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sd-wan/{instance_id}/delete", response_model=None)
def sdwan_delete_instance(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    instance_id: int,
    csrf_token: Annotated[str, Form()],
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    inst = get_sdwan_manager(db, user.id, instance_id)
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found.")
    delete_sdwan_manager(db, inst)
    return RedirectResponse(url="/administration/sd-wan?deleted=1", status_code=status.HTTP_303_SEE_OTHER)
