"""EIOLTE cellular RF history via Manager statistics ``uniqueAggregation``."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.inventory_extract import device_has_cellular_capability, system_ip_from_inventory
from terra.models import SdWanManagerInstance, SyncedDevice
from terra.telemetry_vm import push_cellular_samples
from terra_sdwan.sdwan_http import open_manager_http_client, refresh_sdwan_dataservice_csrf_header
from terra_sdwan.sdwan_sync import switch_tenant

logger = logging.getLogger(__name__)

EIOLTE_PATH = "dataservice/statistics/eiolte/uniqueAggregation"

_AGGREGATION_FIELDS: tuple[tuple[str, int], ...] = (
    ("rsrp", 1),
    ("rsrq", 2),
    ("mcc", 3),
    ("mnc", 4),
    ("carrier", 5),
    ("rat", 6),
    ("ps_domain", 7),
    ("emm_state", 8),
    ("lteband", 9),
    ("ltebw", 10),
    ("lteca", 11),
    ("active_sim", 12),
    ("bandclass", 13),
    ("slot", 14),
    ("pci", 15),
)


@dataclass(frozen=True, slots=True)
class CellularBucket:
    entry_time_ms: int
    rsrp: float | None
    rsrq: float | None
    rssi: float | None
    slot: str
    active_sim: str
    count: int | None = None


def build_eiolte_unique_aggregation_body(
    system_ip: str,
    hours: int | str,
    *,
    histogram_minutes: int = 30,
    omit_ps_domain: bool = False,
    ps_domain_values: tuple[str, ...] = ("Attached",),
) -> dict[str, Any]:
    """Build POST body for ``/dataservice/statistics/eiolte/uniqueAggregation`` (20.18 pattern)."""
    sip = str(system_ip).strip()
    if not sip:
        msg = "system_ip required for EIOLTE statistics"
        raise ValueError(msg)
    h = str(int(hours)) if isinstance(hours, int) else str(hours).strip()
    rules: list[dict[str, Any]] = [
        {
            "value": [h],
            "field": "entry_time",
            "type": "date",
            "operator": "last_n_hours",
        },
        {
            "value": [sip],
            "field": "vdevice_name",
            "type": "string",
            "operator": "in",
        },
        {
            "value": ["0"],
            "field": "rssi",
            "type": "string",
            "operator": "not_equal",
        },
    ]
    if not omit_ps_domain and ps_domain_values:
        rules.append(
            {
                "value": list(ps_domain_values),
                "field": "ps_domain",
                "type": "string",
                "operator": "in",
            }
        )
    agg_fields = [{"property": prop, "sequence": seq} for prop, seq in _AGGREGATION_FIELDS]
    return {
        "query": {"condition": "AND", "rules": rules},
        "aggregation": {
            "field": agg_fields,
            "metrics": [{"property": "rssi", "type": "avg"}],
            "histogram": {
                "property": "entry_time",
                "type": "minute",
                "interval": max(1, int(histogram_minutes)),
                "order": "asc",
            },
        },
        "size": 10000,
    }


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _slot_sim_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def parse_eiolte_buckets(payload: Any) -> list[CellularBucket]:
    """Parse ``data[]`` from a successful uniqueAggregation response."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    allowed: set[str] | None = None
    header = payload.get("header")
    if isinstance(header, dict):
        fields = header.get("fields") or header.get("columns")
        if isinstance(fields, list):
            names: set[str] = set()
            for f in fields:
                if isinstance(f, dict) and f.get("property"):
                    names.add(str(f["property"]))
            if names:
                allowed = names
    out: list[CellularBucket] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if allowed is not None and "entry_time" not in allowed and "entry_time" not in row:
            continue
        et = _coerce_int(row.get("entry_time"))
        if et is None or et <= 0:
            continue
        out.append(
            CellularBucket(
                entry_time_ms=et,
                rsrp=_coerce_float(row.get("rsrp")),
                rsrq=_coerce_float(row.get("rsrq")),
                rssi=_coerce_float(row.get("rssi")),
                slot=_slot_sim_str(row.get("slot")),
                active_sim=_slot_sim_str(row.get("active_sim")),
                count=_coerce_int(row.get("count")),
            )
        )
    return out


def dedupe_buckets(buckets: list[CellularBucket]) -> list[CellularBucket]:
    """Keep the last row per ``(entry_time_ms, slot, active_sim)``."""
    merged: dict[tuple[int, str, str], CellularBucket] = {}
    for b in buckets:
        key = (b.entry_time_ms, b.slot, b.active_sim)
        merged[key] = b
    return sorted(merged.values(), key=lambda x: x.entry_time_ms)


