"""Pull device inventory from Cisco Catalyst SD-WAN Manager into the local database (UTC)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.app_log_buffer import append_event
from terra.config import get_settings
from terra.db import sdwan_batch_needs_serial_execution
from terra.inventory_extract import deep_find_serial
from terra.models import SdWanLinkStatus, SdWanManagerInstance, SyncedDevice
from terra_sdwan.sdwan_client import read_manager_version
from terra_sdwan.sdwan_dataservice_rows import rows_from_dataservice_body
from terra_sdwan.sdwan_device_live import enrich_inventory_row_for_sync
from terra_sdwan.sdwan_http import (
    manager_credential_mode,
    open_manager_http_client,
    refresh_sdwan_dataservice_csrf_header,
)
from terra_sdwan.sdwan_operator_log import clear_sdwan_http_log_tenant, set_sdwan_http_log_tenant

logger = logging.getLogger(__name__)

_FAIR_SYNC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _inventory_stale_sort_key(dt: datetime | None) -> float:
    """Sort oldest / never-synced managers first (timezone-safe)."""
    if dt is None:
        return _FAIR_SYNC_EPOCH.timestamp()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).timestamp()
    return dt.timestamp()


def _inventory_http_timeout_seconds() -> float:
    return float(get_settings().sdwan_sync_inventory_timeout_seconds)


class SdWanSyncCancelled(Exception):
    """Raised when an operator cancels an in-progress async inventory sync."""


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise SdWanSyncCancelled()


def _progress_notify(
    cb: Callable[[str, int, str], None] | None,
    phase: str,
    percent: int,
    message: str,
) -> None:
    if cb is None:
        return
    with suppress(Exception):
        cb(phase, min(100, max(0, int(percent))), message)

# When GET /dataservice/device returns no rows (some lab / CVD builds), try controller inventories.
_FALLBACK_DEVICE_PATHS: tuple[str, ...] = (
    "system/device/vedges",
    "system/device/controllers",
)
_VEDGES_FALLBACK_PATH = _FALLBACK_DEVICE_PATHS[0]

_CONTROLLER_DEVICE_TYPES: frozenset[str] = frozenset(
    {"vmanage", "vsmart", "vbond", "vcontainer", "vmanage-system"}
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _scalar_to_str(v: Any) -> str:
    """Stringify JSON scalars for inventory fields (Manager often sends numbers as unquoted JSON)."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        s = str(v).strip()
        return s
    return str(v).strip() if v else ""


