"""Query helpers for normalized SD-WAN governance events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from terra.inventory_extract import utc_iso_for_json
from terra.models import SdWanGovernanceEvent, SdWanManagerInstance, SyncedDevice

_GOVERNANCE_SORT_COLUMNS: dict[str, Any] = {
    "entry_time_utc": SdWanGovernanceEvent.entry_time_utc,
    "severity_norm": SdWanGovernanceEvent.severity_norm,
    "stream_kind": SdWanGovernanceEvent.stream_kind,
    "title": SdWanGovernanceEvent.title,
    "system_ip": SdWanGovernanceEvent.system_ip,
    "site_id": SdWanGovernanceEvent.site_id,
    "cluster": SdWanManagerInstance.display_name,
    "tenant": SdWanGovernanceEvent.sdwan_tenant_name,
    "loguser": SdWanGovernanceEvent.loguser,
}


def _parse_unix_or_iso(raw: str | None, *, default: datetime) -> datetime:
    if raw is None or not str(raw).strip():
        return default
    s = str(raw).strip()
    try:
        return datetime.fromtimestamp(float(s), tz=UTC)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return default


def governance_event_to_row(
    ev: SdWanGovernanceEvent,
    *,
    cluster: str,
    device_hostname: str | None = None,
) -> dict[str, Any]:
    return {
        "id": ev.id,
        "stream_kind": ev.stream_kind,
        "entry_time_utc": utc_iso_for_json(ev.entry_time_utc),
        "severity_raw": ev.severity_raw,
        "severity_norm": ev.severity_norm,
        "active": ev.active,
        "cluster": cluster,
        "tenant": ev.sdwan_tenant_name or ev.sdwan_tenant_id or "—",
        "sdwan_instance_id": ev.sdwan_instance_id,
        "device_id": ev.synced_device_id,
        "device_hostname": device_hostname or "—",
        "system_ip": ev.system_ip or "—",
        "site_id": ev.site_id or "—",
        "title": ev.title,
        "summary": ev.summary,
        "component": ev.component or "—",
        "rule_name": ev.rule_name or "—",
        "loguser": ev.loguser or "—",
        "logfeature": ev.logfeature or "—",
        "degraded": ev.degraded,
    }


def list_governance_events(
    db: Session,
    *,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    sort: str = "entry_time_utc",
    sort_dir: Literal["asc", "desc"] = "desc",
    streams: list[str] | None = None,
    severities: list[str] | None = None,
    sdwan_instance_id: int | None = None,
    tenant_id: str | None = None,
    device_id: int | None = None,
    system_ip: str | None = None,
    site_id: str | None = None,
    active: bool | None = None,
    audit_user: str | None = None,
    audit_feature: str | None = None,
    q: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    base = (
        select(SdWanGovernanceEvent, SdWanManagerInstance.display_name, SyncedDevice.hostname)
        .join(SdWanManagerInstance, SdWanGovernanceEvent.sdwan_instance_id == SdWanManagerInstance.id)
        .outerjoin(SyncedDevice, SdWanGovernanceEvent.synced_device_id == SyncedDevice.id)
        .where(SdWanGovernanceEvent.user_id == user_id)
    )
    if streams:
        base = base.where(SdWanGovernanceEvent.stream_kind.in_(streams))
    if severities:
        base = base.where(SdWanGovernanceEvent.severity_norm.in_([s.lower() for s in severities]))
    if sdwan_instance_id is not None:
        base = base.where(SdWanGovernanceEvent.sdwan_instance_id == sdwan_instance_id)
    if tenant_id:
        base = base.where(SdWanGovernanceEvent.sdwan_tenant_id == tenant_id.strip())
    if device_id is not None:
        base = base.where(SdWanGovernanceEvent.synced_device_id == device_id)
    if system_ip:
        base = base.where(SdWanGovernanceEvent.system_ip == system_ip.strip())
    if site_id:
        base = base.where(SdWanGovernanceEvent.site_id == site_id.strip())
    if active is not None:
        base = base.where(SdWanGovernanceEvent.active.is_(active))
    if audit_user:
        like = f"%{audit_user.strip()}%"
        base = base.where(SdWanGovernanceEvent.loguser.ilike(like))
    if audit_feature:
        like = f"%{audit_feature.strip()}%"
        base = base.where(SdWanGovernanceEvent.logfeature.ilike(like))
    if start is not None:
        base = base.where(SdWanGovernanceEvent.entry_time_utc >= start)
    if end is not None:
        base = base.where(SdWanGovernanceEvent.entry_time_utc <= end)
    if q and q.strip():
        term = f"%{q.strip()}%"
        base = base.where(
            or_(
                SdWanGovernanceEvent.title.ilike(term),
                SdWanGovernanceEvent.summary.ilike(term),
                SdWanGovernanceEvent.component.ilike(term),
                SdWanGovernanceEvent.rule_name.ilike(term),
                SdWanGovernanceEvent.loguser.ilike(term),
                SdWanGovernanceEvent.system_ip.ilike(term),
            )
        )

    count_q = select(func.count()).select_from(base.subquery())
    total = int(db.scalar(count_q) or 0)

    sort_col = _GOVERNANCE_SORT_COLUMNS.get(sort, SdWanGovernanceEvent.entry_time_utc)
    order = sort_col.desc() if sort_dir == "desc" else sort_col.asc()
    rows = db.execute(base.order_by(order, SdWanGovernanceEvent.id.desc()).limit(limit).offset(offset)).all()
    items = [
        governance_event_to_row(ev, cluster=cluster or "?", device_hostname=hostname)
        for ev, cluster, hostname in rows
    ]
    return items, total


def get_governance_event(db: Session, event_id: int, *, user_id: int) -> dict[str, Any] | None:
    row = db.execute(
        select(SdWanGovernanceEvent, SdWanManagerInstance.display_name, SyncedDevice.hostname)
        .join(SdWanManagerInstance, SdWanGovernanceEvent.sdwan_instance_id == SdWanManagerInstance.id)
        .outerjoin(SyncedDevice, SdWanGovernanceEvent.synced_device_id == SyncedDevice.id)
        .where(SdWanGovernanceEvent.id == event_id, SdWanGovernanceEvent.user_id == user_id)
    ).one_or_none()
    if row is None:
        return None
    ev, cluster, hostname = row
    out = governance_event_to_row(ev, cluster=cluster or "?", device_hostname=hostname)
    try:
        out["raw_json"] = json.loads(ev.raw_json)
    except json.JSONDecodeError:
        out["raw_json"] = ev.raw_json
    return out


def governance_facets(
    db: Session,
    *,
    user_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    filters = [SdWanGovernanceEvent.user_id == user_id]
    if start is not None:
        filters.append(SdWanGovernanceEvent.entry_time_utc >= start)
    if end is not None:
        filters.append(SdWanGovernanceEvent.entry_time_utc <= end)

    sev_q = select(SdWanGovernanceEvent.severity_norm).distinct()
    stream_q = select(SdWanGovernanceEvent.stream_kind).distinct()
    for f in filters:
        sev_q = sev_q.where(f)
        stream_q = stream_q.where(f)
    severities = sorted(s for s in db.scalars(sev_q) if s)
    streams = sorted(s for s in db.scalars(stream_q) if s)

    cluster_q = (
        select(SdWanManagerInstance.id, SdWanManagerInstance.display_name)
        .join(SdWanGovernanceEvent, SdWanGovernanceEvent.sdwan_instance_id == SdWanManagerInstance.id)
        .distinct()
        .order_by(SdWanManagerInstance.display_name)
    )
    for f in filters:
        cluster_q = cluster_q.where(f)
    cluster_rows = db.execute(cluster_q).all()
    return {
        "severities": severities,
        "streams": streams,
        "clusters": [{"id": cid, "display_name": name} for cid, name in cluster_rows],
    }


def default_governance_window_hours(hours: int = 24) -> tuple[datetime, datetime]:
    from datetime import timedelta

    end = datetime.now(tz=UTC)
    start = end - timedelta(hours=hours)
    return start, end
