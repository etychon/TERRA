"""Authenticated end-user utilities (non-admin)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.crud_devices import get_device_for_user, list_map_device_telemetry_for_ui
from terra.db import get_db
from terra.deps import get_current_user
from terra.models import SdWanLinkStatus, SdWanManagerInstance, User
from terra.schemas import (
    LiveSdWanCellularTable,
    LiveSdWanDeviceResponse,
    LiveSdWanInterfaceRow,
    MapDeviceTelemetryItem,
    MapDeviceTelemetryResponse,
    SyncDevicesStats,
)
from terra.sdwan_device_live import fetch_live_device_dashboard
from terra.sdwan_http import open_manager_http_client
from terra.sdwan_sync import sync_user_sdwan_devices

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/map-devices-telemetry", response_model=MapDeviceTelemetryResponse)
def map_devices_telemetry(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> MapDeviceTelemetryResponse:
    """Poll map devices (with coordinates): sync/reachability fingerprint for client ripples."""
    rows = list_map_device_telemetry_for_ui(db)
    return MapDeviceTelemetryResponse(
        devices=[MapDeviceTelemetryItem.model_validate(r) for r in rows],
    )


@router.post("/sync-sdwan-devices", response_model=SyncDevicesStats)
def sync_sdwan_devices_now(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SyncDevicesStats:
    """Pull device inventory from all connected SD-WAN managers for the current user."""
    settings = get_settings()
    stats = sync_user_sdwan_devices(db, settings.secret_key, user.id)
    return SyncDevicesStats.model_validate(stats)


@router.get("/devices/{device_id}/live-sdwan", response_model=LiveSdWanDeviceResponse)
def live_sdwan_device_snapshot(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> LiveSdWanDeviceResponse:
    """Poll Manager dataservice for this device (interfaces + cellular/WAN); JSON for browser polling."""
    row = get_device_for_user(db, user.id, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    try:
        parsed: dict[str, Any] = json.loads(row.raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}

    settings = get_settings()
    inst = db.get(SdWanManagerInstance, row.sdwan_instance_id)
    fetched = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if inst is None or inst.link_status != SdWanLinkStatus.connected.value:
        return LiveSdWanDeviceResponse(
            ok=False,
            fetched_at=fetched,
            note="SD-WAN Manager is not connected for this device.",
        )

    try:
        with open_manager_http_client(settings.secret_key, inst) as http_client:
            iface_rows, sections, note = fetch_live_device_dashboard(
                http_client,
                inst.base_url,
                parsed,
                request_timeout=settings.device_live_http_timeout_seconds,
            )
    except (ValueError, OSError, RuntimeError, httpx.RequestError) as e:
        return LiveSdWanDeviceResponse(ok=False, fetched_at=fetched, note=str(e)[:500])

    cellular: list[LiveSdWanCellularTable] = []
    for t in sections:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title", ""))
        cols = t.get("columns")
        rws = t.get("rows")
        if not isinstance(cols, list):
            cols = []
        if not isinstance(rws, list):
            rws = []
        cellular.append(
            LiveSdWanCellularTable(
                title=title,
                columns=[str(c) for c in cols],
                rows=[[str(c) for c in line] for line in rws if isinstance(line, list)],
            )
        )

    return LiveSdWanDeviceResponse(
        ok=True,
        fetched_at=fetched,
        note=note,
        interfaces=[LiveSdWanInterfaceRow.model_validate(r) for r in iface_rows],
        cellular_tables=cellular,
    )
