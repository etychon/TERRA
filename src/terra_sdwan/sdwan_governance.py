"""Cisco Catalyst SD-WAN Manager governance ingest (alarms, events, audit)."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from terra.app_log_buffer import append_event
from terra.config import get_settings
from terra.inventory_extract import system_ip_from_inventory
from terra.models import (
    SdWanGovernanceEvent,
    SdWanGovernanceSyncState,
    SdWanLinkStatus,
    SdWanManagerInstance,
    SyncedDevice,
)
from terra_sdwan.sdwan_dataservice_rows import rows_from_dataservice_body
from terra_sdwan.sdwan_http import open_manager_http_client
from terra_sdwan.sdwan_sync import fetch_tenant_list, switch_tenant

logger = logging.getLogger(__name__)

StreamKind = Literal["alarm", "event", "audit"]

_STREAM_PATHS: dict[StreamKind, str] = {
    "alarm": "dataservice/alarms",
    "event": "dataservice/events",
    "audit": "dataservice/auditlog",
}

_FIELDS_PATHS: dict[StreamKind, str] = {
    "alarm": "dataservice/alarms/query/fields",
    "event": "dataservice/events/fields",
    "audit": "dataservice/auditlog/fields",
}

_LEGACY_EVENT_GET = "dataservice/event"

_RAW_JSON_MAX = 16384


def build_governance_query_body(*, hours: int, size: int = 2000) -> dict[str, Any]:
    """Rules-based POST body for alarms/events/audit (DevNet pattern)."""
    h = max(1, int(hours))
    return {
        "query": {
            "condition": "AND",
            "rules": [
                {
                    "field": "entry_time",
                    "type": "date",
                    "operator": "last_n_hours",
                    "value": [str(h)],
                }
            ],
        },
        "size": max(1, min(size, 10000)),
    }


def normalize_severity(raw: str | None) -> str:
    if not raw:
        return "unknown"
    s = str(raw).strip().lower()
    mapping = {
        "critical": "critical",
        "major": "major",
        "minor": "minor",
        "medium": "minor",
        "warning": "major",
        "info": "info",
        "information": "info",
        "notice": "info",
    }
    return mapping.get(s, s[:32] or "unknown")


def _pick_str(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in ("-", "—", "null", "None"):
            return s[:512]
    return ""


def _entry_time_ms(row: dict[str, Any]) -> int | None:
    for k in ("entry_time", "entryTime", "timestamp", "time"):
        v = row.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            n = int(v)
            if n > 1_000_000_000_000:
                return n
            if n > 1_000_000_000:
                return n * 1000
        if isinstance(v, str) and v.strip().isdigit():
            n = int(v.strip())
            if n > 1_000_000_000_000:
                return n
            if n > 1_000_000_000:
                return n * 1000
    return None


def _entry_datetime(row: dict[str, Any]) -> datetime:
    ms = _entry_time_ms(row)
    if ms is not None:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    return datetime.now(tz=UTC)


def governance_source_key(
    *,
    sdwan_instance_id: int,
    sdwan_tenant_id: str,
    stream_kind: str,
    row: dict[str, Any],
) -> str:
    parts = [
        str(sdwan_instance_id),
        sdwan_tenant_id or "",
        stream_kind,
        _pick_str(row, "uuid", "alarm_uuid", "event_id", "id", "_id"),
        _pick_str(row, "rule_name", "rule_name_display", "component", "eventname", "message"),
        str(_entry_time_ms(row) or ""),
        _pick_str(row, "system_ip", "vdevice_name", "logdeviceid"),
    ]
    if not parts[3]:
        parts.append(json.dumps(row, sort_keys=True, default=str)[:400])
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:48]
    return f"{stream_kind}:{digest}"


def normalize_governance_row(
    row: dict[str, Any],
    *,
    stream_kind: StreamKind,
) -> dict[str, Any]:
    """Map a Manager alarm/event/audit row to projection columns."""
    severity_raw = _pick_str(row, "severity", "severity_level", "severityLevel")
    if stream_kind == "alarm" and not severity_raw:
        severity_raw = _pick_str(row, "severity-level")
    active_raw = row.get("active")
    active: bool | None = None
    if isinstance(active_raw, bool):
        active = active_raw
    elif isinstance(active_raw, str):
        low = active_raw.strip().lower()
        if low in ("true", "1", "yes"):
            active = True
        elif low in ("false", "0", "no"):
            active = False

    system_ip = _pick_str(row, "system_ip", "system-ip", "vdevice_name", "vdevice-name", "logdeviceid", "deviceIp")
    site_id = _pick_str(row, "site_id", "site-id", "site_name", "site-name")
    title = _pick_str(
        row,
        "rule_name_display",
        "rule_name",
        "component",
        "eventname",
        "event_name",
        "logfeature",
        "type",
    )
    summary = _pick_str(row, "message", "details", "detail", "logmsg", "logdetail", "description")
    if not summary:
        summary = title
    if not title:
        title = summary[:120] if summary else stream_kind

    return {
        "severity_raw": severity_raw[:64] if severity_raw else "",
        "severity_norm": normalize_severity(severity_raw),
        "active": active,
        "system_ip": system_ip[:64] if system_ip else "",
        "site_id": site_id[:128] if site_id else "",
        "title": title[:512],
        "summary": summary[:2048],
        "component": _pick_str(row, "component", "logmodule")[:256],
        "rule_name": _pick_str(row, "rule_name", "rule_name_display", "eventname")[:256],
        "loguser": _pick_str(row, "loguser", "user", "username")[:128],
        "logfeature": _pick_str(row, "logfeature", "feature")[:128],
        "entry_time_utc": _entry_datetime(row),
    }


def _post_query_rows(
    client: httpx.Client,
    base_url: str,
    path: str,
    body: dict[str, Any],
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = client.post(url, json=body, headers={"Accept": "application/json"}, timeout=timeout)
    except httpx.RequestError as e:
        logger.debug("Governance POST %s failed: %s", path, e)
        return []
    if r.status_code >= 400:
        logger.debug("Governance POST %s HTTP %s", path, r.status_code)
        return []
    try:
        payload = r.json()
    except ValueError:
        return []
    return [x for x in rows_from_dataservice_body(payload) if isinstance(x, dict)]


def _fetch_event_rows(
    client: httpx.Client,
    base_url: str,
    body: dict[str, Any],
    *,
    timeout: float,
) -> tuple[list[dict[str, Any]], bool]:
    rows = _post_query_rows(client, base_url, _STREAM_PATHS["event"], body, timeout=timeout)
    if rows:
        return rows, False
    url = f"{base_url.rstrip('/')}/{_LEGACY_EVENT_GET.lstrip('/')}"
    try:
        r = client.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    except httpx.RequestError:
        return [], False
    if r.status_code == 404:
        return [], False
    if r.status_code >= 400:
        return [], False
    try:
        payload = r.json()
    except ValueError:
        return [], False
    legacy = [x for x in rows_from_dataservice_body(payload) if isinstance(x, dict)]
    return legacy, True


def fetch_governance_stream(
    client: httpx.Client,
    base_url: str,
    stream_kind: StreamKind,
    *,
    hours: int,
    timeout: float,
    size: int = 2000,
) -> tuple[list[dict[str, Any]], bool]:
    body = build_governance_query_body(hours=hours, size=size)
    if stream_kind == "event":
        return _fetch_event_rows(client, base_url, body, timeout=timeout)
    path = _STREAM_PATHS[stream_kind]
    return _post_query_rows(client, base_url, path, body, timeout=timeout), False


def _device_index_for_instance(
    db: Session,
    instance_id: int,
    tenant_id: str,
) -> dict[str, int]:
    q = select(SyncedDevice).where(
        SyncedDevice.sdwan_instance_id == instance_id,
        SyncedDevice.sdwan_tenant_id == tenant_id,
    )
    out: dict[str, int] = {}
    for dev in db.scalars(q):
        try:
            parsed = json.loads(dev.raw_json)
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}
        sip = system_ip_from_inventory(parsed)
        if sip:
            out[sip] = dev.id
        uuid = (dev.source_device_uuid or "").strip()
        if uuid:
            out[uuid] = dev.id
        if dev.hostname:
            out[dev.hostname.strip()] = dev.id
    return out


def _resolve_device_id(device_index: dict[str, int], system_ip: str) -> int | None:
    if not system_ip:
        return None
    return device_index.get(system_ip.strip())


def _get_sync_state(
    db: Session,
    instance_id: int,
    tenant_id: str,
    stream_kind: StreamKind,
) -> SdWanGovernanceSyncState | None:
    return db.execute(
        select(SdWanGovernanceSyncState).where(
            SdWanGovernanceSyncState.sdwan_instance_id == instance_id,
            SdWanGovernanceSyncState.sdwan_tenant_id == tenant_id,
            SdWanGovernanceSyncState.stream_kind == stream_kind,
        )
    ).scalar_one_or_none()


def _hours_for_stream(
    db: Session,
    instance_id: int,
    tenant_id: str,
    stream_kind: StreamKind,
) -> int:
    settings = get_settings()
    state = _get_sync_state(db, instance_id, tenant_id, stream_kind)
    if state is None or state.last_entry_time_ms is None:
        return settings.governance_backfill_hours
    overlap_ms = settings.governance_overlap_minutes * 60 * 1000
    delta_ms = max(0, int(time.time() * 1000) - int(state.last_entry_time_ms) + overlap_ms)
    hours = max(1, int(delta_ms / (3600 * 1000)) + 1)
    return min(hours, settings.governance_backfill_hours)


def upsert_governance_rows(
    db: Session,
    *,
    instance: SdWanManagerInstance,
    tenant_id: str,
    tenant_name: str,
    stream_kind: StreamKind,
    rows: list[dict[str, Any]],
    degraded: bool = False,
) -> tuple[int, int | None]:
    """Insert new governance rows; returns (inserted_count, max_entry_time_ms)."""
    if not rows:
        return 0, None
    device_index = _device_index_for_instance(db, instance.id, tenant_id)
    inserted = 0
    max_ms: int | None = None
    now = datetime.now(tz=UTC)
    for raw in rows:
        norm = normalize_governance_row(raw, stream_kind=stream_kind)
        ms = _entry_time_ms(raw)
        if ms is not None:
            max_ms = ms if max_ms is None else max(max_ms, ms)
        source_key = governance_source_key(
            sdwan_instance_id=instance.id,
            sdwan_tenant_id=tenant_id,
            stream_kind=stream_kind,
            row=raw,
        )
        existing = db.execute(
            select(SdWanGovernanceEvent.id).where(
                SdWanGovernanceEvent.sdwan_instance_id == instance.id,
                SdWanGovernanceEvent.source_key == source_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        try:
            raw_json = json.dumps(raw, default=str)
            if len(raw_json) > _RAW_JSON_MAX:
                raw_json = raw_json[:_RAW_JSON_MAX] + "…"
        except TypeError:
            raw_json = str(raw)[:_RAW_JSON_MAX]
        synced_device_id = _resolve_device_id(device_index, norm["system_ip"])
        db.add(
            SdWanGovernanceEvent(
                sdwan_instance_id=instance.id,
                sdwan_tenant_id=tenant_id,
                sdwan_tenant_name=tenant_name,
                user_id=instance.user_id,
                stream_kind=stream_kind,
                source_key=source_key,
                entry_time_utc=norm["entry_time_utc"],
                ingested_at_utc=now,
                severity_raw=norm["severity_raw"],
                severity_norm=norm["severity_norm"],
                active=norm["active"],
                system_ip=norm["system_ip"],
                site_id=norm["site_id"],
                synced_device_id=synced_device_id,
                title=norm["title"],
                summary=norm["summary"],
                component=norm["component"],
                rule_name=norm["rule_name"],
                loguser=norm["loguser"],
                logfeature=norm["logfeature"],
                raw_json=raw_json,
                degraded=degraded,
            )
        )
        inserted += 1
    return inserted, max_ms


def _update_sync_state(
    db: Session,
    instance_id: int,
    tenant_id: str,
    stream_kind: StreamKind,
    *,
    max_entry_time_ms: int | None,
    error: str | None = None,
    degraded: bool = False,
) -> None:
    state = _get_sync_state(db, instance_id, tenant_id, stream_kind)
    now = datetime.now(tz=UTC)
    if state is None:
        state = SdWanGovernanceSyncState(
            sdwan_instance_id=instance_id,
            sdwan_tenant_id=tenant_id,
            stream_kind=stream_kind,
        )
        db.add(state)
    if (
        max_entry_time_ms is not None
        and (state.last_entry_time_ms is None or max_entry_time_ms > state.last_entry_time_ms)
    ):
        state.last_entry_time_ms = max_entry_time_ms
    state.last_success_at = now
    state.last_error = error
    state.degraded = degraded


def purge_stale_governance_events(db: Session) -> int:
    settings = get_settings()
    cutoff = datetime.now(tz=UTC) - timedelta(days=settings.governance_retention_days)
    result = db.execute(delete(SdWanGovernanceEvent).where(SdWanGovernanceEvent.entry_time_utc < cutoff))
    if isinstance(result, CursorResult):
        return int(result.rowcount or 0)
    return 0


def sync_governance_for_instance(
    db: Session,
    secret_key: str,
    instance: SdWanManagerInstance,
) -> tuple[int, str | None]:
    """Pull alarms, events, and audit for one connected Manager instance."""
    if instance.link_status != SdWanLinkStatus.connected.value:
        return 0, "Manager not connected"
    settings = get_settings()
    timeout = settings.governance_http_timeout_seconds
    total_inserted = 0
    errors: list[str] = []
    try:
        with open_manager_http_client(secret_key, instance) as client:
            tenants = fetch_tenant_list(client, instance.base_url, request_timeout=timeout)
            tenant_slices: list[tuple[str, str]] = []
            if tenants:
                for t in tenants:
                    tid = str(t.get("tenantId") or t.get("id") or "").strip()
                    if not tid:
                        continue
                    tname = str(t.get("name") or t.get("tenantName") or tid).strip()
                    tenant_slices.append((tid, tname))
            else:
                tenant_slices.append(("", ""))

            for tenant_id, tenant_name in tenant_slices:
                if tenant_id:
                    try:
                        switch_tenant(client, instance.base_url, tenant_id, request_timeout=timeout)
                    except (RuntimeError, ValueError) as e:
                        errors.append(f"tenant {tenant_id}: {e}")
                        continue

                for stream in ("alarm", "event", "audit"):
                    hours = _hours_for_stream(db, instance.id, tenant_id, stream)
                    rows, degraded = fetch_governance_stream(
                        client,
                        instance.base_url,
                        stream,
                        hours=hours,
                        timeout=timeout,
                        size=settings.governance_query_size,
                    )
                    ins, max_ms = upsert_governance_rows(
                        db,
                        instance=instance,
                        tenant_id=tenant_id,
                        tenant_name=tenant_name,
                        stream_kind=stream,
                        rows=rows,
                        degraded=degraded,
                    )
                    total_inserted += ins
                    _update_sync_state(
                        db,
                        instance.id,
                        tenant_id,
                        stream,
                        max_entry_time_ms=max_ms,
                        degraded=degraded,
                    )
    except (ValueError, OSError, RuntimeError, httpx.RequestError) as e:
        return total_inserted, str(e)[:500]
    err = "; ".join(errors)[:500] if errors else None
    return total_inserted, err


def sync_governance_for_connected_managers(secret_key: str) -> None:
    """Background batch: governance ingest for every connected Manager."""
    from terra.db import get_session_factory

    run_id = secrets.token_hex(4)
    t0 = time.perf_counter()
    sf = get_session_factory()
    with sf() as db:
        instances = list(
            db.scalars(
                select(SdWanManagerInstance).where(
                    SdWanManagerInstance.link_status == SdWanLinkStatus.connected.value,
                )
            )
        )
    total_rows = 0
    errors = 0
    for inst in instances:
        with sf() as db:
            row = db.get(SdWanManagerInstance, inst.id)
            if row is None:
                continue
            n, err = sync_governance_for_instance(db, secret_key, row)
            purged = purge_stale_governance_events(db)
            db.commit()
            total_rows += n
            if err:
                errors += 1
                append_event(
                    "WARNING",
                    "sdwan_governance_sync",
                    f"Governance sync partial for {row.display_name}",
                    detail=f"run_id={run_id} instance_id={row.id} inserted={n} purged={purged} error={err}"[:4000],
                )
            else:
                append_event(
                    "INFO",
                    "sdwan_governance_sync",
                    f"Governance sync ok for {row.display_name}",
                    detail=f"run_id={run_id} instance_id={row.id} inserted={n} purged={purged}"[:4000],
                )
    wall_ms = int((time.perf_counter() - t0) * 1000)
    detail = (
        f"run_id={run_id} managers={len(instances)} rows={total_rows} "
        f"errors={errors} duration_ms={wall_ms}"
    )[:4000]
    append_event(
        "WARNING" if errors else "INFO",
        "sdwan_governance_sync",
        f"Governance batch finished ({len(instances)} managers)",
        detail=detail,
    )
