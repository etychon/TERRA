"""Query synced SD-WAN devices (scoped to owning user via Manager instance)."""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from terra.crud_sdwan import _CONTROLLER_DEVICE_TYPES, _is_controller_inventory_row
from terra.inventory_extract import (
    device_has_cellular_capability,
    display_inventory_model,
    display_inventory_serial,
    display_ios_xe_release,
    display_site_name,
    extract_geo_lat_lng,
    utc_iso_for_json,
)
from terra.models import SdWanManagerInstance, SyncedDevice, User

_DEVICE_SORT_COLUMNS: dict[str, Any] = {
    "hostname": SyncedDevice.hostname,
    "serial_number": SyncedDevice.serial_number,
    "model": SyncedDevice.model,
    "software_version": SyncedDevice.software_version,
    "site_name": SyncedDevice.site_id,
    "device_type": SyncedDevice.device_type,
    "tenant": SyncedDevice.sdwan_tenant_name,
    "reachability": SyncedDevice.reachability,
    "state_changed_at_utc": SyncedDevice.state_changed_at_utc,
    "synced_at_utc": SyncedDevice.synced_at_utc,
    "cluster": SdWanManagerInstance.display_name,
    "owner_email": User.email,
}


def _sql_exclude_controllers() -> ColumnElement[bool]:
    dt = func.lower(SyncedDevice.device_type)
    host = func.lower(SyncedDevice.hostname)
    return ~or_(
        dt.in_(tuple(_CONTROLLER_DEVICE_TYPES)),
        dt.like("vmanage%"),
        host.in_(("vmanage", "vbond", "vsmart", "vsmart2")),
    )


def list_all_devices_for_ui(db: Session) -> list[tuple[SyncedDevice, str]]:
    """All synced devices for the Home grid (every user sees the full fabric)."""
    q = (
        select(SyncedDevice, User.email)
        .join(SdWanManagerInstance, SyncedDevice.sdwan_instance_id == SdWanManagerInstance.id)
        .join(User, SdWanManagerInstance.user_id == User.id)
        .order_by(
            User.email.asc(),
            SyncedDevice.sdwan_tenant_name.asc(),
            SyncedDevice.hostname.asc(),
            SyncedDevice.id.asc(),
        )
    )
    return [(d, mail) for d, mail in db.execute(q).all()]


def list_map_device_telemetry_for_ui(db: Session) -> list[dict[str, Any]]:
    """Devices that appear on the home map (have lat/lng in raw JSON) with fields for poll/ripple."""
    out: list[dict[str, Any]] = []
    for d, _owner in list_all_devices_for_ui(db):
        try:
            raw = json.loads(d.raw_json)
            if not isinstance(raw, dict):
                raw = {}
        except json.JSONDecodeError:
            raw = {}
        lat, lng = extract_geo_lat_lng(raw)
        if lat is None or lng is None:
            continue
        out.append(
            {
                "id": d.id,
                "synced_at_utc": utc_iso_for_json(d.synced_at_utc),
                "state_changed_at_utc": utc_iso_for_json(d.state_changed_at_utc),
                "reachability": d.reachability or "",
            }
        )
    return out


def get_device_for_user(db: Session, _user_id: int, device_id: int) -> SyncedDevice | None:
    """Return a synced device by id (any signed-in user may open any device)."""
    return db.get(SyncedDevice, device_id)


def get_devices_for_user_by_ids(db: Session, _user_id: int, device_ids: list[int]) -> list[SyncedDevice]:
    """Return devices for compare by id (any signed-in user; order follows ``device_ids``)."""
    if not device_ids:
        return []
    q = select(SyncedDevice).where(SyncedDevice.id.in_(device_ids))
    rows = list(db.scalars(q))
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in device_ids if i in by_id]


def _parse_device_json(d: SyncedDevice) -> dict[str, Any]:
    try:
        parsed: dict[str, Any] = json.loads(d.raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed


def device_to_home_row(db: Session, d: SyncedDevice, *, owner_email: str) -> dict[str, Any]:
    inst = db.get(SdWanManagerInstance, d.sdwan_instance_id)
    cluster = inst.display_name if inst else "?"
    parsed = _parse_device_json(d)
    source_uuid = (d.source_device_uuid or "").strip()
    serial = display_inventory_serial(d.serial_number or "", parsed, source_uuid=source_uuid)
    model = display_inventory_model(d.model or "", parsed, source_uuid=source_uuid)
    software = display_ios_xe_release(d.software_version or "", parsed)
    site_name = display_site_name(d.site_id, parsed)
    tenant_cell = "—"
    tn = (d.sdwan_tenant_name or "").strip()
    tid = (d.sdwan_tenant_id or "").strip()
    if tn:
        tenant_cell = tn
    elif tid:
        tenant_cell = tid
    row: dict[str, Any] = {
        "id": d.id,
        "cluster": cluster,
        "manager": cluster,
        "tenant": tenant_cell,
        "hostname": d.hostname or "—",
        "serial_number": serial or "—",
        "model": model or "—",
        "software_version": software or "—",
        "device_type": d.device_type or "—",
        "site_name": site_name or "—",
        "site_id": d.site_id or "—",
        "reachability": d.reachability,
        "state_changed_at_utc": utc_iso_for_json(d.state_changed_at_utc),
        "synced_at_utc": utc_iso_for_json(d.synced_at_utc),
        "has_cellular": device_has_cellular_capability(parsed, model=model, hostname=d.hostname or ""),
        "owner_email": owner_email,
    }
    return row


def list_devices_for_api(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
    sort: str = "hostname",
    sort_dir: Literal["asc", "desc"] = "asc",
    hide_control: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated device rows for the React devices grid API."""
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    sort_key = sort if sort in _DEVICE_SORT_COLUMNS else "hostname"
    col = _DEVICE_SORT_COLUMNS[sort_key]
    order = col.asc() if sort_dir == "asc" else col.desc()

    base = (
        select(SyncedDevice, User.email, SdWanManagerInstance.display_name)
        .join(SdWanManagerInstance, SyncedDevice.sdwan_instance_id == SdWanManagerInstance.id)
        .join(User, SdWanManagerInstance.user_id == User.id)
    )
    if hide_control:
        base = base.where(_sql_exclude_controllers())

    needle = (q or "").strip()
    if needle:
        pattern = f"%{needle}%"
        base = base.where(
            or_(
                SyncedDevice.hostname.ilike(pattern),
                SyncedDevice.serial_number.ilike(pattern),
                SyncedDevice.model.ilike(pattern),
                SyncedDevice.site_id.ilike(pattern),
                SyncedDevice.sdwan_tenant_name.ilike(pattern),
                SyncedDevice.device_type.ilike(pattern),
                SdWanManagerInstance.display_name.ilike(pattern),
            )
        )

    count_q = select(func.count()).select_from(base.subquery())
    total = int(db.scalar(count_q) or 0)

    rows = db.execute(base.order_by(order, SyncedDevice.id.asc()).limit(lim).offset(off)).all()
    items = [
        device_to_home_row(db, d, owner_email=mail)
        for d, mail, _cluster in rows
    ]
    return items, total


def is_controller_device_row(device_type: str, hostname: str) -> bool:
    """Public wrapper for grid client-side checks."""
    return _is_controller_inventory_row(device_type, hostname)
