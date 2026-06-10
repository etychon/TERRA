"""Operator-visible logging context for outbound SD-WAN Manager (vManage) HTTP calls."""

from __future__ import annotations

import contextvars
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from terra.app_log_buffer import append_event
from terra.models import SdWanManagerInstance, SyncedDevice

_cluster_name: contextvars.ContextVar[str] = contextvars.ContextVar("terra_sdwan_log_cluster", default="")
_tenant_label: contextvars.ContextVar[str] = contextvars.ContextVar("terra_sdwan_log_tenant", default="")


def set_sdwan_http_log_cluster(name: str) -> None:
    _cluster_name.set((name or "").strip()[:200])


def set_sdwan_http_log_tenant(label: str) -> None:
    _tenant_label.set((label or "").strip()[:255])


def clear_sdwan_http_log_tenant() -> None:
    _tenant_label.set("")


def _detail_suffix() -> str:
    c = _cluster_name.get().strip()
    t = _tenant_label.get().strip()
    parts: list[str] = []
    if c:
        parts.append(f'cluster="{c}"')
    if t:
        parts.append(f'tenant="{t}"')
    return " ".join(parts)


def log_outbound_sdwan_request(request: Any) -> None:
    """``httpx`` event hook: log dataservice calls with cluster / tenant context."""
    try:
        raw_url = str(getattr(request, "url", "") or "")
        path = (urlparse(raw_url).path or "")[:512]
        method = str(getattr(request, "method", "?") or "?").upper()[:16]
    except Exception:
        return
    if "/dataservice/" not in path:
        return
    tail = path.split("?", 1)[0].rstrip("/")
    if "/dataservice/device" in tail and not tail.endswith("/dataservice/device"):
        return
    det = _detail_suffix()
    append_event("INFO", "sdwan_http", f"{method} {path}", detail=det)


def http_access_log_detail_for_path(db: Session, path: str) -> str:
    """
    Short detail line for TERRA HTTP access logs touching SD-WAN APIs (incoming requests).
    """
    p = path or ""
    m = re.search(r"/sync-sdwan-devices/(\d+)", p)
    if m:
        iid = int(m.group(1))
        inst = db.get(SdWanManagerInstance, iid)
        if inst is not None:
            return f'cluster="{inst.display_name}"'
        return f'cluster_id={iid} (not found)'
    m2 = re.search(r"/devices/(\d+)/live-sdwan", p)
    if m2:
        did = int(m2.group(1))
        dev = db.get(SyncedDevice, did)
        if dev is None:
            return f"device_id={did} (not found)"
        inst = db.get(SdWanManagerInstance, dev.sdwan_instance_id)
        cname = inst.display_name if inst else "?"
        tn = (dev.sdwan_tenant_name or "").strip()
        tid = (dev.sdwan_tenant_id or "").strip()
        tenant = tn or tid
        if tenant:
            return f'cluster="{cname}" tenant="{tenant}"'
        return f'cluster="{cname}"'
    if "/sync-sdwan-devices" in p and p.rstrip("/").endswith("/sync-sdwan-devices"):
        return "scope=all_managers"
    return ""
