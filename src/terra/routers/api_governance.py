"""Governance events API (alarms, events, audit projections)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from terra.crud_governance import (
    default_governance_window_hours,
    get_governance_event,
    governance_facets,
    list_governance_events,
)
from terra.db import get_db
from terra.deps import get_current_user
from terra.models import User
from terra.schemas import (
    GovernanceEventDetail,
    GovernanceEventRow,
    GovernanceEventsFacets,
    GovernanceEventsListResponse,
)

router = APIRouter(prefix="/api/v1/me/governance", tags=["governance"])


def _parse_time_param(raw: str | None, *, default: datetime) -> datetime:
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


def _split_csv(raw: str | None) -> list[str] | None:
    if raw is None or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    return parts or None


@router.get("/events", response_model=GovernanceEventsListResponse)
def governance_events_list(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("entry_time_utc", max_length=64),
    dir: Literal["asc", "desc"] = Query("desc", alias="dir"),
    stream: str | None = Query(None, description="Comma-separated: alarm,event,audit"),
    severity: str | None = Query(None, description="Comma-separated normalized severities"),
    sdwan_instance_id: int | None = Query(None),
    tenant_id: str | None = Query(None, max_length=160),
    device_id: int | None = Query(None),
    system_ip: str | None = Query(None, max_length=64),
    site_id: str | None = Query(None, max_length=128),
    active: bool | None = Query(None),
    audit_user: str | None = Query(None, max_length=128),
    audit_feature: str | None = Query(None, max_length=128),
    q: str | None = Query(None, max_length=200),
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> GovernanceEventsListResponse:
    default_start, default_end = default_governance_window_hours(24)
    start_dt = _parse_time_param(start, default=default_start)
    end_dt = _parse_time_param(end, default=default_end)
    if start_dt >= end_dt:
        start_dt = end_dt - timedelta(hours=1)
    items, total = list_governance_events(
        db,
        user_id=user.id,
        limit=limit,
        offset=offset,
        sort=sort,
        sort_dir=dir,
        streams=_split_csv(stream),
        severities=_split_csv(severity),
        sdwan_instance_id=sdwan_instance_id,
        tenant_id=tenant_id,
        device_id=device_id,
        system_ip=system_ip,
        site_id=site_id,
        active=active,
        audit_user=audit_user,
        audit_feature=audit_feature,
        q=q,
        start=start_dt,
        end=end_dt,
    )
    return GovernanceEventsListResponse(
        items=[GovernanceEventRow.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/events/facets", response_model=GovernanceEventsFacets)
def governance_events_facets(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    start: str | None = Query(None),
    end: str | None = Query(None),
) -> GovernanceEventsFacets:
    default_start, default_end = default_governance_window_hours(24)
    start_dt = _parse_time_param(start, default=default_start)
    end_dt = _parse_time_param(end, default=default_end)
    data = governance_facets(db, user_id=user.id, start=start_dt, end=end_dt)
    return GovernanceEventsFacets.model_validate(data)


@router.get("/events/{event_id}", response_model=GovernanceEventDetail)
def governance_event_detail(
    event_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> GovernanceEventDetail:
    row = get_governance_event(db, event_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return GovernanceEventDetail.model_validate(row)
