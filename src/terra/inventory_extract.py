"""Parse SD-WAN Manager device inventory JSON: serials, geo, interfaces, cellular."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

_LAT_KEYS = frozenset(
    {
        "latitude",
        "lat",
        "geoLatitude",
        "siteLatitude",
    },
)
_LNG_KEYS = frozenset(
    {
        "longitude",
        "lng",
        "lon",
        "geoLongitude",
        "siteLongitude",
    },
)


def utc_iso_for_json(dt: datetime) -> str:
    """RFC 3339 instant with Z suffix so browsers parse as UTC reliably."""
    dt_utc = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _try_float(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _scalar_to_str(v: Any) -> str:
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        if float(v).is_integer():
            return str(int(v))
        return str(v).strip()
    return ""


def deep_find_serial(obj: Any, *, depth: int = 0, max_depth: int = 5) -> str:
    """Find a plausible hardware serial when top-level keys omit serialNumber."""
    if depth > max_depth:
        return ""
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if "serial" in lk and not isinstance(v, (dict, list)):
                s = _scalar_to_str(v)
                if s and len(s) >= 3 and not lk.endswith("session"):
                    return s[:128]
        for v in obj.values():
            s = deep_find_serial(v, depth=depth + 1, max_depth=max_depth)
            if s:
                return s
    elif isinstance(obj, list):
        for x in obj[:40]:
            s = deep_find_serial(x, depth=depth + 1, max_depth=max_depth)
            if s:
                return s
    return ""


def _parse_lat_lng_pair(obj: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = lng = None
    for lk in _LAT_KEYS:
        if lk not in obj:
            continue
        lat = _try_float(obj[lk])
        if lat is not None:
            break
    for lk in _LNG_KEYS:
        if lk not in obj:
            continue
        lng = _try_float(obj[lk])
        if lng is not None:
            break
    if lat is None or lng is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def extract_geo_lat_lng(obj: Any, *, depth: int = 0, max_depth: int = 7) -> tuple[float | None, float | None]:
    """Return first plausible WGS84 lat/lng pair found in nested JSON."""
    if depth > max_depth:
        return None, None
    if isinstance(obj, dict):
        lat, lng = _parse_lat_lng_pair(obj)
        if lat is not None and lng is not None:
            return lat, lng
        nest = obj.get("geoLocation") or obj.get("geolocation") or obj.get("geo")
        if isinstance(nest, dict):
            lat, lng = _parse_lat_lng_pair(nest)
            if lat is not None and lng is not None:
                return lat, lng
        for v in obj.values():
            a, b = extract_geo_lat_lng(v, depth=depth + 1, max_depth=max_depth)
            if a is not None and b is not None:
                return a, b
    elif isinstance(obj, list):
        for x in obj[:60]:
            a, b = extract_geo_lat_lng(x, depth=depth + 1, max_depth=max_depth)
            if a is not None and b is not None:
                return a, b
    return None, None


def _pick(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        if k in d:
            s = _scalar_to_str(d.get(k))
            if s:
                return s
    return ""


_IFACE_LIST_KEYS = (
    "deviceInterface",
    "interfaces",
    "ipInterfaces",
    "interfaceList",
    "vpnInterface",
)


def _row_from_interface_dict(d: dict[str, Any]) -> dict[str, str]:
    name = _pick(
        d,
        "ifname",
        "interfaceName",
        "intf-name",
        "intfName",
        "name",
        "interface-name",
    )
    ip_val = _pick(
        d,
        "ip-address",
        "ipAddress",
        "ipv4-address",
        "ipv4Address",
        "address",
        "ip",
    )
    vrf = _pick(d, "vrfName", "vrf-name", "vrf", "vpn-id", "vpnId")
    admin = _pick(d, "admin-state", "adminState", "if-admin-status", "admin-v26")
    oper = _pick(d, "oper-state", "operState", "operation-state", "line-protocol")
    mtu = _pick(d, "mtu", "if-mtu")
    out = {"interface": name or "—", "ip": ip_val or "—", "vrf": vrf or "—"}
    detail_parts = []
    if admin:
        detail_parts.append(f"admin {admin}")
    if oper:
        detail_parts.append(f"oper {oper}")
    if mtu:
        detail_parts.append(f"MTU {mtu}")
    out["detail"] = ", ".join(detail_parts) if detail_parts else ""
    return out


def extract_interface_rows(parsed: dict[str, Any]) -> list[dict[str, str]]:
    """Summarize interfaces from common SD-WAN / vManage device payload shapes."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_row(r: dict[str, str]) -> None:
        key = (r["interface"], r.get("ip", ""))
        if key in seen:
            return
        seen.add(key)
        rows.append(r)

    for lk in _IFACE_LIST_KEYS:
        raw = parsed.get(lk)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    add_row(_row_from_interface_dict(item))

    for k, v in parsed.items():
        lk = str(k).lower()
        if lk.endswith("interface") and isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    add_row(_row_from_interface_dict(item))

    return rows[:500]


_CELL_HINT = re.compile(
    r"(cellular|lte|modem|radio|sim|wan-cell|wwan|4g|5g|signal|rssi|sinr|rsrp|bars)",
    re.I,
)


def extract_cellular_kv(parsed: dict[str, Any]) -> list[dict[str, str]]:
    """Key/value pairs for cellular / LTE / signal-like fields (flattened, capped)."""
    out: list[dict[str, str]] = []

    def walk(obj: Any, prefix: str, depth: int) -> None:
        if depth > 6 or len(out) >= 80:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                lk = f"{prefix}.{k}".lower()
                if _CELL_HINT.search(lk) or _CELL_HINT.search(str(k)):
                    if isinstance(v, (dict, list)):
                        try:
                            frag = json.dumps(v, default=str)[:800]
                        except TypeError:
                            frag = str(v)[:800]
                        out.append({"label": path, "value": frag})
                    else:
                        s = _scalar_to_str(v)
                        if s:
                            out.append({"label": path, "value": s[:2000]})
                elif isinstance(v, (dict, list)):
                    walk(v, path, depth + 1)

        elif isinstance(obj, list) and obj:
            for i, x in enumerate(obj[:25]):
                walk(x, f"{prefix}[{i}]", depth + 1)

    walk(parsed, "", 0)
    return out


def display_serial(stored: str, parsed: dict[str, Any]) -> str:
    """Prefer DB column; fall back to parsing raw Manager JSON (legacy rows)."""
    if stored and stored.strip():
        return stored.strip()
    return deep_find_serial(parsed)
