"""SD-WAN Manager instance persistence (per-user)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from terra.models import SdWanManagerInstance, SyncedDevice


def list_sdwan_managers(db: Session, user_id: int) -> list[SdWanManagerInstance]:
    q = (
        select(SdWanManagerInstance)
        .where(SdWanManagerInstance.user_id == user_id)
        .order_by(SdWanManagerInstance.display_name.asc(), SdWanManagerInstance.id.asc())
    )
    return list(db.scalars(q))


def get_sdwan_manager(db: Session, user_id: int, instance_id: int) -> SdWanManagerInstance | None:
    return db.execute(
        select(SdWanManagerInstance).where(
            SdWanManagerInstance.user_id == user_id,
            SdWanManagerInstance.id == instance_id,
        )
    ).scalar_one_or_none()


def delete_sdwan_manager(db: Session, row: SdWanManagerInstance) -> None:
    db.delete(row)
    db.commit()


_CONTROLLER_DEVICE_TYPES: frozenset[str] = frozenset(
    {"vmanage", "vsmart", "vbond", "vcontainer", "vmanage-system"}
)


def _is_controller_inventory_row(device_type: str, hostname: str) -> bool:
    """Heuristic: exclude SD-WAN control-plane nodes from the edge list."""
    dt = (device_type or "").strip().lower()
    if not dt:
        return False
    if dt in _CONTROLLER_DEVICE_TYPES or dt.startswith("vmanage"):
        return True
    host = (hostname or "").strip().lower()
    return host in ("vmanage", "vbond", "vsmart", "vsmart2")


def count_synced_devices_for_manager(db: Session, instance_id: int) -> int:
    """All ``synced_devices`` rows for this Manager (includes controllers)."""
    n = db.scalar(
        select(func.count()).select_from(SyncedDevice).where(
            SyncedDevice.sdwan_instance_id == instance_id
        )
    )
    return int(n or 0)


def edge_inventory_labels_for_manager(
    db: Session,
    instance_id: int,
    *,
    max_labels: int = 500,
) -> tuple[int, list[str]]:
    """
    Return (edge_count, display labels) for Administration UI.
    Labels include tenant name when ``sdwan_tenant_name`` is set (multitenant).
    """
    q = (
        select(
            SyncedDevice.hostname,
            SyncedDevice.device_type,
            SyncedDevice.sdwan_tenant_name,
        )
        .where(SyncedDevice.sdwan_instance_id == instance_id)
        .order_by(SyncedDevice.sdwan_tenant_name.asc(), SyncedDevice.hostname.asc())
    )
    pairs = db.execute(q).all()
    labels: list[str] = []
    for hostname, device_type, tenant_name in pairs:
        if _is_controller_inventory_row(str(device_type), str(hostname)):
            continue
        host = (hostname or "").strip() or "—"
        tenant = (tenant_name or "").strip()
        if tenant:
            labels.append(f"{host} ({tenant})")
        else:
            labels.append(host)
    total = len(labels)
    if len(labels) > max_labels:
        labels = labels[:max_labels]
    return total, labels