def post_eiolte_history(
    client: httpx.Client,
    base_url: str,
    body: dict[str, Any],
    *,
    timeout: float = 45.0,
) -> tuple[int, Any | None]:
    """POST uniqueAggregation; returns ``(status_code, json_or_none)``."""
    url = f"{base_url.rstrip('/')}/{EIOLTE_PATH.lstrip('/')}"
    try:
        r = client.post(
            url,
            json=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout,
        )
    except httpx.RequestError as e:
        logger.debug("EIOLTE POST failed: %s", e)
        return 0, None
    if r.status_code >= 400:
        logger.debug("EIOLTE POST HTTP %s for %s", r.status_code, sip_from_body(body))
        return r.status_code, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def sip_from_body(body: dict[str, Any]) -> str:
    try:
        rules = body["query"]["rules"]
        for rule in rules:
            if rule.get("field") == "vdevice_name":
                vals = rule.get("value")
                if isinstance(vals, list) and vals:
                    return str(vals[0])
    except (KeyError, TypeError):
        pass
    return "?"


def load_cellular_stats_cursor(raw: str | None) -> dict[str, int]:
    """Map ``slot:active_sim`` → max ingested ``entry_time`` ms."""
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def save_cellular_stats_cursor(cursor: dict[str, int]) -> str:
    return json.dumps(cursor, separators=(",", ":"))


def _cursor_key(slot: str, active_sim: str) -> str:
    return f"{slot}:{active_sim}"


def filter_buckets_after_cursor(
    buckets: list[CellularBucket],
    cursor: dict[str, int],
) -> list[CellularBucket]:
    """Drop buckets at or before the stored max ``entry_time`` per dimension."""
    if not cursor:
        return buckets
    out: list[CellularBucket] = []
    for b in buckets:
        prev = cursor.get(_cursor_key(b.slot, b.active_sim), 0)
        if b.entry_time_ms > prev:
            out.append(b)
    return out


def merge_buckets_into_cursor(
    cursor: dict[str, int],
    buckets: list[CellularBucket],
) -> dict[str, int]:
    updated = dict(cursor)
    for b in buckets:
        key = _cursor_key(b.slot, b.active_sim)
        updated[key] = max(updated.get(key, 0), b.entry_time_ms)
    return updated


def buckets_to_vm_samples(
    *,
    buckets: list[CellularBucket],
    manager_id: str,
    cluster: str,
    device_id: int,
    device_uuid: str,
) -> list[tuple[str, dict[str, str], float, int]]:
    """``(metric_name, labels, value, timestamp_ms)`` tuples for Prometheus import."""
    lines: list[tuple[str, dict[str, str], float, int]] = []
    base_labels = {
        "manager_id": manager_id,
        "cluster": cluster[:120],
        "device_id": str(device_id),
        "device_uuid": (device_uuid or "")[:160],
    }
    for b in buckets:
        labels = {
            **base_labels,
            "slot": b.slot[:32],
            "active_sim": b.active_sim[:32],
        }
        ts = b.entry_time_ms
        if b.rssi is not None:
            lines.append(("terra_cellular_rssi", labels, b.rssi, ts))
        if b.rsrp is not None:
            lines.append(("terra_cellular_rsrp", labels, b.rsrp, ts))
        if b.rsrq is not None:
            lines.append(("terra_cellular_rsrq", labels, b.rsrq, ts))
    return lines


def _is_wan_edge_row(device_type: str) -> bool:
    dt = (device_type or "").strip().lower()
    if not dt:
        return True
    if dt in ("vmanage", "vsmart", "vbond", "vcontainer") or dt.startswith("vmanage"):
        return False
    return dt == "vedge" or "edge" in dt


@dataclass(frozen=True, slots=True)
class CellularDeviceWork:
    device_id: int
    tenant_id: str
    raw_json: str
    cellular_stats_cursor: str | None


