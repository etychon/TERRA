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


def _pick_first_meaningful_ip(d: dict[str, Any], *keys: str) -> str:
    """Like ``_pick`` for address fields, but treats ``-`` / ``n/a`` / empty as absent (Cisco interface API)."""
    absent = frozenset(
        {
            "",
            "-",
            "—",
            "n/a",
            "na",
            "none",
            "null",
            "::",
        },
    )
    for k in keys:
        if k not in d:
            continue
        s = _scalar_to_str(d.get(k))
        if not s or s.strip().lower() in absent:
            continue
        return s
    return ""


def _ipv4_to_int(addr: str) -> int | None:
    parts = addr.strip().split(".")
    if len(parts) != 4:
        return None
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octets):
        return None
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def _prefix_bits_from_mask_int(mask_int: int) -> int | None:
    """CIDR prefix length for a contiguous IPv4 netmask, or None if invalid."""
    if mask_int < 0 or mask_int > 0xFFFFFFFF:
        return None
    if mask_int == 0:
        return 0
    inv = (~mask_int) & 0xFFFFFFFF
    if inv == 0:
        return 32
    inc = inv + 1
    if inc & (inc - 1) != 0:
        return None
    return 32 - (inc.bit_length() - 1)


def _prefix_from_dotted_mask(mask: str) -> int | None:
    m = _ipv4_to_int(mask)
    if m is None:
        return None
    return _prefix_bits_from_mask_int(m)


def _iface_status_label_tone(raw: str) -> tuple[str, str]:
    """Human label + chip tone (success | error | warning | neutral) for admin/oper status."""
    s = raw.strip().lower()
    if not s:
        return "Unknown", "neutral"
    if s in {"up", "1", "if-up", "true", "yes", "ready"}:
        return "Up", "success"
    if s in {"down", "2", "if-down", "false", "no"}:
        return "Down", "error"
    if "down" in s and "admin" in s:
        return "Admin down", "error"
    if "down" in s:
        return "Down", "error"
    if "up" in s and "down" not in s:
        return "Up", "success"
    if s in {"3", "testing"}:
        return "Testing", "warning"
    if s in {"4", "unknown"} or "unknown" in s:
        return "Unknown", "neutral"
    if s in {"5", "dormant"}:
        return "Dormant", "warning"
    if "lower" in s or "partial" in s or "degraded" in s:
        return raw.strip()[:48] or "Degraded", "warning"
    return raw.strip()[:48] or "Unknown", "neutral"


def _canon_line_state_token(raw: str) -> str:
    """Collapse hyphens/underscores/spacing for comparing noisy Manager / YANG echo values."""
    s = raw.strip().lower()
    for ch in ("\u2011", "\u2010", "\u2212", "\u00ad"):
        s = s.replace(ch, "-")
    return re.sub(r"[^a-z0-9]", "", s)


# Values sometimes copied into ``if-oper-status`` (or only present as the ready leaf echo).
_OPER_LINE_STATE_ECHO_CANON: frozenset[str] = frozenset(
    {
        "ifoperstateready",
        "operstateready",
    }
)


def _oper_value_is_placeholder_leaf(oper_primary: str) -> bool:
    """True when the string is a YANG leaf echo / placeholder, not a real SNMP-style oper state."""
    c = _canon_line_state_token(oper_primary)
    if not c:
        return False
    if c in _OPER_LINE_STATE_ECHO_CANON:
        return True
    # e.g. ``if-oper-state-ready-yang`` or vendor suffixes — still the ready leaf, not ``up``/``down``.
    return c.startswith("ifoperstateready") or c.startswith("operstateready")


def _line_oper_label_tone(oper_raw: str) -> tuple[str, str]:
    """Line state column: never show raw YANG leaf names; treat known echoes as **Up**."""
    if _oper_value_is_placeholder_leaf(oper_raw):
        return "Up", "success"
    return _iface_status_label_tone(oper_raw)


def _if_oper_state_ready_implies_up(ready_raw: str) -> bool:
    """``if-oper-state-ready`` (and similar) often means the line protocol is ready / up."""
    s = ready_raw.strip().lower()
    if not s:
        return False
    if s in {"true", "1", "yes", "up", "ready", "if-ready", "if-up"}:
        return True
    if "not-ready" in s or "not_ready" in s or s in {"false", "0", "no", "down"}:
        return False
    return "ready" in s


