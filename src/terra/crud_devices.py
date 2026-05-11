"""Query synced SD-WAN devices (scoped to owning user via Manager instance)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.inventory_extract import deep_find_serial, utc_iso_for_json
from terra.models import SdWanManagerInstance, SyncedDevice, User


def list_all_devices_for_ui(db: Session) -> list[tuple[SyncedDevice, str]]:
    """All synced devices for the Home grid (every user sees the full fabric)."""
    q = (
        select(SyncedDevice, User.email)
        .join(SdWanManagerInstance, SyncedDevice.sdwan_instance_id == SdWanManagerInstance.id)
        .join(User, SdWanManagerInstance.user_id == User.id)
        .order_by(User.email.asc(), SyncedDevice.hostname.asc(), SyncedDevice.id.asc())
    )
    return [(d, mail) for d, mail in db.execute(q).all()]


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


def device_to_home_row(db: Session, d: SyncedDevice, *, owner_email: str) -> dict[str, Any]:
    inst = db.get(SdWanManagerInstance, d.sdwan_instance_id)
    mgr = inst.display_name if inst else "?"
    serial = (d.serial_number or "").strip()
    if not serial:
        try:
            raw = json.loads(d.raw_json)
            if isinstance(raw, dict):
                serial = deep_find_serial(raw)
        except json.JSONDecodeError:
            pass
    row: dict[str, Any] = {
        "id": d.id,
        "manager": mgr,
        "hostname": d.hostname or "—",
        "serial_number": serial or "—",
        "model": d.model or "—",
        "software_version": d.software_version or "—",
        "device_type": d.device_type or "—",
        "site_id": d.site_id or "—",
        "reachability": d.reachability,
        "state_changed_at_utc": utc_iso_for_json(d.state_changed_at_utc),
        "synced_at_utc": utc_iso_for_json(d.synced_at_utc),
    }
    row["owner_email"] = owner_email
    return row
