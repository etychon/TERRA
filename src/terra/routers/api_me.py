"""Authenticated end-user utilities (non-admin)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from terra.cellular_quality import rssi_quality_band
from terra.config import get_settings
from terra.crud_devices import (
    get_device_for_user,
    get_devices_for_user_by_ids,
    list_devices_for_api,
    list_map_device_telemetry_for_ui,
)
from terra.crud_sdwan import get_sdwan_manager
from terra.db import get_db
from terra.deps import get_current_user
from terra.inventory_extract import device_has_cellular_capability, utc_iso_for_json
from terra.models import SdWanLinkStatus, SdWanManagerInstance, SyncedDevice, User
from terra.schemas import (
    CellularHistoryResponse,
    CellularHistorySeries,
    CellularSparklineItem,
    CellularSparklinePoint,
    CellularSparklinesResponse,
    DeviceHomeRow,
    DevicesListResponse,
    LiveSdWanCellularTable,
    LiveSdWanDeviceResponse,
    LiveSdWanInterfaceRow,
    MapDeviceTelemetryItem,
    MapDeviceTelemetryResponse,
    SyncDevicesStats,
    SyncJobCancelResponse,
    SyncJobQueued,
    SyncJobStatus,
)
from terra.telemetry_query import default_history_window_seconds, query_cellular_range
from terra_sdwan.sdwan_device_live import fetch_live_device_dashboard
from terra_sdwan.sdwan_http import open_manager_http_client
from terra_sdwan.sdwan_sync import sync_devices_for_instance, sync_user_sdwan_devices
from terra_sdwan.sdwan_sync_job_runner import get_job, request_cancel_job, start_job

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.get("/devices", response_model=DevicesListResponse)
def list_devices(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=200),
    sort: str = Query("hostname", max_length=64),
    dir: Literal["asc", "desc"] = Query("asc", alias="dir"),
    hide_control: bool = Query(True),
) -> DevicesListResponse:
    """Paginated device inventory for the React devices grid."""
    items, total = list_devices_for_api(
        db,
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        sort_dir=dir,
        hide_control=hide_control,
    )
    return DevicesListResponse(
        items=[DeviceHomeRow.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    return SyncDevicesStats(
        managers=int(stats["managers"]),
        rows_touched=int(stats["rows_touched"]),
        errors=int(stats["errors"]),
        last_sync_at_utc=None,
        error_detail=None,
    )


@router.post("/sync-sdwan-devices/{instance_id}", response_model=SyncDevicesStats)
def sync_sdwan_devices_one_manager(
    instance_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SyncDevicesStats:
    """Pull device inventory from one SD-WAN manager owned by the current user."""
    inst = get_sdwan_manager(db, user.id, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="SD-WAN manager not found.")
    settings = get_settings()
    n, err = sync_devices_for_instance(db, settings.secret_key, inst)
    if err is None:
        try:
            from terra_sdwan.sdwan_cellular_history import sync_cellular_history_for_instance

            sync_cellular_history_for_instance(db, settings.secret_key, inst)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Cellular history sync failed instance_id=%s",
                instance_id,
            )
    db.commit()
    db.refresh(inst)
    last_iso = utc_iso_for_json(inst.devices_last_sync_at_utc) if inst.devices_last_sync_at_utc else None
    return SyncDevicesStats(
        managers=1,
        rows_touched=max(n, 0),
        errors=1 if err else 0,
        last_sync_at_utc=last_iso,
        error_detail=err,
    )


@router.post("/sync-sdwan-devices/{instance_id}/async", response_model=SyncJobQueued)
def sync_sdwan_devices_one_manager_async(
    instance_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SyncJobQueued:
    """Queue a background inventory sync (use ``GET …/sync-sdwan-jobs/{job_id}`` for progress)."""
    inst = get_sdwan_manager(db, user.id, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="SD-WAN manager not found.")
    job_id = start_job(user.id, instance_id)
    return SyncJobQueued(job_id=job_id)


@router.get("/sync-sdwan-jobs/{job_id}", response_model=SyncJobStatus)
def sync_sdwan_job_status(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> SyncJobStatus:
    snap = get_job(job_id, user.id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Sync job not found.")
    return SyncJobStatus.model_validate(snap)


@router.post("/sync-sdwan-jobs/{job_id}/cancel", response_model=SyncJobCancelResponse)
def sync_sdwan_job_cancel(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> SyncJobCancelResponse:
    accepted, reason = request_cancel_job(job_id, user.id)
    if reason == "not_found":
        raise HTTPException(status_code=404, detail="Sync job not found.")
    if not accepted and reason == "terminal":
        return SyncJobCancelResponse(
            accepted=False,
            message="Job already finished.",
        )
    return SyncJobCancelResponse(
        accepted=accepted,
        message="Cancellation requested — the sync stops after the current step.",
    )


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
        tlog = ((row.sdwan_tenant_name or "").strip() or (row.sdwan_tenant_id or "").strip()) or None
        with open_manager_http_client(settings.secret_key, inst, log_tenant=tlog) as http_client:
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


def _parse_unix_param(raw: str | None, *, default: float) -> float:
    if raw is None or not str(raw).strip():
        return default
    s = str(raw).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except ValueError:
        return default


def _device_parsed(row: SyncedDevice) -> dict[str, Any]:
    try:
        parsed: dict[str, Any] = json.loads(row.raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed


@router.get("/devices/{device_id}/cellular/history", response_model=CellularHistoryResponse)
def cellular_device_history(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    start: str | None = Query(None, description="Range start (unix seconds or ISO-8601)"),
    end: str | None = Query(None, description="Range end (unix seconds or ISO-8601)"),
    metrics: str = Query("rsrp,rsrq", description="Comma-separated: rsrp, rsrq"),
    slot: str | None = Query(None),
    active_sim: str | None = Query(None),
) -> CellularHistoryResponse:
    """Cellular RF history from VictoriaMetrics (EIOLTE ingest)."""
    row = get_device_for_user(db, user.id, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    parsed = _device_parsed(row)
    has_cell = device_has_cellular_capability(parsed, model=row.model, hostname=row.hostname)
    default_start, default_end = default_history_window_seconds(24)
    end_unix = _parse_unix_param(end, default=default_end)
    start_unix = _parse_unix_param(start, default=default_start)
    if start_unix >= end_unix:
        start_unix = end_unix - 3600

    metric_names = [m.strip().lower() for m in metrics.split(",") if m.strip()]
    if not metric_names:
        metric_names = ["rsrp", "rsrq"]

    series_out: list[CellularHistorySeries] = []
    note: str | None = None
    if not (get_settings().victoriametrics_url or "").strip():
        note = "VictoriaMetrics is not configured."
    else:
        span = end_unix - start_unix
        step = max(60, int(span / 500))
        for metric in metric_names:
            if metric not in ("rsrp", "rsrq", "rssi"):
                continue
            for s in query_cellular_range(
                metric,
                device_id=device_id,
                start_unix=start_unix,
                end_unix=end_unix,
                step_seconds=step,
                slot=slot,
                active_sim=active_sim,
            ):
                series_out.append(
                    CellularHistorySeries(
                        metric=metric,
                        unit="dBm",
                        slot=s.get("slot", ""),
                        active_sim=s.get("active_sim", ""),
                        timestamps=s.get("timestamps", []),
                        values=s.get("values", []),
                    )
                )
        if has_cell and not series_out and note is None:
            note = "No cellular history samples yet. Wait for the next background sync."

    return CellularHistoryResponse(
        ok=True,
        device_id=device_id,
        has_cellular=has_cell,
        start_unix=start_unix,
        end_unix=end_unix,
        series=series_out,
        note=note,
    )


@router.get("/devices/cellular/sparklines", response_model=CellularSparklinesResponse)
def cellular_sparklines(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    ids: str = Query(..., description="Comma-separated TERRA device ids"),
    minutes: int = Query(1440, ge=15, le=1440),
) -> CellularSparklinesResponse:
    """Batch RSSI sparklines and quality dots for the devices table."""
    id_parts = [p.strip() for p in ids.split(",") if p.strip()]
    device_ids: list[int] = []
    for p in id_parts[:50]:
        try:
            device_ids.append(int(p))
        except ValueError:
            continue
    if not device_ids:
        return CellularSparklinesResponse(items=[])

    rows = get_devices_for_user_by_ids(db, user.id, device_ids)
    end_unix = time.time()
    start_unix = end_unix - minutes * 60
    step = max(30, int((minutes * 60) / 30))

    items: list[CellularSparklineItem] = []
    for row in rows:
        parsed = _device_parsed(row)
        has_cell = device_has_cellular_capability(parsed, model=row.model, hostname=row.hostname)
        points: list[CellularSparklinePoint] = []
        latest: float | None = None
        if has_cell and (get_settings().victoriametrics_url or "").strip():
            series = query_cellular_range(
                "rssi",
                device_id=row.id,
                start_unix=start_unix,
                end_unix=end_unix,
                step_seconds=step,
            )
            merged_ts: list[int] = []
            merged_vals: list[float] = []
            for s in series:
                for ts, val in zip(s.get("timestamps", []), s.get("values", []), strict=False):
                    merged_ts.append(ts)
                    merged_vals.append(val)
            if merged_ts:
                order = sorted(range(len(merged_ts)), key=lambda i: merged_ts[i])
                for i in order:
                    points.append(CellularSparklinePoint(t=merged_ts[i], v=merged_vals[i]))
                latest = merged_vals[order[-1]]
        items.append(
            CellularSparklineItem(
                device_id=row.id,
                has_cellular=has_cell,
                points=points,
                latest_rssi=latest,
                quality=rssi_quality_band(latest),
            )
        )
    return CellularSparklinesResponse(items=items)
