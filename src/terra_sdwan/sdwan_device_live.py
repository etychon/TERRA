"""Live Cisco Catalyst SD-WAN Manager dataservice reads for a single device (interfaces, cellular, WAN)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from terra.inventory_extract import _pick, _row_from_interface_dict
from terra_sdwan.sdwan_dataservice_rows import rows_from_dataservice_body

logger = logging.getLogger(__name__)

LiveProgressFn = Callable[[dict[str, Any]], None]

_LIVE_STEP_RESOLVE = ("resolve_id", "Resolve device identifier")
_LIVE_STEP_INTERFACES = ("interfaces", "Network interfaces")

# vManage uses `deviceId` (typically system IP, sometimes UUID) on per-device dataservice URLs.
_DEVICE_ID_SOURCE_KEYS: tuple[str, ...] = (
    "system-ip",
    "systemIp",
    "deviceIp",
    "local-system-ip",
    "uuid",
    "deviceId",
)

_INTERFACE_PATHS: tuple[str, ...] = (
    "dataservice/device/interface",
    "dataservice/device/interface/synced",
)

_CELLULAR_PATHS: tuple[tuple[str, str], ...] = (
    ("Cellular modem", "dataservice/device/cellular/modem"),
    ("Cellular network", "dataservice/device/cellular/network"),
    ("Cellular radio", "dataservice/device/cellular/radio"),
    ("Cellular status", "dataservice/device/cellular/status"),
    ("Cellular sessions", "dataservice/device/cellular/sessions"),
    ("Cellular profiles", "dataservice/device/cellular/profiles"),
)

_EXTRA_PATHS: tuple[tuple[str, str], ...] = (
    ("WAN (control)", "dataservice/device/control/waninterface"),
)


def vmanage_device_id_candidates(inventory: dict[str, Any]) -> list[str]:
    """Ordered unique values to try as ``deviceId`` query parameter."""
    out: list[str] = []
    seen: set[str] = set()
    for k in _DEVICE_ID_SOURCE_KEYS:
        v = inventory.get(k)
        if isinstance(v, str):
            s = v.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            s = str(v).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _http_get_json(
    client: httpx.Client,
    base: str,
    path: str,
    params: dict[str, str],
    *,
    timeout: float = 45.0,
) -> Any | None:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = client.get(url, params=params, headers={"Accept": "application/json"}, timeout=timeout)
    except httpx.RequestError as e:
        logger.debug("SD-WAN live GET %s failed: %s", path, e)
        return None
    if r.status_code >= 400:
        logger.debug("SD-WAN live GET %s HTTP %s", path, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _rows_from_get(
    client: httpx.Client,
    base: str,
    path: str,
    device_id: str,
    *,
    timeout: float = 45.0,
) -> list[dict[str, Any]]:
    body = _http_get_json(client, base, path, {"deviceId": device_id}, timeout=timeout)
    if body is None:
        return []
    return rows_from_dataservice_body(body)


async def _async_rows_from_get(
    client: httpx.AsyncClient,
    base: str,
    path: str,
    device_id: str,
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = await client.get(
            url,
            params={"deviceId": device_id},
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except httpx.RequestError:
        return []
    if r.status_code >= 400:
        return []
    try:
        body = r.json()
    except ValueError:
        return []
    return rows_from_dataservice_body(body)


async def _parallel_cellular_wan_snapshots(
    base_url: str,
    header_map: dict[str, str],
    cookies: httpx.Cookies,
    verify_tls: bool | str,
    dev_id: str,
    request_timeout: float,
) -> dict[str, Any]:
    """Fetch cellular + WAN dataservice slices concurrently (sync inventory enrich)."""
    cellular_snapshots: dict[str, Any] = {}
    base = base_url.rstrip("/")
    paths: list[tuple[str, str]] = [(t, p) for t, p in _CELLULAR_PATHS[:4]] + [(t, p) for t, p in _EXTRA_PATHS]
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
    async with httpx.AsyncClient(
        verify=verify_tls,
        follow_redirects=True,
        headers=header_map,
        cookies=cookies,
        limits=limits,
        timeout=request_timeout,
    ) as ac:

        async def fetch_one(title: str, path: str) -> tuple[str, str, list[dict[str, Any]]]:
            rows = await _async_rows_from_get(ac, base, path, dev_id, timeout=request_timeout)
            return title, path, [x for x in rows if isinstance(x, dict)]

        parts = await asyncio.gather(*[fetch_one(t, p) for t, p in paths])
        for _title, path, chunk in parts:
            if not chunk:
                continue
            if path in {p for _t, p in _CELLULAR_PATHS[:4]}:
                key = f"cellular_sync_{path.replace('dataservice/', '').replace('/', '_')}"
            else:
                key = f"wan_sync_{path.replace('dataservice/', '').replace('/', '_')}"
            cellular_snapshots[key] = chunk[:120]
    return cellular_snapshots


def interface_row_from_live_api_dict(d: dict[str, Any]) -> dict[str, str]:
    """Map a /dataservice/device/interface* row to the device detail table shape."""
    row = _row_from_interface_dict(d)
    extras: list[str] = []
    mac = _pick(d, "hwaddr", "mac-address", "macAddress", "macaddr")
    if mac:
        extras.append(f"MAC {mac}")
    for label, keys in (
        ("vDevice", ("vdevice-name", "vdeviceName")),
        ("last updated", ("lastupdated", "last-updated", "lastUpdated")),
    ):
        v = _pick(d, *keys)
        if v:
            extras.append(f"{label} {v}")
    for metric_key in (
        "rx-kbps",
        "tx-kbps",
        "rx-pps",
        "tx-pps",
        "rx-drops",
        "tx-drops",
        "ipv6-addrs",
        "ipv6-address",
    ):
        v = _pick(d, metric_key)
        if v:
            extras.append(f"{metric_key} {v}")
    if extras:
        row["detail"] = (row["detail"] + " · " if row["detail"] else "") + " · ".join(extras[:12])
    return row


def _dedupe_interface_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for r in rows:
        key = (r.get("interface", ""), r.get("ip", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:500]


def _table_from_dict_rows(
    rows: list[dict[str, Any]],
    *,
    max_rows: int = 80,
    max_cols: int = 16,
) -> dict[str, Any] | None:
    if not rows:
        return None
    columns: list[str] = []
    for r in rows[:max_rows]:
        if not isinstance(r, dict):
            continue
        for k in r:
            if isinstance(k, str) and k not in columns:
                columns.append(k)
                if len(columns) >= max_cols:
                    break
    data: list[list[str]] = []
    for r in rows[:max_rows]:
        if not isinstance(r, dict):
            continue
        line: list[str] = []
        for c in columns:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                try:
                    line.append(json.dumps(v, default=str)[:320])
                except TypeError:
                    line.append(str(v)[:320])
            else:
                line.append("" if v is None else str(v)[:400])
        data.append(line)
    return {"columns": columns, "rows": data}


def _live_step_id(title: str, path: str) -> str:
    slug = path.replace("dataservice/", "").replace("/", "_")
    return f"cellular_{slug}" if "cellular" in path else f"wan_{slug}"


def _emit_live_step(
    progress: LiveProgressFn | None,
    *,
    step_id: str,
    label: str,
    status: str,
    elapsed_ms: float = 0.0,
    detail: str | None = None,
) -> None:
    if progress is None:
        return
    payload: dict[str, Any] = {
        "type": "step",
        "step_id": step_id,
        "label": label,
        "status": status,
        "elapsed_ms": round(max(0.0, elapsed_ms), 1),
    }
    if detail:
        payload["detail"] = detail
    progress(payload)


def _step_timer() -> tuple[float, Callable[[], float]]:
    start = time.perf_counter()

    def elapsed_ms() -> float:
        return (time.perf_counter() - start) * 1000.0

    return start, elapsed_ms


def fetch_live_device_dashboard(
    client: httpx.Client,
    base_url: str,
    inventory: dict[str, Any],
    *,
    request_timeout: float = 45.0,
    progress: LiveProgressFn | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], str | None]:
    """
    Pull interfaces and cellular/WAN tables from Manager for the device inventory row.

    Returns ``(interface_rows, cellular_sections, note)`` where ``note`` is a short UX string
    (success, partial, or skip reason). Empty lists mean fall back to cached inventory JSON in the UI.
    """
    candidates = vmanage_device_id_candidates(inventory)
    _emit_live_step(
        progress,
        step_id=_LIVE_STEP_RESOLVE[0],
        label=_LIVE_STEP_RESOLVE[1],
        status="running",
    )
    if not candidates:
        _emit_live_step(
            progress,
            step_id=_LIVE_STEP_RESOLVE[0],
            label=_LIVE_STEP_RESOLVE[1],
            status="done",
            detail="No device identifier in inventory JSON",
        )
        return [], [], "Live Manager APIs need a device identifier (system-ip or uuid) in inventory JSON."
    resolve_detail = ", ".join(candidates[:3])
    if len(candidates) > 3:
        resolve_detail += f" (+{len(candidates) - 3} more)"
    _emit_live_step(
        progress,
        step_id=_LIVE_STEP_RESOLVE[0],
        label=_LIVE_STEP_RESOLVE[1],
        status="done",
        detail=resolve_detail,
    )

    interface_rows: list[dict[str, str]] = []
    used_id: str | None = None
    _emit_live_step(
        progress,
        step_id=_LIVE_STEP_INTERFACES[0],
        label=_LIVE_STEP_INTERFACES[1],
        status="running",
    )
    _, _iface_elapsed = _step_timer()
    for dev_id in candidates:
        for path in _INTERFACE_PATHS:
            raw_rows = _rows_from_get(client, base_url, path, dev_id, timeout=request_timeout)
            if not raw_rows:
                continue
            for item in raw_rows:
                if isinstance(item, dict):
                    interface_rows.append(interface_row_from_live_api_dict(item))
            interface_rows = _dedupe_interface_rows(interface_rows)
            if interface_rows:
                used_id = dev_id
                break
        if interface_rows:
            break
    if interface_rows:
        iface_detail = f"{len(interface_rows)} interface(s)"
        if used_id:
            iface_detail += f" · deviceId {used_id}"
    else:
        iface_detail = "No rows from interface endpoints"
    _emit_live_step(
        progress,
        step_id=_LIVE_STEP_INTERFACES[0],
        label=_LIVE_STEP_INTERFACES[1],
        status="done",
        elapsed_ms=_iface_elapsed(),
        detail=iface_detail,
    )

    sections: list[dict[str, Any]] = []
    if used_id is None:
        used_id = candidates[0]

    for title, path in _CELLULAR_PATHS + _EXTRA_PATHS:
        step_id = _live_step_id(title, path)
        _emit_live_step(progress, step_id=step_id, label=title, status="running")
        _, step_elapsed = _step_timer()
        raw_rows = _rows_from_get(client, base_url, path, used_id, timeout=request_timeout)
        tbl = _table_from_dict_rows(raw_rows)
        if tbl:
            sections.append({"title": title, **tbl})
            row_count = len(tbl.get("rows") or [])
            detail = f"{row_count} row(s)"
        else:
            detail = "No rows"
        _emit_live_step(
            progress,
            step_id=step_id,
            label=title,
            status="done",
            elapsed_ms=step_elapsed(),
            detail=detail,
        )

    if interface_rows and sections:
        note = "Interfaces and tables loaded live from SD-WAN Manager."
    elif interface_rows:
        note = (
            "Interfaces loaded live from SD-WAN Manager; cellular/WAN endpoints returned no rows for this device."
        )
    elif sections:
        note = (
            "Live cellular/WAN data from Manager; interface endpoints returned no rows "
            "(try sync or check deviceId)."
        )
    else:
        note = (
            "Live Manager per-device APIs returned no data for this device (unreachable edge, "
            "unsupported personality, or deviceId mismatch). Showing inventory JSON only."
        )

    return interface_rows, sections, note


def enrich_inventory_row_for_sync(
    client: httpx.Client,
    base_url: str,
    row: dict[str, Any],
    *,
    request_timeout: float = 4.0,
    verify_tls: bool | str | None = None,
) -> dict[str, Any]:
    """
    Merge per-device dataservice rows into the inventory dict before persisting ``raw_json``.

    Bounded: a few GETs with short timeouts so background sync stays predictable.
    Cellular/WAN dataservice slices after ``deviceId`` is known are fetched concurrently (async).
    """
    _verify: bool | str = True if verify_tls is None else verify_tls
    out = dict(row)
    candidates = vmanage_device_id_candidates(out)
    if not candidates:
        return out

    used_id: str | None = None
    iface_raw: list[dict[str, Any]] = []
    for dev_id in candidates:
        for path in _INTERFACE_PATHS:
            chunk = _rows_from_get(client, base_url, path, dev_id, timeout=request_timeout)
            if chunk:
                iface_raw = [x for x in chunk if isinstance(x, dict)]
                used_id = dev_id
                break
        if iface_raw:
            break

    if iface_raw:
        out["deviceInterface"] = iface_raw[:500]

    dev = used_id or candidates[0]
    cellular_snapshots: dict[str, Any] = {}
    header_map = dict(client.headers)
    try:
        cellular_snapshots = asyncio.run(
            _parallel_cellular_wan_snapshots(
                base_url,
                header_map,
                client.cookies,
                _verify,
                dev,
                request_timeout,
            ),
        )
    except (RuntimeError, OSError, httpx.RequestError, ValueError, TypeError):
        logger.debug("SD-WAN parallel cellular/WAN enrich failed; falling back to sequential GETs", exc_info=True)
        for _title, path in _CELLULAR_PATHS[:4]:
            chunk = _rows_from_get(client, base_url, path, dev, timeout=request_timeout)
            if chunk:
                key = f"cellular_sync_{path.replace('dataservice/', '').replace('/', '_')}"
                cellular_snapshots[key] = chunk[:120]
        for _title, path in _EXTRA_PATHS:
            chunk = _rows_from_get(client, base_url, path, dev, timeout=request_timeout)
            if chunk:
                key = f"wan_sync_{path.replace('dataservice/', '').replace('/', '_')}"
                cellular_snapshots[key] = chunk[:120]

    if cellular_snapshots:
        nest = out.get("terraEnrichedFromSync")
        if not isinstance(nest, dict):
            nest = {}
        nest["cellular_dataservice"] = cellular_snapshots
        out["terraEnrichedFromSync"] = nest

    return out