def _oper_primary_ambiguous_or_unknown(oper_primary: str) -> bool:
    """True when ``if-oper-status`` is absent or does not give a clear line state on its own."""
    if not oper_primary.strip():
        return True
    if _oper_value_is_placeholder_leaf(oper_primary):
        return True
    o_label, o_tone = _iface_status_label_tone(oper_primary)
    if o_label == "Unknown":
        return True
    s = oper_primary.strip().lower()
    return o_tone == "neutral" and (
        s in {"0", "unknown", "n/a", "-", "--"} or (s.isdigit() and s not in {"1", "2"})
    )


def _effective_oper_raw_for_line_state(d: dict[str, Any]) -> tuple[str, str, str]:
    """
    Return ``(raw_for_tone, oper_primary, ready_raw)`` for line state.

    Prefer ``if-oper-status``. When it is absent or ambiguous/unknown, treat a true
    ``if-oper-state-ready`` as operational ``up``. Does not override an explicit oper Down.
    """
    oper_primary = _pick(
        d,
        "if-oper-status",
        "ifOperStatus",
        "if_oper_status",
        "oper-state",
        "operState",
        "operation-state",
        "line-protocol",
    )
    ready_raw = _pick(
        d,
        "if-oper-state-ready",
        "ifOperStateReady",
        "if_oper_state_ready",
        "oper-state-ready",
        "operStateReady",
    )
    if oper_primary.strip():
        o_label, o_tone = _iface_status_label_tone(oper_primary)
        if o_tone == "error" and o_label == "Down":
            return oper_primary, oper_primary, ready_raw
        if _if_oper_state_ready_implies_up(ready_raw) and _oper_primary_ambiguous_or_unknown(oper_primary):
            return "up", oper_primary, ready_raw
        if _oper_value_is_placeholder_leaf(oper_primary):
            return "up", oper_primary, ready_raw
        return oper_primary, oper_primary, ready_raw
    if _if_oper_state_ready_implies_up(ready_raw):
        return "up", oper_primary, ready_raw
    if ready_raw.strip():
        return ready_raw, oper_primary, ready_raw
    return "", oper_primary, ready_raw


def _parse_positive_int_str(s: str) -> int | None:
    try:
        n = int(float(s))
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def _resolve_ip_cidr(ip_val: str, d: dict[str, Any]) -> str:
    """Format ``address/prefix`` when prefix or netmask is available; else plain IP or em dash."""
    ip = ip_val.strip()
    if not ip or ip == "—":
        return "—"
    if ip in {"0.0.0.0", "::"}:
        return "—"
    pl = _pick(
        d,
        "ipv4-prefix-length",
        "ipv4PrefixLength",
        "prefix-length",
        "prefixLength",
        "cidr-prefix",
        "cidrPrefix",
        "ip-prefix-length",
        "ipPrefixLength",
    )
    if pl and pl.isdigit():
        p = int(pl)
        if 0 <= p <= 32:
            return f"{ip}/{p}"
    mask = _pick(
        d,
        "ipv4-subnet-mask",
        "ipv4SubnetMask",
        "subnet-mask",
        "subnetMask",
        "netmask",
        "mask",
    )
    if mask:
        bits = _prefix_from_dotted_mask(mask)
        if bits is not None:
            return f"{ip}/{bits}"
    return ip


def _speed_human_from_dict(d: dict[str, Any]) -> str:
    raw = _pick(
        d,
        "negotiated-port-speed",
        "negotiatedPortSpeed",
        "port-speed",
        "portSpeed",
        "speed",
        "lan-speed",
        "lanSpeed",
        "link-speed",
        "linkSpeed",
    )
    if not raw:
        return ""
    s = raw.strip()
    low = s.lower()
    if any(u in low for u in ("bps", "gbps", "mbps", "kbps", "auto", "n/a", "none")):
        return s[:64]
    try:
        n = float(s)
    except ValueError:
        return s[:64]
    if n <= 0:
        return ""
    if n >= 1_000_000:
        g = n / 1_000_000_000
        if g >= 1:
            return f"{g:g} Gbps"
        m = n / 1_000_000
        return f"{m:g} Mbps"
    if n >= 1000:
        return f"{n / 1000:g} Gbps"
    return f"{n:g} Mbps"


def _vpn_id_from_dict(d: dict[str, Any], vrf_fallback: str) -> int:
    vid = _pick(d, "vpn-id", "vpnId", "vpnID")
    if not vid and vrf_fallback.isdigit():
        vid = vrf_fallback
    if not vid:
        return -1
    n = _parse_positive_int_str(vid)
    return n if n is not None else -1