def sync_cellular_history_for_instance(
    db: Session,
    secret_key: str,
    inst: SdWanManagerInstance,
) -> dict[str, Any]:
    """
    Pull EIOLTE history for cellular-capable WAN edges on this Manager and push to VictoriaMetrics.

    Best-effort; returns summary counters for logging.
    """
    settings = get_settings()
    stats: dict[str, Any] = {
        "devices_seen": 0,
        "devices_fetched": 0,
        "buckets_pushed": 0,
        "errors": 0,
    }
    if not settings.cellular_history_enabled:
        return stats
    if not settings.telemetry_push_enabled or not (settings.victoriametrics_url or "").strip():
        return stats

    rows = list(
        db.scalars(
            select(SyncedDevice).where(SyncedDevice.sdwan_instance_id == inst.id).order_by(SyncedDevice.id)
        )
    )
    work_items: list[CellularDeviceWork] = []
    for d in rows:
        if not _is_wan_edge_row(d.device_type):
            continue
        try:
            parsed: dict[str, Any] = json.loads(d.raw_json)
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}
        if not device_has_cellular_capability(parsed, model=d.model, hostname=d.hostname):
            continue
        if not system_ip_from_inventory(parsed):
            continue
        work_items.append(
            CellularDeviceWork(
                device_id=int(d.id),
                tenant_id=(d.sdwan_tenant_id or "").strip(),
                raw_json=d.raw_json,
                cellular_stats_cursor=d.cellular_stats_cursor,
            )
        )

    stats["devices_seen"] = len(work_items)
    if not work_items:
        return stats

    max_devices = max(0, settings.cellular_history_max_devices_per_sync)
    timeout = settings.cellular_history_http_timeout_seconds
    hist_min = settings.cellular_history_histogram_minutes
    omit_ps = settings.cellular_history_omit_ps_domain_filter
    if max_devices and len(work_items) > max_devices:
        work_items = work_items[:max_devices]

    cluster = (inst.display_name or "").strip() or f"id:{inst.id}"
    manager_id = str(inst.id)

    by_tenant: dict[str, list[CellularDeviceWork]] = {}
    for item in work_items:
        by_tenant.setdefault(item.tenant_id, []).append(item)

    all_samples: list[tuple[str, dict[str, str], float, int]] = []
    device_updates: list[tuple[int, str]] = []

    # Release row locks before slow Manager HTTP (collector must not block UI reads).
    db.commit()

    try:
        with open_manager_http_client(secret_key, inst) as client:
            base = inst.base_url.rstrip("/")
            # JWT statistics POSTs require X-XSRF-TOKEN from GET /dataservice/client/server (recipe + field work).
            refresh_sdwan_dataservice_csrf_header(client, base)
            for tenant_id, group in by_tenant.items():
                if tenant_id:
                    try:
                        refresh_sdwan_dataservice_csrf_header(client, base)
                        switch_tenant(
                            client,
                            base,
                            tenant_id,
                            request_timeout=settings.sdwan_sync_inventory_timeout_seconds,
                        )
                    except (RuntimeError, ValueError) as e:
                        logger.warning(
                            "Cellular history tenant switch failed instance=%s tenant=%s: %s",
                            inst.id,
                            tenant_id,
                            e,
                        )
                        stats["errors"] += len(group)
                        continue

                for item in group:
                    try:
                        parsed = json.loads(item.raw_json)
                        if not isinstance(parsed, dict):
                            parsed = {}
                    except json.JSONDecodeError:
                        parsed = {}
                    system_ip = system_ip_from_inventory(parsed)
                    if not system_ip:
                        continue

                    cursor = load_cellular_stats_cursor(item.cellular_stats_cursor)
                    hours = (
                        settings.cellular_history_hours
                        if cursor
                        else settings.cellular_history_backfill_hours
                    )

                    body = build_eiolte_unique_aggregation_body(
                        system_ip,
                        hours,
                        histogram_minutes=hist_min,
                        omit_ps_domain=omit_ps,
                    )
                    status, payload = post_eiolte_history(client, base, body, timeout=timeout)
                    if status >= 400 or payload is None:
                        stats["errors"] += 1
                        continue

                    stats["devices_fetched"] += 1
                    buckets = dedupe_buckets(parse_eiolte_buckets(payload))
                    buckets = filter_buckets_after_cursor(buckets, cursor)
                    if not buckets:
                        continue

                    new_cursor = merge_buckets_into_cursor(cursor, buckets)
                    all_samples.extend(
                        buckets_to_vm_samples(
                            buckets=buckets,
                            manager_id=manager_id,
                            cluster=cluster,
                            device_id=item.device_id,
                            device_uuid=str(parsed.get("uuid") or parsed.get("deviceId") or item.device_id),
                        )
                    )
                    stats["buckets_pushed"] += len(buckets)
                    device_updates.append((item.device_id, save_cellular_stats_cursor(new_cursor)))
    except (ValueError, OSError, RuntimeError, httpx.RequestError) as e:
        logger.warning("Cellular history sync failed instance=%s: %s", inst.id, e)
        stats["errors"] += 1
        return stats

    if all_samples:
        push_cellular_samples(samples=all_samples)

    for device_id, cursor_json in device_updates:
        device = db.get(SyncedDevice, device_id)
        if device is not None:
            device.cellular_stats_cursor = cursor_json
            db.add(device)

    return stats