def _coalesce_str(d: dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        s = _scalar_to_str(d.get(k))
        if s:
            return s
    return default


def _is_controller_inventory_row(device_type: str, hostname: str) -> bool:
    """Match ``terra.crud_sdwan._is_controller_inventory_row`` (control-plane only)."""
    dt = (device_type or "").strip().lower()
    if not dt:
        return False
    if dt in _CONTROLLER_DEVICE_TYPES or dt.startswith("vmanage"):
        return True
    host = (hostname or "").strip().lower()
    return host in ("vmanage", "vbond", "vsmart", "vsmart2")


def _raw_row_is_wan_edge(row: dict[str, Any]) -> bool:
    host = _coalesce_str(row, "host-name", "hostname", "ncsDeviceName", "vedgeName")
    dev_type = _coalesce_str(row, "deviceType", "device-type", "personality", "vedgePersonality")
    return not _is_controller_inventory_row(dev_type, host)


_CPU_ARCH_RE = re.compile(
    r"^(aarch64|arm64|armv7l|armv8l|x86_64|amd64|i386|i686|powerpc|ppc64le|riscv64)$",
    re.IGNORECASE,
)


def _looks_like_cpu_architecture(value: str) -> bool:
    return bool(_CPU_ARCH_RE.match(value.strip()))


_MODEL_FIELD_ORDER: tuple[str, ...] = (
    "deviceModel",
    "vedgeModel",
    "hardwareModel",
    "device-model",
    "pid",
    "PID",
    "pId",
    "productId",
    "product-id",
    "partNumber",
    "part-number",
    "sku",
    "SKU",
    "ncsDeviceType",
    "vedgeHWType",
    "hardwareType",
    "chassisDescription",
    "model",
    "platform",
)


def _device_model_from_row(row: dict[str, Any]) -> str:
    """
    Prefer hardware SKU / PID over CPU architecture strings often found in ``platform`` or ``model``.
    """
    for key in _MODEL_FIELD_ORDER:
        s = _scalar_to_str(row.get(key))
        if not s:
            continue
        if key in ("model", "platform") and _looks_like_cpu_architecture(s):
            continue
        return s
    for key in _MODEL_FIELD_ORDER:
        s = _scalar_to_str(row.get(key))
        if s:
            return s
    return ""


def _normalize_reachability(raw: str) -> str:
    s = raw.lower().strip()
    if s in ("reachable", "green", "true", "1", "up", "online"):
        return "reachable"
    if s in ("unreachable", "red", "false", "0", "down", "offline"):
        return "unreachable"
    return s or "unknown"


def normalize_inventory_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map a /dataservice/device row to normalized columns + full JSON."""
    uid = _coalesce_str(row, "uuid", "deviceId", "system-ip", "systemIp")
    if not uid:
        uid = _coalesce_str(row, "serialNumber", "chasisNumber", "chassisNumber")
    if not uid:
        digest = hashlib.sha256(
            json.dumps(row, sort_keys=True, default=str).encode("utf-8"),
        ).hexdigest()[:28]
        uid = f"synthetic-{digest}"
    host = _coalesce_str(row, "host-name", "hostname", "ncsDeviceName", "vedgeName")
    sn = _coalesce_str(
        row,
        "serialNumber",
        "serial-number",
        "serial",
        "SerialNumber",
        "chasisNumber",
        "chassisNumber",
        "board-serial-number",
        "boardSerialNumber",
        "chassisSerialNumber",
        "vin",
        "sn",
        "assetSerialNumber",
        "hardwareInventorySerialNumber",
    )
    if not sn:
        sn = deep_find_serial(row)
        if not sn:
            logger.debug(
                "SD-WAN inventory row still missing serial; top-level keys=%s",
                list(row.keys())[:50],
            )
    model = _device_model_from_row(row)
    sw = _coalesce_str(row, "version", "softwareVersion", "software_version", "vedgeVersion")
    dev_type = _coalesce_str(row, "deviceType", "device-type", "personality", "vedgePersonality")
    site = _coalesce_str(row, "site-id", "siteId", "site-name", "siteName") or None
    reach_raw = _coalesce_str(row, "reachability", "device-state", "deviceState", "state", default="unknown")
    reach = _normalize_reachability(reach_raw)
    return {
        "source_device_uuid": uid or sn or host or json.dumps(row, sort_keys=True)[:120],
        "hostname": host,
        "serial_number": sn,
        "model": model,
        "software_version": sw,
        "device_type": dev_type,
        "site_id": site,
        "reachability": reach,
        "raw": row,
    }


def _stable_device_key(row: dict[str, Any]) -> str:
    for key in (
        "uuid",
        "deviceId",
        "chasisNumber",
        "chassisNumber",
        "serialNumber",
        "system-ip",
        "systemIp",
        "ncsDeviceName",
    ):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
    digest = hashlib.sha256(
        json.dumps(row, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()[:40]
    return f"synthetic-{digest}"


def _tenant_switch_id(row: dict[str, Any]) -> str:
    """Resolve the path segment for ``POST …/tenant/{id}/switch``."""
    for k in ("tenantId", "id", "uuid", "tenant_id", "tenantUUID"):
        s = _scalar_to_str(row.get(k))
        if s:
            return s[:160]
    return ""


def _tenant_display_name(row: dict[str, Any]) -> str:
    for k in ("name", "orgName", "organizationName", "desc"):
        s = _scalar_to_str(row.get(k))
        if s:
            return s[:255]
    return _tenant_switch_id(row)[:255]


def fetch_tenant_list(
    client: httpx.Client, base_url: str, *, request_timeout: float | None = None
) -> list[dict[str, Any]]:
    """
    ``GET /dataservice/tenant`` — non-multitenant / inaccessible builds return an empty list
    (HTTP 400/403/404/405 treated as non-MT; some managers use 400 when the tenant API is not in use).
    """
    base = base_url.rstrip("/")
    to = float(request_timeout) if request_timeout is not None else _inventory_http_timeout_seconds()
    r = client.get(f"{base}/dataservice/tenant", headers={"Accept": "application/json"}, timeout=to)
    # Non-multitenant / legacy builds: tenant API missing, not applicable, or not allowed for this token.
    if r.status_code in (400, 403, 404, 405):
        return []
    if r.status_code >= 400:
        msg = f"tenant list HTTP {r.status_code}"
        raise RuntimeError(msg)
    try:
        body = r.json()
    except ValueError as e:
        msg = "tenant list invalid JSON"
        raise RuntimeError(msg) from e
    return rows_from_dataservice_body(body)


def _vsession_id_from_switch_response(response: httpx.Response) -> str | None:
    """``POST …/tenant/{id}/switch`` returns tenant scope via ``VSessionId`` (header and/or JSON body)."""
    for key in ("VSessionId", "vsessionid", "vSessionId"):
        raw = response.headers.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("VSessionId", "vSessionId", "vsessionId"):
        raw = body.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    data = body.get("data")
    if isinstance(data, dict):
        raw = data.get("VSessionId") or data.get("vSessionId")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def switch_tenant(
    client: httpx.Client, base_url: str, tenant_id: str, *, request_timeout: float | None = None
) -> str | None:
    """
    ``POST /dataservice/tenant/{tenantId}/switch`` — establishes tenant scope.

    Returns ``VSessionId`` when the Manager provides one. Callers should keep that header on
    ``GET /dataservice/system/device/vedges`` (and controllers); do **not** rely on
    ``GET /dataservice/device`` with ``VSessionId`` (often empty on multitenant builds).
    """
    tid = str(tenant_id).strip()
    if not tid:
        msg = "tenant id required for switch"
        raise ValueError(msg)
    base = base_url.rstrip("/")
    to = float(request_timeout) if request_timeout is not None else _inventory_http_timeout_seconds()
    client.headers.pop("VSessionId", None)
    r = client.post(
        f"{base}/dataservice/tenant/{tid}/switch",
        headers={"Accept": "application/json"},
        json={},
        timeout=to,
    )
    if r.status_code >= 400:
        msg = f"tenant switch HTTP {r.status_code}"
        raise RuntimeError(msg)
    vs = _vsession_id_from_switch_response(r)
    if vs:
        client.headers["VSessionId"] = vs
    return vs


def _get_dataservice_inventory_rows(
    client: httpx.Client,
    base: str,
    path: str,
    *,
    request_timeout: float,
) -> list[dict[str, Any]]:
    r = client.get(f"{base}/dataservice/{path}", headers={"Accept": "application/json"}, timeout=request_timeout)
    if r.status_code >= 400:
        return []
    try:
        body = r.json()
    except ValueError:
        return []
    return rows_from_dataservice_body(body)


def _fetch_device_inventory_with_vsession(
    client: httpx.Client,
    base: str,
    request_timeout: float,
) -> list[dict[str, Any]]:
    """
    Multitenant tenant scope: WAN edges and controllers come from system device category APIs.

    ``GET /dataservice/device`` with ``VSessionId`` is intentionally skipped (commonly empty).
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def ingest(rows: list[dict[str, Any]]) -> None:
        for item in rows:
            k = _stable_device_key(item)
            if k not in merged:
                order.append(k)
                merged[k] = item
            else:
                cur = merged[k]
                for fk, fv in item.items():
                    if fk not in cur or cur.get(fk) in (None, "", []):
                        cur[fk] = fv

    vedge_rows = _get_dataservice_inventory_rows(
        client, base, _VEDGES_FALLBACK_PATH, request_timeout=request_timeout
    )
    ingest(vedge_rows)
    controller_rows = _get_dataservice_inventory_rows(
        client, base, "system/device/controllers", request_timeout=request_timeout
    )
    ingest(controller_rows)
    return [merged[k] for k in order]


def fetch_device_inventory(
    client: httpx.Client,
    base_url: str,
    *,
    request_timeout: float | None = None,
) -> list[dict[str, Any]]:
    """GET /dataservice/device (and fallbacks) — full inventory list."""
    base = base_url.rstrip("/")
    to = float(request_timeout) if request_timeout is not None else _inventory_http_timeout_seconds()
    vs = (client.headers.get("VSessionId") or client.headers.get("vsessionid") or "").strip()
    if vs:
        return _fetch_device_inventory_with_vsession(client, base, to)
    r = client.get(f"{base}/dataservice/device", headers={"Accept": "application/json"}, timeout=to)

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def ingest(rows: list[dict[str, Any]]) -> None:
        for item in rows:
            k = _stable_device_key(item)
            if k not in merged:
                order.append(k)
                merged[k] = item
            else:
                cur = merged[k]
                for fk, fv in item.items():
                    if fk not in cur or cur.get(fk) in (None, "", []):
                        cur[fk] = fv

    if r.status_code < 400:
        try:
            body = r.json()
        except ValueError as e:
            msg = "device inventory invalid JSON"
            raise RuntimeError(msg) from e
        ingest(rows_from_dataservice_body(body))
    else:
        logger.debug(
            "SD-WAN primary device inventory HTTP %s; trying fallback paths",
            r.status_code,
        )

    has_wan_edge = any(_raw_row_is_wan_edge(item) for item in merged.values())
    if not has_wan_edge:
        ingest(_get_dataservice_inventory_rows(client, base, _VEDGES_FALLBACK_PATH, request_timeout=to))

    if not merged:
        for path in _FALLBACK_DEVICE_PATHS:
            ingest(_get_dataservice_inventory_rows(client, base, path, request_timeout=to))

    if not merged and r.status_code >= 400:
        msg = f"device inventory HTTP {r.status_code}"
        raise RuntimeError(msg)

    return [merged[k] for k in order]


def _gather_inventory_with_tenant_scopes(
    client: httpx.Client,
    base_url: str,
    *,
    inventory_timeout: float | None = None,
) -> tuple[list[tuple[dict[str, Any], str, str]], bool]:
    """
    Build (raw_row, sdwan_tenant_id, sdwan_tenant_name) tuples.
    For single-tenant Managers, tenant fields are ``""``.
    Returns (rows, any_tenant_phase_error); when the second value is True, callers must not prune stale rows.
    """
    to = float(inventory_timeout) if inventory_timeout is not None else _inventory_http_timeout_seconds()
    tenants = fetch_tenant_list(client, base_url, request_timeout=to)
    if not tenants:
        clear_sdwan_http_log_tenant()
        inv = fetch_device_inventory(client, base_url, request_timeout=to)
        return [(r, "", "") for r in inv], False

    switchable = [t for t in tenants if isinstance(t, dict) and _tenant_switch_id(t)]
    if not switchable:
        logger.warning(
            "SD-WAN multitenant: /dataservice/tenant returned rows but none had a usable tenant id for switch"
        )
        return [], True

    refresh_sdwan_dataservice_csrf_header(client, base_url)

    out: list[tuple[dict[str, Any], str, str]] = []
    any_err = False
    for t in switchable:
        tid_key = _tenant_switch_id(t)[:160]
        label = (_tenant_display_name(t) or tid_key)[:255]
        set_sdwan_http_log_tenant(label or tid_key)
        try:
            switch_tenant(client, base_url, tid_key, request_timeout=to)
        except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
            logger.warning("SD-WAN tenant switch failed (tenant_id=%s): %s", tid_key, e)
            any_err = True
            continue
        try:
            batch = fetch_device_inventory(client, base_url, request_timeout=to)
        except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
            logger.warning("SD-WAN inventory after tenant switch failed (tenant_id=%s): %s", tid_key, e)
            any_err = True
            continue
        for raw in batch:
            out.append((raw, tid_key, label))
    if not out:
        clear_sdwan_http_log_tenant()
        try:
            inv = fetch_device_inventory(client, base_url, request_timeout=to)
            if inv:
                out = [(r, "", "") for r in inv]
                any_err = False
        except (RuntimeError, ValueError, httpx.RequestError, OSError):
            logger.debug("SD-WAN provider-level fallback inventory failed", exc_info=True)
    return out, any_err


def _delete_stale_devices_for_instance(db: Session, instance_id: int, seen: set[tuple[str, str]]) -> None:
    """Remove DB rows not present in the last successful full inventory pull for this Manager."""
    q = select(SyncedDevice).where(SyncedDevice.sdwan_instance_id == instance_id)
    for d in list(db.scalars(q)):
        key = ((d.sdwan_tenant_id or "").strip(), d.source_device_uuid)
        if key not in seen:
            db.delete(d)


def _upsert_devices_from_inventory(
    db: Session,
    inst: SdWanManagerInstance,
    rows_scoped: list[tuple[dict[str, Any], str, str]],
    now: datetime,
    progress_notify: Callable[[str, int, str], None] | None,
    cancel_check: Callable[[], bool] | None,
    *,
    pct_lo: int,
    pct_hi: int,
) -> tuple[int, set[tuple[str, str]]]:
    """Insert or update ``SyncedDevice`` rows from inventory JSON (``seen`` drives stale deletion)."""
    touched = 0
    seen: set[tuple[str, str]] = set()
    n_save = len(rows_scoped)
    step_s = max(1, n_save // 10) if n_save else 1
    span = max(1, pct_hi - pct_lo)
    for si, (raw, tenant_id_scope, tenant_name_scope) in enumerate(rows_scoped):
        _raise_if_cancelled(cancel_check)
        if progress_notify and n_save and (si % step_s == 0 or si == n_save - 1):
            cur_pct = pct_lo + min(span, int(span * si / max(n_save, 1)))
            _progress_notify(
                progress_notify,
                "saving",
                cur_pct,
                f"Writing devices to database ({si + 1} of {n_save})…",
            )
        norm = normalize_inventory_row(raw)
        if not norm["source_device_uuid"]:
            continue
        uid = str(norm["source_device_uuid"])[:160]
        tid = (tenant_id_scope or "")[:160]
        tlabel = (tenant_name_scope or "")[:255]
        seen.add((tid, uid))
        existing = db.execute(
            select(SyncedDevice).where(
                SyncedDevice.sdwan_instance_id == inst.id,
                SyncedDevice.source_device_uuid == uid,
                SyncedDevice.sdwan_tenant_id == tid,
            )
        ).scalar_one_or_none()

        raw_json = json.dumps(raw, separators=(",", ":"), default=str)
        new_r = str(norm["reachability"])

        if existing is None:
            db.add(
                SyncedDevice(
                    sdwan_instance_id=inst.id,
                    source_device_uuid=uid,
                    sdwan_tenant_id=tid,
                    sdwan_tenant_name=tlabel,
                    hostname=str(norm["hostname"])[:255],
                    serial_number=str(norm["serial_number"])[:128],
                    model=str(norm["model"])[:128],
                    software_version=str(norm["software_version"])[:128],
                    device_type=str(norm["device_type"])[:64],
                    site_id=(str(norm["site_id"])[:64] if norm["site_id"] else None),
                    reachability=new_r[:32],
                    state_changed_at_utc=now,
                    synced_at_utc=now,
                    raw_json=raw_json,
                )
            )
            touched += 1
            continue

        old_r = existing.reachability
        if old_r != new_r:
            existing.state_changed_at_utc = now
        existing.hostname = str(norm["hostname"])[:255]
        existing.serial_number = str(norm["serial_number"])[:128]
        existing.model = str(norm["model"])[:128]
        existing.software_version = str(norm["software_version"])[:128]
        existing.device_type = str(norm["device_type"])[:64]
        existing.site_id = (str(norm["site_id"])[:64] if norm["site_id"] else None)
        existing.reachability = new_r[:32]
        existing.synced_at_utc = now
        existing.raw_json = raw_json
        existing.sdwan_tenant_name = tlabel
        touched += 1

    return touched, seen


def _enrich_one_scoped_row(
    secret_key: str,
    inst: SdWanManagerInstance,
    row_tuple: tuple[dict[str, Any], str, str],
    request_timeout: float,
) -> tuple[dict[str, Any], str, str]:
    raw, tid_scope, tname_scope = row_tuple
    tlog = (tname_scope or tid_scope or "").strip()
    try:
        set_sdwan_http_log_tenant(tlog)
        with open_manager_http_client(secret_key, inst, log_tenant=tlog) as c:
            eraw = enrich_inventory_row_for_sync(
                c,
                inst.base_url,
                raw,
                request_timeout=request_timeout,
                verify_tls=inst.verify_tls,
            )
        return (eraw, tid_scope, tname_scope)
    except Exception:
        logger.debug(
            "SD-WAN per-device enrich failed (instance id=%s name=%r)",
            inst.id,
            inst.display_name,
            exc_info=True,
        )
        return (raw, tid_scope, tname_scope)
    finally:
        clear_sdwan_http_log_tenant()


def _enrich_rows_scoped_parallel(
    secret_key: str,
    inst: SdWanManagerInstance,
    rows_scoped: list[tuple[dict[str, Any], str, str]],
    request_timeout: float,
    max_workers: int,
    progress_notify: Callable[[str, int, str], None] | None,
    cancel_check: Callable[[], bool] | None,
) -> list[tuple[dict[str, Any], str, str]]:
    """Per-device enrich; parallel only for JWT single-tenant style inventories (see caller)."""
    n_en = len(rows_scoped)
    if n_en == 0:
        return []
    if max_workers <= 1:
        out: list[tuple[dict[str, Any], str, str]] = []
        step = max(1, n_en // 10)
        with open_manager_http_client(secret_key, inst) as c:
            for i, (raw, tid_scope, tname_scope) in enumerate(rows_scoped):
                _raise_if_cancelled(cancel_check)
                tlog = (tname_scope or tid_scope or "").strip()
                set_sdwan_http_log_tenant(tlog)
                if progress_notify and (i % step == 0 or i == n_en - 1):
                    _progress_notify(
                        progress_notify,
                        "enriching",
                        62 + min(22, int(22 * i / max(n_en, 1))),
                        f"Enriching device details ({i + 1} of {n_en})…",
                    )
                try:
                    out.append(
                        (
                            enrich_inventory_row_for_sync(
                                c,
                                inst.base_url,
                                raw,
                                request_timeout=request_timeout,
                                verify_tls=inst.verify_tls,
                            ),
                            tid_scope,
                            tname_scope,
                        )
                    )
                except Exception:
                    logger.debug(
                        "SD-WAN per-device enrich failed (instance id=%s name=%r)",
                        inst.id,
                        inst.display_name,
                        exc_info=True,
                    )
                    out.append((raw, tid_scope, tname_scope))
                finally:
                    clear_sdwan_http_log_tenant()
        return out

    out_mut: list[tuple[dict[str, Any], str, str]] = list(rows_scoped)
    completed = 0
    step = max(1, n_en // 10)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="terra-sdwan-enrich") as pool:
        fut_to_idx = {
            pool.submit(_enrich_one_scoped_row, secret_key, inst, rows_scoped[i], request_timeout): i
            for i in range(n_en)
        }
        for fut in as_completed(fut_to_idx):
            _raise_if_cancelled(cancel_check)
            idx = fut_to_idx[fut]
            try:
                out_mut[idx] = fut.result()
            except Exception:
                out_mut[idx] = rows_scoped[idx]
            completed += 1
            if progress_notify and (completed % step == 0 or completed == n_en):
                _progress_notify(
                    progress_notify,
                    "enriching",
                    62 + min(22, int(22 * completed / max(n_en, 1))),
                    f"Enriching device details ({completed} of {n_en})…",
                )
    return out_mut


def _apply_enriched_raw_to_db(
    db: Session,
    inst: SdWanManagerInstance,
    enriched_scoped: list[tuple[dict[str, Any], str, str]],
    now: datetime,
    progress_notify: Callable[[str, int, str], None] | None,
    cancel_check: Callable[[], bool] | None,
) -> None:
    """Merge enriched ``raw_json`` (and core columns) into rows written in pass A."""
    n = len(enriched_scoped)
    step = max(1, n // 10) if n else 1
    for si, (raw, tenant_id_scope, tenant_name_scope) in enumerate(enriched_scoped):
        _raise_if_cancelled(cancel_check)
        if progress_notify and n and (si % step == 0 or si == n - 1):
            _progress_notify(
                progress_notify,
                "saving",
                86 + min(8, int(8 * si / max(n, 1))),
                f"Merging enrichment ({si + 1} of {n})…",
            )
        norm = normalize_inventory_row(raw)
        if not norm["source_device_uuid"]:
            continue
        uid = str(norm["source_device_uuid"])[:160]
        tid = (tenant_id_scope or "")[:160]
        tlabel = (tenant_name_scope or "")[:255]
        existing = db.execute(
            select(SyncedDevice).where(
                SyncedDevice.sdwan_instance_id == inst.id,
                SyncedDevice.source_device_uuid == uid,
                SyncedDevice.sdwan_tenant_id == tid,
            )
        ).scalar_one_or_none()
        if existing is None:
            continue
        raw_json = json.dumps(raw, separators=(",", ":"), default=str)
        new_r = str(norm["reachability"])
        old_r = existing.reachability
        if old_r != new_r:
            existing.state_changed_at_utc = now
        existing.hostname = str(norm["hostname"])[:255]
        existing.serial_number = str(norm["serial_number"])[:128]
        existing.model = str(norm["model"])[:128]
        existing.software_version = str(norm["software_version"])[:128]
        existing.device_type = str(norm["device_type"])[:64]
        existing.site_id = (str(norm["site_id"])[:64] if norm["site_id"] else None)
        existing.reachability = new_r[:32]
        existing.synced_at_utc = now
        existing.raw_json = raw_json
        existing.sdwan_tenant_name = tlabel


def sync_devices_for_instance(
    db: Session,
    secret_key: str,
    inst: SdWanManagerInstance,
    progress_notify: Callable[[str, int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[int, str | None]:
    """
    Upsert devices for one Manager instance. Returns (rows_touched, error_message).
    All timestamps written in UTC.

    ``progress_notify(phase, percent, message)`` is optional UI feedback (async sync jobs).
    ``cancel_check`` returns True when the operator requested cancellation (cooperative; checked between steps).
    """
    if inst.link_status != SdWanLinkStatus.connected.value:
        _progress_notify(progress_notify, "failed", 100, "Manager is not connected — run Verify first.")
        return 0, "instance not connected"

    now = _utcnow()
    rows_scoped: list[tuple[dict[str, Any], str, str]] = []
    tenant_phase_errors = False
    settings = get_settings()
    auth_mode = manager_credential_mode(secret_key, inst)
    try:
        inv_to = float(settings.sdwan_sync_inventory_timeout_seconds)
        _raise_if_cancelled(cancel_check)
        _progress_notify(progress_notify, "connecting", 6, "Opening HTTP session to SD-WAN Manager…")
        with open_manager_http_client(secret_key, inst) as client:
            _progress_notify(progress_notify, "connected", 14, "Session ready — downloading device inventory…")
            rows_scoped, tenant_phase_errors = _gather_inventory_with_tenant_scopes(
                client, inst.base_url, inventory_timeout=inv_to
            )
            _raise_if_cancelled(cancel_check)
            _progress_notify(
                progress_notify,
                "inventory",
                32,
                f"Inventory received ({len(rows_scoped)} row(s)) — reading Manager version…",
            )
            mv = read_manager_version(client, inst.base_url, request_timeout=inv_to)
            if mv:
                inst.manager_version = mv[:128]
    except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
        msg = str(e)[:500]
        inst.last_error = f"Inventory sync: {msg}"[:1000]
        db.add(inst)
        logger.warning(
            "SD-WAN device sync failed for instance %s (%s): %s",
            inst.id,
            inst.display_name,
            e,
        )
        _progress_notify(progress_notify, "failed", 100, msg)
        return 0, msg

    if not rows_scoped and tenant_phase_errors:
        msg = (
            "Multitenant inventory returned no devices after tenant switching "
            "(tenant switch or per-tenant /dataservice/device failed, XSRF rejected, or empty responses). "
            "Confirm the API token has Device read scope; for JWT, CSRF must be accepted after "
            "GET /dataservice/client/server."
        )[:500]
        inst.last_error = f"Inventory sync: {msg}"[:1000]
        db.add(inst)
        _progress_notify(progress_notify, "failed", 100, msg)
        return 0, msg

    enrich = (
        settings.sdwan_sync_enrich_device_details
        and len(rows_scoped) > 0
        and len(rows_scoped) <= settings.sdwan_sync_enrich_max_inventory_devices
    )

    if enrich:
        touched, seen = _upsert_devices_from_inventory(
            db, inst, rows_scoped, now, progress_notify, cancel_check, pct_lo=40, pct_hi=55
        )
        if not tenant_phase_errors:
            _raise_if_cancelled(cancel_check)
            _delete_stale_devices_for_instance(db, inst.id, seen)
        _raise_if_cancelled(cancel_check)
        inst.devices_last_sync_at_utc = now
        if inst.last_error and str(inst.last_error).startswith("Inventory sync:"):
            inst.last_error = None
        db.add(inst)
        _progress_notify(
            progress_notify,
            "saving",
            58,
            "WAN edge list saved — fetching per-device details…",
        )
        db.commit()

        _raise_if_cancelled(cancel_check)
        multitenant_inventory = any(str(tid or "").strip() for _, tid, _ in rows_scoped)
        max_w = 1
        if auth_mode == "jwt" and not multitenant_inventory:
            max_w = max(1, min(int(settings.sdwan_sync_enrich_concurrency), len(rows_scoped)))
        to = float(settings.sdwan_sync_enrich_request_timeout_seconds)
        rows_enriched = _enrich_rows_scoped_parallel(
            secret_key, inst, rows_scoped, to, max_w, progress_notify, cancel_check
        )
        _apply_enriched_raw_to_db(db, inst, rows_enriched, now, progress_notify, cancel_check)
        _raise_if_cancelled(cancel_check)
        _progress_notify(progress_notify, "finishing", 96, "Finalizing inventory…")
        db.add(inst)
        _progress_notify(progress_notify, "complete", 100, "Inventory sync complete.")
        return touched, None

    if rows_scoped:
        _progress_notify(
            progress_notify,
            "inventory",
            44,
            "Skipping per-device enrichment (disabled or large fleet).",
        )
        touched, seen = _upsert_devices_from_inventory(
            db, inst, rows_scoped, now, progress_notify, cancel_check, pct_lo=58, pct_hi=88
        )
        if not tenant_phase_errors:
            _raise_if_cancelled(cancel_check)
            _delete_stale_devices_for_instance(db, inst.id, seen)
        _raise_if_cancelled(cancel_check)
        _progress_notify(progress_notify, "finishing", 96, "Finalizing inventory…")
        inst.devices_last_sync_at_utc = now
        if inst.last_error and str(inst.last_error).startswith("Inventory sync:"):
            inst.last_error = None
        db.add(inst)
        _progress_notify(progress_notify, "complete", 100, "Inventory sync complete.")
        return touched, None

    touched = 0
    if not tenant_phase_errors:
        _raise_if_cancelled(cancel_check)
        _delete_stale_devices_for_instance(db, inst.id, set())
    _raise_if_cancelled(cancel_check)
    _progress_notify(progress_notify, "finishing", 96, "Finalizing inventory…")
    inst.devices_last_sync_at_utc = now
    if inst.last_error and str(inst.last_error).startswith("Inventory sync:"):
        inst.last_error = None
    db.add(inst)
    _progress_notify(progress_notify, "complete", 100, "Inventory sync complete.")
    return touched, None


def sync_cellular_history_best_effort(
    db: Session,
    secret_key: str,
    inst: SdWanManagerInstance,
) -> dict[str, Any]:
    """Pull EIOLTE history after inventory sync; returns summary stats, never raises."""
    empty: dict[str, Any] = {
        "devices_seen": 0,
        "devices_fetched": 0,
        "buckets_pushed": 0,
        "errors": 0,
    }
    try:
        from terra_sdwan.sdwan_cellular_history import sync_cellular_history_for_instance

        stats = sync_cellular_history_for_instance(db, secret_key, inst)
        if isinstance(stats, dict):
            return {**empty, **stats}
    except Exception:
        logger.exception("Cellular history sync failed instance_id=%s", inst.id)
        empty["errors"] = 1
    return empty


def _inventory_row_for_device(
    rows: list[dict[str, Any]],
    device: SyncedDevice,
) -> dict[str, Any] | None:
    uid = (device.source_device_uuid or "").strip()
    if not uid:
        return None
    for raw in rows:
        norm = normalize_inventory_row(raw)
        if str(norm.get("source_device_uuid") or "").strip() == uid:
            return raw
    return None


def _stored_inventory_row(device: SyncedDevice) -> dict[str, Any]:
    try:
        parsed = json.loads(device.raw_json)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _best_effort_switch_tenant(
    client: httpx.Client,
    base: str,
    tenant_id: str,
    *,
    request_timeout: float,
) -> bool:
    try:
        switch_tenant(client, base, tenant_id, request_timeout=request_timeout)
    except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
        logger.warning("SD-WAN tenant switch skipped for device sync (tenant=%s): %s", tenant_id, e)
        client.headers.pop("VSessionId", None)
        return False
    return True


def _best_effort_refresh_inventory_row(
    client: httpx.Client,
    base: str,
    device: SyncedDevice,
    *,
    request_timeout: float,
) -> dict[str, Any] | None:
    try:
        inv_rows = fetch_device_inventory(client, base, request_timeout=request_timeout)
    except (RuntimeError, httpx.RequestError, OSError) as e:
        logger.warning("SD-WAN inventory list unavailable during device sync: %s", e)
        return None
    return _inventory_row_for_device(inv_rows, device)


def sync_synced_device_detail(
    db: Session,
    secret_key: str,
    device: SyncedDevice,
    inst: SdWanManagerInstance,
    *,
    progress_notify: Callable[[str, int, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[bool, str | None]:
    """
    Refresh one ``SyncedDevice``: inventory row, interface/cellular enrich, DB persist, EIOLTE history.

    Returns ``(ok, error_message)``.
    """
    if inst.link_status != SdWanLinkStatus.connected.value:
        _progress_notify(progress_notify, "failed", 100, "Manager is not connected — run Verify first.")
        return False, "instance not connected"

    settings = get_settings()
    now = _utcnow()
    inv_to = float(settings.sdwan_sync_inventory_timeout_seconds)
    enrich_to = float(settings.sdwan_sync_enrich_request_timeout_seconds)
    tenant_id = (device.sdwan_tenant_id or "").strip()
    tenant_label = (device.sdwan_tenant_name or tenant_id or "").strip()
    cluster = (inst.display_name or inst.base_url or "Manager").strip()
    raw = _stored_inventory_row(device)

    try:
        _raise_if_cancelled(cancel_check)
        _progress_notify(progress_notify, "connecting", 8, f"Opening session to {cluster}…")
        with open_manager_http_client(secret_key, inst, log_tenant=tenant_label) as client:
            base = inst.base_url.rstrip("/")
            if tenant_id:
                _progress_notify(progress_notify, "inventory", 18, "Switching tenant context…")
                if not _best_effort_switch_tenant(client, base, tenant_id, request_timeout=inv_to):
                    _progress_notify(
                        progress_notify,
                        "inventory",
                        22,
                        "Tenant switch unavailable — continuing with provider-scoped token…",
                    )
            _raise_if_cancelled(cancel_check)
            _progress_notify(progress_notify, "inventory", 28, "Refreshing device inventory row…")
            refreshed = _best_effort_refresh_inventory_row(
                client, base, device, request_timeout=inv_to
            )
            if refreshed is not None:
                raw = refreshed
            elif not raw:
                msg = f"{cluster}: device inventory unavailable and no stored row in TERRA."
                _progress_notify(progress_notify, "failed", 100, msg)
                return False, msg
            elif refreshed is None:
                _progress_notify(
                    progress_notify,
                    "inventory",
                    32,
                    "Using stored inventory (Manager list unavailable)…",
                )
            _raise_if_cancelled(cancel_check)
            _progress_notify(
                progress_notify,
                "enriching",
                48,
                "Fetching interfaces, cellular, and WAN dataservice rows…",
            )
            enriched = enrich_inventory_row_for_sync(
                client,
                base,
                raw,
                request_timeout=enrich_to,
                verify_tls=inst.verify_tls,
            )
    except SdWanSyncCancelled:
        _progress_notify(progress_notify, "cancelled", 0, "Cancelled.")
        return False, "cancelled"
    except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
        msg = f"{cluster}: {e!s}"[:500]
        _progress_notify(progress_notify, "failed", 100, msg)
        return False, msg

    _raise_if_cancelled(cancel_check)
    _progress_notify(progress_notify, "saving", 72, "Saving enriched inventory to TERRA…")
    norm = normalize_inventory_row(enriched)
    new_r = str(norm["reachability"])
    old_r = device.reachability
    if old_r != new_r:
        device.state_changed_at_utc = now
    device.hostname = str(norm["hostname"])[:255]
    device.serial_number = str(norm["serial_number"])[:128]
    device.model = str(norm["model"])[:128]
    device.software_version = str(norm["software_version"])[:128]
    device.device_type = str(norm["device_type"])[:64]
    device.site_id = (str(norm["site_id"])[:64] if norm["site_id"] else None)
    device.reachability = new_r[:32]
    device.synced_at_utc = now
    device.raw_json = json.dumps(enriched, separators=(",", ":"), default=str)
    if tenant_label and not (device.sdwan_tenant_name or "").strip():
        device.sdwan_tenant_name = tenant_label[:255]
    db.add(device)

    _raise_if_cancelled(cancel_check)
    _progress_notify(progress_notify, "cellular", 88, "Refreshing cellular RF history…")
    try:
        from terra_sdwan.sdwan_cellular_history import sync_cellular_history_for_device

        sync_cellular_history_for_device(db, secret_key, inst, device)
    except Exception:
        logger.exception("Per-device cellular history failed device_id=%s", device.id)

    _progress_notify(progress_notify, "done", 100, "Device sync complete.")
    return True, None


def _cellular_detail_suffix(stats: dict[str, Any] | None) -> str:
    if not stats:
        return ""
    buckets = int(stats.get("buckets_pushed") or 0)
    errors = int(stats.get("errors") or 0)
    fetched = int(stats.get("devices_fetched") or 0)
    if buckets == 0 and errors == 0 and fetched == 0:
        return ""
    return f" cellular_buckets={buckets} cellular_errors={errors} cellular_fetched={fetched}"


def _cluster_labels_for_batch(instance_ids: list[int]) -> str:
    """Comma-separated manager display names for batch log messages."""
    if not instance_ids:
        return ""
    from terra.db import get_session_factory

    sf = get_session_factory()
    labels: list[str] = []
    with sf() as db:
        for iid in instance_ids:
            inst = db.get(SdWanManagerInstance, iid)
            if inst is None:
                labels.append(f"id:{iid}")
            else:
                labels.append((inst.display_name or "").strip() or f"id:{iid}")
    return ", ".join(labels)


def _manager_batch_log_message(res: dict[str, Any], batch_kind: str, *, outcome: str) -> str:
    cluster = str(res.get("cluster") or "(unknown)")
    rows = int(res.get("rows") or 0)
    duration_ms = int(res.get("duration_ms") or 0)
    cellular = res.get("cellular_stats") or {}
    buckets = int(cellular.get("buckets_pushed") or 0)
    base = f'{outcome}: "{cluster}" — {rows} rows in {duration_ms}ms ({batch_kind})'
    if buckets > 0:
        return f"{base}, cellular_buckets={buckets}"
    return base


def _emit_batch_log(
    level: str,
    message: str,
    *,
    detail: str,
    batch_kind: str,
) -> None:
    append_event(level, "sdwan_sync_batch", message, detail=detail)
    if batch_kind == "periodic":
        try:
            from terra.collector_status import persist_log_event

            persist_log_event(
                level,
                "sdwan_sync_batch",
                message,
                detail=detail,
                source="collector",
                batch_kind=batch_kind,
            )
        except Exception:
            logger.debug("persist batch log skipped", exc_info=True)


def _sync_one_manager_worker(secret_key: str, instance_id: int) -> dict[str, Any]:
    """Sync one Manager in an isolated DB session (for concurrent batch workers)."""
    from terra.db import get_session_factory

    t0 = time.perf_counter()
    out: dict[str, Any] = {
        "instance_id": instance_id,
        "cluster": "(unknown)",
        "rows": 0,
        "error": None,
        "crashed": False,
    }
    sf = get_session_factory()
    try:
        with sf() as db:
            inst = db.get(SdWanManagerInstance, instance_id)
            if inst is None:
                out["cluster"] = "(missing)"
                out["error"] = "instance not found"
                return out
            out["cluster"] = (inst.display_name or "").strip() or f"id:{instance_id}"
            if inst.link_status != SdWanLinkStatus.connected.value:
                out["error"] = "not connected"
                return out
            from terra_sdwan.sdwan_sync_instance_gate import (
                release_batch_instance_sync,
                try_batch_instance_sync,
            )

            if not try_batch_instance_sync(instance_id):
                out["error"] = "skipped (operator sync in progress)"
                out["skipped"] = True
                return out
            try:
                n, err = sync_devices_for_instance(db, secret_key, inst)
                cellular_stats: dict[str, Any] | None = None
                if err is None:
                    db.commit()
                    db.refresh(inst)
                    cellular_stats = sync_cellular_history_best_effort(db, secret_key, inst)
                    out["cellular_stats"] = cellular_stats
                db.commit()
            except Exception:
                logger.exception(
                    "SD-WAN batch worker crashed instance_id=%s",
                    instance_id,
                )
                db.rollback()
                out["crashed"] = True
                out["error"] = "worker crashed"
                return out
            finally:
                release_batch_instance_sync(instance_id)
            out["rows"] = max(int(n), 0)
            out["error"] = err
    except Exception:
        logger.exception("SD-WAN batch worker session error instance_id=%s", instance_id)
        out["crashed"] = True
        out["error"] = "session error"
    finally:
        out["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def _execute_sdwan_manager_sync_batch(
    secret_key: str,
    sorted_instance_ids: list[int],
    *,
    run_id: str,
    batch_kind: str,
) -> list[dict[str, Any]]:
    """
    Run inventory sync for each instance id with bounded concurrency.

    ``batch_kind`` is ``periodic`` (background loop) or ``user_bulk`` (POST all managers); log text only.

    Emits ``append_event`` (``sdwan_sync_batch``) and structured ``logger`` lines per instance and batch.
    """
    settings = get_settings()
    n_m = len(sorted_instance_ids)
    max_w = max(1, min(int(settings.sdwan_batch_max_concurrent_managers), n_m or 1))
    if sdwan_batch_needs_serial_execution():
        max_w = 1
    label = "Periodic" if batch_kind == "periodic" else "User bulk"
    t_batch = time.perf_counter()
    cluster_labels = _cluster_labels_for_batch(sorted_instance_ids)

    if batch_kind == "periodic":
        try:
            from terra.collector_status import record_batch_start

            record_batch_start(
                run_id=run_id,
                batch_kind=batch_kind,
                managers=n_m,
                max_concurrent=max_w,
            )
        except Exception:
            logger.debug("record_batch_start skipped", exc_info=True)

    start_detail = f"run_id={run_id} managers={n_m} max_concurrent={max_w} batch_kind={batch_kind}"
    if cluster_labels:
        start_detail += f' clusters="{cluster_labels}"'
    start_msg = f"{label} SD-WAN sync batch started ({n_m} manager(s))"
    if cluster_labels:
        start_msg = f'{label} SD-WAN sync batch started ({n_m} manager(s): {cluster_labels})'
    _emit_batch_log(
        "INFO",
        start_msg,
        detail=start_detail,
        batch_kind=batch_kind,
    )
    logger.info(
        "%s SD-WAN sync batch started run_id=%s managers=%s max_concurrent=%s kind=%s",
        label,
        run_id,
        n_m,
        max_w,
        batch_kind,
        extra={
            "terra_sdwan_run_id": run_id,
            "terra_sdwan_managers": n_m,
            "terra_sdwan_max_concurrent": max_w,
            "terra_sdwan_batch_kind": batch_kind,
            "terra_sdwan_phase": "batch_start",
        },
    )

    results: list[dict[str, Any]] = []
    if not sorted_instance_ids:
        wall_ms = 0
        _emit_batch_log(
            "INFO",
            f"{label} SD-WAN sync batch completed (0 managers)",
            detail=f"run_id={run_id} wall_ms={wall_ms} ok=0 warn=0 err=0 rows=0",
            batch_kind=batch_kind,
        )
        if batch_kind == "periodic":
            try:
                from terra.collector_status import record_batch_finish

                record_batch_finish(
                    run_id=run_id,
                    batch_kind=batch_kind,
                    managers=0,
                    ok=0,
                    warn=0,
                    err=0,
                    rows=0,
                    wall_ms=wall_ms,
                    cellular_buckets=0,
                    cellular_errors=0,
                )
            except Exception:
                logger.debug("record_batch_finish skipped", exc_info=True)
        logger.info(
            "%s SD-WAN sync batch completed run_id=%s managers=0 wall_ms=0",
            label,
            run_id,
            extra={"terra_sdwan_run_id": run_id, "terra_sdwan_phase": "batch_end", "terra_sdwan_wall_ms": 0},
        )
        return results

    with ThreadPoolExecutor(max_workers=max_w, thread_name_prefix="terra-sdwan-batch") as pool:
        future_map = {pool.submit(_sync_one_manager_worker, secret_key, iid): iid for iid in sorted_instance_ids}
        for fut in as_completed(future_map):
            iid = future_map[fut]
            try:
                res = fut.result()
            except Exception:
                logger.exception("SD-WAN batch future failed instance_id=%s", iid)
                res = {
                    "instance_id": iid,
                    "cluster": "(unknown)",
                    "rows": 0,
                    "error": "future failed",
                    "crashed": True,
                    "duration_ms": 0,
                }
            results.append(res)
            det = (
                f'run_id={run_id} instance_id={res["instance_id"]} cluster="{res["cluster"]}" '
                f'duration_ms={res["duration_ms"]} rows={res["rows"]}'
            )
            if res.get("error"):
                det += f' error={str(res["error"])[:400]}'
            det += _cellular_detail_suffix(res.get("cellular_stats"))
            if res.get("crashed"):
                _emit_batch_log(
                    "ERROR",
                    _manager_batch_log_message(res, batch_kind, outcome="Manager sync failed"),
                    detail=det[:4000],
                    batch_kind=batch_kind,
                )
                logger.error(
                    (
                        "SD-WAN batch instance done run_id=%s instance_id=%s cluster=%r "
                        "duration_ms=%s rows=%s crashed=1"
                    ),
                    run_id,
                    res["instance_id"],
                    res["cluster"],
                    res["duration_ms"],
                    res["rows"],
                    extra={
                        "terra_sdwan_run_id": run_id,
                        "terra_sdwan_phase": "instance_done",
                        "terra_sdwan_instance_id": res["instance_id"],
                        "terra_sdwan_duration_ms": res["duration_ms"],
                        "terra_sdwan_rows": res["rows"],
                        "terra_sdwan_crashed": True,
                    },
                )
            elif res.get("error"):
                _emit_batch_log(
                    "WARNING",
                    _manager_batch_log_message(res, batch_kind, outcome="Manager sync error"),
                    detail=det[:4000],
                    batch_kind=batch_kind,
                )
                logger.warning(
                    "SD-WAN batch instance done run_id=%s instance_id=%s cluster=%r duration_ms=%s rows=%s err=%s",
                    run_id,
                    res["instance_id"],
                    res["cluster"],
                    res["duration_ms"],
                    res["rows"],
                    res["error"],
                    extra={
                        "terra_sdwan_run_id": run_id,
                        "terra_sdwan_phase": "instance_done",
                        "terra_sdwan_instance_id": res["instance_id"],
                        "terra_sdwan_duration_ms": res["duration_ms"],
                        "terra_sdwan_rows": res["rows"],
                        "terra_sdwan_error": str(res["error"])[:500],
                    },
                )
            else:
                _emit_batch_log(
                    "INFO",
                    _manager_batch_log_message(res, batch_kind, outcome="Manager sync ok"),
                    detail=det[:4000],
                    batch_kind=batch_kind,
                )
                logger.info(
                    "SD-WAN batch instance done run_id=%s instance_id=%s cluster=%r duration_ms=%s rows=%s",
                    run_id,
                    res["instance_id"],
                    res["cluster"],
                    res["duration_ms"],
                    res["rows"],
                    extra={
                        "terra_sdwan_run_id": run_id,
                        "terra_sdwan_phase": "instance_done",
                        "terra_sdwan_instance_id": res["instance_id"],
                        "terra_sdwan_duration_ms": res["duration_ms"],
                        "terra_sdwan_rows": res["rows"],
                    },
                )

    wall_ms = int((time.perf_counter() - t_batch) * 1000)
    ok_n = sum(1 for r in results if not r.get("error") and not r.get("crashed"))
    warn_n = sum(1 for r in results if r.get("error") and not r.get("crashed"))
    err_n = sum(1 for r in results if r.get("crashed"))
    total_rows = sum(int(r.get("rows") or 0) for r in results)
    total_cellular_buckets = sum(
        int((r.get("cellular_stats") or {}).get("buckets_pushed") or 0) for r in results
    )
    total_cellular_errors = sum(int((r.get("cellular_stats") or {}).get("errors") or 0) for r in results)
    end_detail = (
        f"run_id={run_id} wall_ms={wall_ms} ok={ok_n} warn={warn_n} err={err_n} rows={total_rows} "
        f"max_concurrent={max_w} cellular_buckets={total_cellular_buckets} "
        f"cellular_errors={total_cellular_errors}"
    )[:4000]
    end_msg = (
        f"{label} SD-WAN sync batch completed ({n_m} manager(s)) — "
        f"ok={ok_n} warn={warn_n} err={err_n} rows={total_rows} in {wall_ms}ms"
    )
    if total_cellular_buckets > 0 or total_cellular_errors > 0:
        end_msg += f", cellular_buckets={total_cellular_buckets} cellular_errors={total_cellular_errors}"
    _emit_batch_log(
        "INFO",
        end_msg,
        detail=end_detail,
        batch_kind=batch_kind,
    )
    if batch_kind == "periodic":
        try:
            from terra.collector_status import record_batch_finish

            record_batch_finish(
                run_id=run_id,
                batch_kind=batch_kind,
                managers=n_m,
                ok=ok_n,
                warn=warn_n,
                err=err_n,
                rows=total_rows,
                wall_ms=wall_ms,
                cellular_buckets=total_cellular_buckets,
                cellular_errors=total_cellular_errors,
            )
        except Exception:
            logger.debug("record_batch_finish skipped", exc_info=True)
    logger.info(
        "%s SD-WAN sync batch completed run_id=%s managers=%s wall_ms=%s ok=%s warn=%s err=%s rows=%s",
        label,
        run_id,
        n_m,
        wall_ms,
        ok_n,
        warn_n,
        err_n,
        total_rows,
        extra={
            "terra_sdwan_run_id": run_id,
            "terra_sdwan_phase": "batch_end",
            "terra_sdwan_wall_ms": wall_ms,
            "terra_sdwan_ok": ok_n,
            "terra_sdwan_warn": warn_n,
            "terra_sdwan_err": err_n,
            "terra_sdwan_rows": total_rows,
            "terra_sdwan_managers": n_m,
        },
    )
    try:
        from terra.telemetry_vm import push_sdwan_sync_batch_telemetry

        push_sdwan_sync_batch_telemetry(results=results, batch_kind=batch_kind, _run_id=run_id)
    except Exception:
        logger.debug("VictoriaMetrics telemetry push skipped", exc_info=True)
    return results


def sync_user_sdwan_devices(db: Session, secret_key: str, user_id: int) -> dict[str, int]:
    """Sync inventory for all connected managers owned by one user (bounded concurrency; isolated sessions)."""
    run_id = secrets.token_hex(4)
    pairs = list(
        db.execute(
            select(SdWanManagerInstance.id, SdWanManagerInstance.devices_last_sync_at_utc).where(
                SdWanManagerInstance.user_id == user_id,
                SdWanManagerInstance.link_status == SdWanLinkStatus.connected.value,
            )
        ).all()
    )
    sorted_ids = [
        r.id
        for r in sorted(
            pairs,
            key=lambda row: _inventory_stale_sort_key(row.devices_last_sync_at_utc),
        )
    ]
    results = _execute_sdwan_manager_sync_batch(secret_key, sorted_ids, run_id=run_id, batch_kind="user_bulk")
    rows = sum(int(r.get("rows") or 0) for r in results)
    errors = sum(1 for r in results if r.get("error") or r.get("crashed"))
    return {"managers": len(sorted_ids), "rows_touched": rows, "errors": errors}


def sync_all_connected_managers(secret_key: str) -> None:
    """Background batch: sync every Manager row marked connected (all users), fair order, bounded concurrency."""
    from terra.db import get_session_factory

    run_id = secrets.token_hex(4)
    sf = get_session_factory()
    with sf() as db:
        rows = list(
            db.execute(
                select(SdWanManagerInstance.id, SdWanManagerInstance.devices_last_sync_at_utc).where(
                    SdWanManagerInstance.link_status == SdWanLinkStatus.connected.value,
                ),
            ).all()
        )
    sorted_ids = [
        r.id
        for r in sorted(
            rows,
            key=lambda row: _inventory_stale_sort_key(row.devices_last_sync_at_utc),
        )
    ]
    _execute_sdwan_manager_sync_batch(secret_key, sorted_ids, run_id=run_id, batch_kind="periodic")