def _is_tunnel_row(name: str, d: dict[str, Any]) -> bool:
    it = _pick(d, "interface-type", "interfaceType", "intf-type", "intfType", "if-type", "ifType").lower()
    if it and any(x in it for x in ("tunnel", "ipsec", "gre", "vti", "sslvpn")):
        return True
    nl = name.strip().lower()
    if nl.startswith(("tunnel", "ipsec", "gre", "vti", "sslvpn", "dvti")):
        return True
    return "tunnel" in nl or "ipsec" in nl


def _has_assigned_ipv4(ip_plain: str, ip_cidr: str) -> bool:
    ip = ip_plain.strip()
    if not ip or ip == "—" or ip in {"0.0.0.0", "::"}:
        return False
    return not (ip_cidr == "—" or not ip_cidr.strip())


_IFACE_LIST_KEYS = (
    "deviceInterface",
    "interfaces",
    "ipInterfaces",
    "interfaceList",
    "vpnInterface",
    "runningInterfaces",
    "device-interfaces",
    "deviceInterfaces",
)

# When walking nested Manager JSON, only descend into these object keys (avoids huge unrelated trees).
_IFACE_RECURSE_PARENT_KEYS = frozenset(
    {
        "running",
        "config",
        "device",
        "deviceInventory",
        "device-data",
        "deviceData",
        "vdevice-data",
        "vdeviceData",
        "data",
        "DATA",
        "system",
        "hardware",
        "platform",
        "lifeCycle",
        "life-cycle",
        "bfd",
        "omp",
        "vpn",
        "vpn-instance",
        "vpnInstance",
        "terraEnrichedFromSync",
    }
)


def _row_from_interface_dict(d: dict[str, Any]) -> dict[str, str]:
    name = _pick(
        d,
        "ifname",
        "ifName",
        "interfaceName",
        "interface-name",
        "intf-name",
        "intfName",
        "intf",
        "name",
        "interface",
        "Interface",
        "vpn-interface-name",
        "vpnInterfaceName",
        "src-if",
        "srcIf",
        "logicalIfName",
        "physical-interface",
        "physicalInterface",
        "nic",
        "INTF",
    )
    ip_val = _pick_first_meaningful_ip(
        d,
        "ip-address",
        "ipAddress",
        "intf-ip-address",
        "intfIpAddress",
        "interfaceIp",
        "interface-ip",
        "interface-ip-address",
        "interfaceIpAddress",
        "ipv4-address",
        "ipv4Address",
        "ipv4-addr",
        "ipv4Addr",
        "address",
        "ip",
        "private-ip",
        "privateIp",
        "public-ip",
        "publicIp",
        "secondary-address",
        "secondaryAddress",
        "pdp-ipv4-address",
        "pdpIpv4Address",
        "pdn-ipv4-address",
        "pdnIpv4Address",
        "assigned-ip",
        "assignedIp",
        "modem-ip",
        "modemIp",
    )
    vrf = _pick(
        d,
        "vrfName",
        "vrf-name",
        "vrf",
        "vpn-id",
        "vpnId",
        "vpn-name",
        "vpnName",
    )
    admin_raw = _pick(
        d,
        "if-admin-status",
        "ifAdminStatus",
        "admin-state",
        "adminState",
        "admin-v26",
    )
    oper_raw, oper_primary, oper_ready = _effective_oper_raw_for_line_state(d)
    admin_label, admin_tone = _iface_status_label_tone(admin_raw)
    oper_label, oper_tone = _line_oper_label_tone(oper_raw)
    mtu = _pick(d, "mtu", "if-mtu")

    ip_plain = ip_val or "—"
    ip_cidr = _resolve_ip_cidr(ip_val, d) if ip_val else "—"
    if not ip_val:
        ip_cidr = "—"

    speed_human = _speed_human_from_dict(d)
    vid = _vpn_id_from_dict(d, "")
    if vid < 0:
        alt = _pick(d, "vrfName", "vrf-name", "vrf")
        if alt.isdigit():
            vid = int(alt)
    vpn_id_str = str(vid) if vid >= 0 else ""
    if vid == 0:
        service_vpn = "WAN"
    elif vid > 0:
        service_vpn = "LAN"
    else:
        service_vpn = "—"

    if_name = name or "—"
    is_tunnel = "1" if _is_tunnel_row(if_name, d) else "0"

    has_ip = _has_assigned_ipv4(ip_val, ip_cidr)
    admin_down = bool(admin_raw.strip()) and admin_tone == "error" and admin_label in {"Down", "Admin down"}
    row_defer = "1" if (admin_down or not has_ip) else "0"

    out: dict[str, str] = {
        "interface": if_name,
        "ip": ip_plain,
        "ip_cidr": ip_cidr,
        "vrf": vrf or "—",
        "admin_status": admin_label,
        "admin_tone": admin_tone,
        "oper_status": oper_label,
        "oper_tone": oper_tone,
        "speed": speed_human,
        "vpn_id": vpn_id_str,
        "service_vpn": service_vpn,
        "is_tunnel": is_tunnel,
        "row_defer": row_defer,
    }
    detail_parts: list[str] = []
    if admin_raw and admin_raw != admin_label:
        detail_parts.append(f"admin {admin_raw}")
    if oper_raw and oper_raw.lower() != oper_label.lower():
        detail_parts.append(f"oper {oper_raw}")
    elif oper_ready.strip() and oper_raw == "up" and _oper_primary_ambiguous_or_unknown(oper_primary):
        detail_parts.append(f"if-oper-state-ready {oper_ready}")
    if mtu:
        detail_parts.append(f"MTU {mtu}")
    out["detail"] = ", ".join(detail_parts) if detail_parts else ""
    return out


