"""Pull device inventory from Cisco Catalyst SD-WAN Manager into the local database (UTC)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.inventory_extract import deep_find_serial
from terra.models import SdWanLinkStatus, SdWanManagerInstance, SyncedDevice
from terra.sdwan_client import read_manager_version
from terra.sdwan_dataservice_rows import rows_from_dataservice_body
from terra.sdwan_http import open_manager_http_client

logger = logging.getLogger(__name__)

# When GET /dataservice/device returns no rows (some lab / CVD builds), try controller inventories.
_FALLBACK_DEVICE_PATHS: tuple[str, ...] = (
    "system/device/vedges",
    "system/device/controllers",
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


def fetch_device_inventory(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    """GET /dataservice/device (and fallbacks) — full inventory list."""
    base = base_url.rstrip("/")
    r = client.get(f"{base}/dataservice/device", headers={"Accept": "application/json"})
    if r.status_code >= 400:
        msg = f"device inventory HTTP {r.status_code}"
        raise RuntimeError(msg)
    try:
        body = r.json()
    except ValueError as e:
        msg = "device inventory invalid JSON"
        raise RuntimeError(msg) from e

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

    primary = rows_from_dataservice_body(body)
    ingest(primary)

    if not merged:
        for path in _FALLBACK_DEVICE_PATHS:
            r2 = client.get(f"{base}/dataservice/{path}", headers={"Accept": "application/json"})
            if r2.status_code >= 400:
                continue
            try:
                b2 = r2.json()
            except ValueError:
                continue
            ingest(rows_from_dataservice_body(b2))

    return [merged[k] for k in order]


def sync_devices_for_instance(db: Session, secret_key: str, inst: SdWanManagerInstance) -> tuple[int, str | None]:
    """
    Upsert devices for one Manager instance. Returns (rows_touched, error_message).
    All timestamps written in UTC.
    """
    if inst.link_status != SdWanLinkStatus.connected.value:
        return 0, "instance not connected"

    now = _utcnow()
    touched = 0
    try:
        with open_manager_http_client(secret_key, inst) as client:
            rows = fetch_device_inventory(client, inst.base_url)
            if not inst.manager_version:
                mv = read_manager_version(client, inst.base_url)
                if mv:
                    inst.manager_version = mv[:128]
    except (RuntimeError, ValueError, httpx.RequestError, OSError) as e:
        logger.warning("SD-WAN device sync failed for instance %s: %s", inst.id, e)
        return 0, str(e)[:500]

    for raw in rows:
        norm = normalize_inventory_row(raw)
        if not norm["source_device_uuid"]:
            continue
        uid = str(norm["source_device_uuid"])[:160]
        existing = db.execute(
            select(SyncedDevice).where(
                SyncedDevice.sdwan_instance_id == inst.id,
                SyncedDevice.source_device_uuid == uid,
            )
        ).scalar_one_or_none()

        raw_json = json.dumps(raw, separators=(",", ":"), default=str)
        new_r = str(norm["reachability"])

        if existing is None:
            db.add(
                SyncedDevice(
                    sdwan_instance_id=inst.id,
                    source_device_uuid=uid,
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
        touched += 1

    inst.devices_last_sync_at_utc = now
    db.add(inst)
    return touched, None


def sync_user_sdwan_devices(db: Session, secret_key: str, user_id: int) -> dict[str, int]:
    """Sync inventory for all connected managers owned by one user."""
    q = select(SdWanManagerInstance).where(
        SdWanManagerInstance.user_id == user_id,
        SdWanManagerInstance.link_status == SdWanLinkStatus.connected.value,
    )
    instances = list(db.scalars(q))
    rows = 0
    errors = 0
    for inst in instances:
        n, err = sync_devices_for_instance(db, secret_key, inst)
        rows += max(n, 0)
        if err:
            errors += 1
    db.commit()
    return {"managers": len(instances), "rows_touched": rows, "errors": errors}


def sync_all_connected_managers(secret_key: str) -> None:
    """Background batch: sync every Manager row marked connected (all users)."""
    from terra.db import get_session_factory

    sf = get_session_factory()
    with sf() as db:
        q = select(SdWanManagerInstance).where(SdWanManagerInstance.link_status == SdWanLinkStatus.connected.value)
        instances = list(db.scalars(q))
        for inst in instances:
            try:
                sync_devices_for_instance(db, secret_key, inst)
            except Exception:
                logger.exception("SD-WAN sync crashed for instance id=%s", inst.id)
            try:
                db.commit()
            except Exception:
                logger.exception("SD-WAN sync commit failed")
                db.rollback()