def sync_cellular_history_for_device(
    db: Session,
    secret_key: str,
    inst: SdWanManagerInstance,
    device: SyncedDevice,
) -> dict[str, Any]:
    """Pull EIOLTE history for one cellular-capable device; returns summary counters."""
    settings = get_settings()
    stats: dict[str, Any] = {
        "devices_seen": 0,
        "devices_fetched": 0,
        "buckets_pushed": 0,
        "errors": 0,
    }
    if not settings.cellular_history_enabled:
        return stats
    if not settings.telemetry_push_enabled or not (settings.victoriametrics_url or "").strip():
        return stats
    if not _is_wan_edge_row(device.device_type):
        return stats
    try:
        parsed: dict[str, Any] = json.loads(device.raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    if not device_has_cellular_capability(parsed, model=device.model, hostname=device.hostname):
        return stats
    if not system_ip_from_inventory(parsed):
        return stats

    work = CellularDeviceWork(
        device_id=int(device.id),
        tenant_id=(device.sdwan_tenant_id or "").strip(),
        raw_json=device.raw_json,
        cellular_stats_cursor=device.cellular_stats_cursor,
    )
    stats["devices_seen"] = 1

    timeout = settings.cellular_history_http_timeout_seconds
    hist_min = settings.cellular_history_histogram_minutes
    omit_ps = settings.cellular_history_omit_ps_domain_filter
    cluster = (inst.display_name or "").strip() or f"id:{inst.id}"
    manager_id = str(inst.id)

    db.commit()

    all_samples: list[tuple[str, dict[str, str], float, int]] = []
    device_updates: list[tuple[int, str]] = []

    try:
        with open_manager_http_client(secret_key, inst) as client:
            base = inst.base_url.rstrip("/")
            refresh_sdwan_dataservice_csrf_header(client, base)
            tenant_id = work.tenant_id
            if tenant_id:
                refresh_sdwan_dataservice_csrf_header(client, base)
                switch_tenant(
                    client,
                    base,
                    tenant_id,
                    request_timeout=settings.sdwan_sync_inventory_timeout_seconds,
                )
            system_ip = system_ip_from_inventory(parsed)
            if not system_ip:
                return stats
            cursor = load_cellular_stats_cursor(work.cellular_stats_cursor)
            hours = (
                settings.cellular_history_hours if cursor else settings.cellular_history_backfill_hours
            )
            body = build_eiolte_unique_aggregation_body(
                system_ip,
                hours,
                histogram_minutes=hist_min,
                omit_ps_domain=omit_ps,
            )
            status, payload = post_eiolte_history(client, base, body, timeout=timeout)
            if status >= 400 or payload is None:
                stats["errors"] += 1
                return stats
            stats["devices_fetched"] += 1
            buckets = dedupe_buckets(parse_eiolte_buckets(payload))
            buckets = filter_buckets_after_cursor(buckets, cursor)
            if buckets:
                new_cursor = merge_buckets_into_cursor(cursor, buckets)
                all_samples.extend(
                    buckets_to_vm_samples(
                        buckets=buckets,
                        manager_id=manager_id,
                        cluster=cluster,
                        device_id=work.device_id,
                        device_uuid=str(parsed.get("uuid") or parsed.get("deviceId") or work.device_id),
                    )
                )
                stats["buckets_pushed"] += len(buckets)
                device_updates.append((work.device_id, save_cellular_stats_cursor(new_cursor)))
    except (ValueError, OSError, RuntimeError, httpx.RequestError) as e:
        logger.warning(
            "Cellular history sync failed instance=%s device=%s: %s",
            inst.id,
            device.id,
            e,
        )
        stats["errors"] += 1
        return stats

    if all_samples:
        push_cellular_samples(samples=all_samples)

    for device_id, cursor_json in device_updates:
        row = db.get(SyncedDevice, device_id)
        if row is not None:
            row.cellular_stats_cursor = cursor_json
            db.add(row)

    return stats