def _ingest_interface_list(items: list[Any], add_row: Any) -> None:
    for item in items:
        if isinstance(item, dict):
            add_row(_row_from_interface_dict(item))


def _ingest_interface_dict_map(mapping: dict[str, Any], add_row: Any) -> None:
    """vManage often uses ``interface: { \"Gi0/0\": { ... } }`` instead of a list."""
    for name_key, item in mapping.items():
        if not isinstance(item, dict):
            continue
        row = _row_from_interface_dict(item)
        if row["interface"] == "—" and isinstance(name_key, str):
            nk = name_key.strip()
            if nk and not nk.isdigit():
                row["interface"] = nk
        add_row(row)


def _walk_nested_for_interfaces(obj: Any, depth: int, add_row: Any) -> None:
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if isinstance(v, list) and (k in _IFACE_LIST_KEYS or lk.endswith("interfaces")):
                _ingest_interface_list(v, add_row)
            elif isinstance(v, dict) and lk == "interface":
                _ingest_interface_dict_map(v, add_row)
            elif isinstance(v, dict) and lk in _IFACE_RECURSE_PARENT_KEYS:
                _walk_nested_for_interfaces(v, depth + 1, add_row)
            elif isinstance(v, list) and lk == "data" and depth < 3 and v:
                for x in v[:40]:
                    if isinstance(x, dict):
                        _walk_nested_for_interfaces(x, depth + 1, add_row)
            elif isinstance(v, list) and lk.endswith("interface") and lk != "interface":
                _ingest_interface_list(v, add_row)
    elif isinstance(obj, list):
        for x in obj[:80]:
            _walk_nested_for_interfaces(x, depth + 1, add_row)


def extract_interface_rows(parsed: dict[str, Any]) -> list[dict[str, str]]:
    """Summarize interfaces from common SD-WAN / vManage device payload shapes."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add_row(r: dict[str, str]) -> None:
        # Wider key than (ifname, ip) so rows that map to placeholders are not all collapsed into one.
        key = (r["interface"], r.get("ip", ""), r.get("vrf", ""), (r.get("detail") or "")[:160])
        if key in seen:
            return
        seen.add(key)
        rows.append(r)

    for lk in _IFACE_LIST_KEYS:
        raw = parsed.get(lk)
        if isinstance(raw, list):
            _ingest_interface_list(raw, add_row)

    for k, v in parsed.items():
        lk = str(k).lower()
        if lk == "interface" and isinstance(v, dict):
            _ingest_interface_dict_map(v, add_row)
        elif lk.endswith("interface") and isinstance(v, list):
            _ingest_interface_list(v, add_row)

    _walk_nested_for_interfaces(parsed, 0, add_row)

    return rows[:500]


def interface_row_sort_key(r: dict[str, str]) -> tuple[int, int, int, str]:
    """Sort: physical interfaces before tunnels; WAN (vpn 0) before LAN; then vpn id; then name."""
    tun = 1 if r.get("is_tunnel") == "1" else 0
    try:
        vid = int(r.get("vpn_id", "-1"))
    except ValueError:
        vid = -1
    wan_bucket = 0 if vid == 0 else 1
    sort_vid = vid if vid >= 0 else 999_999
    return (tun, wan_bucket, sort_vid, (r.get("interface") or "").lower())


def prepare_interface_detail_tables(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split rows into primary vs collapsed (admin-down or no IPv4), preserving WAN-first / tunnel-last order."""
    ordered = sorted(rows, key=interface_row_sort_key)
    primary: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    for r in ordered:
        if r.get("row_defer") == "1":
            deferred.append(r)
        else:
            primary.append(r)
    return primary, deferred


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
