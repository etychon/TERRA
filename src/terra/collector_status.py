"""Postgres-backed collector heartbeat and cross-process operator log persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from terra.db import get_session_factory
from terra.models import AppLogEvent, CollectorStatus

logger = logging.getLogger(__name__)

_COLLECTOR_STATUS_ID = 1
_APP_LOG_EVENTS_MAX_ROWS = 2000
_PERSIST_COMPONENTS = frozenset({"sdwan_sync_batch", "collector", "sdwan_sync_job"})


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _with_db(fn: Any) -> Any:
    sf = get_session_factory()
    with sf() as db:
        result = fn(db)
        db.commit()
        return result


def _ensure_collector_row(db: Session) -> CollectorStatus:
    row = db.get(CollectorStatus, _COLLECTOR_STATUS_ID)
    if row is None:
        row = CollectorStatus(id=_COLLECTOR_STATUS_ID, service_name="collector")
        db.add(row)
        db.flush()
    return row


def touch_collector_heartbeat(*, interval_seconds: int, error: str | None = None) -> None:
    """Update singleton heartbeat (called at start of each collector loop tick)."""

    def _write(db: Session) -> None:
        row = _ensure_collector_row(db)
        row.last_heartbeat_at = _utc_now()
        row.interval_seconds = max(30, int(interval_seconds))
        row.last_error = (error or "")[:512] or None
        row.updated_at = _utc_now()
        db.add(row)

    try:
        _with_db(_write)
    except Exception:
        logger.debug("collector heartbeat write failed", exc_info=True)


def record_batch_start(
    *,
    run_id: str,
    batch_kind: str,
    managers: int,
    max_concurrent: int,
) -> None:
    def _write(db: Session) -> None:
        row = _ensure_collector_row(db)
        now = _utc_now()
        row.last_batch_run_id = run_id[:32]
        row.last_batch_started_at = now
        row.last_batch_finished_at = None
        row.last_batch_kind = batch_kind[:32]
        row.last_batch_managers = int(managers)
        row.last_batch_ok = None
        row.last_batch_warn = None
        row.last_batch_err = None
        row.last_batch_rows = None
        row.last_batch_wall_ms = None
        row.last_batch_cellular_buckets = None
        row.last_batch_cellular_errors = None
        row.last_heartbeat_at = now
        row.updated_at = now
        db.add(row)

    if batch_kind != "periodic":
        return
    try:
        _with_db(_write)
    except Exception:
        logger.debug("record_batch_start failed", exc_info=True)


def record_batch_finish(
    *,
    run_id: str,
    batch_kind: str,
    managers: int,
    ok: int,
    warn: int,
    err: int,
    rows: int,
    wall_ms: int,
    cellular_buckets: int,
    cellular_errors: int,
) -> None:
    def _write(db: Session) -> None:
        row = _ensure_collector_row(db)
        now = _utc_now()
        row.last_batch_run_id = run_id[:32]
        row.last_batch_finished_at = now
        row.last_batch_kind = batch_kind[:32]
        row.last_batch_managers = int(managers)
        row.last_batch_ok = int(ok)
        row.last_batch_warn = int(warn)
        row.last_batch_err = int(err)
        row.last_batch_rows = int(rows)
        row.last_batch_wall_ms = int(wall_ms)
        row.last_batch_cellular_buckets = int(cellular_buckets)
        row.last_batch_cellular_errors = int(cellular_errors)
        row.last_heartbeat_at = now
        row.updated_at = now
        db.add(row)

    if batch_kind != "periodic":
        return
    try:
        _with_db(_write)
    except Exception:
        logger.debug("record_batch_finish failed", exc_info=True)


def persist_log_event(
    level: str,
    component: str,
    message: str,
    *,
    detail: str = "",
    http_status: int | None = None,
    source: Literal["collector", "core"] = "collector",
    batch_kind: str | None = None,
) -> int | None:
    """
    Append one row to ``app_log_events`` for cross-process Logs UI visibility.

    Returns inserted row id, or None when skipped / failed.
    """
    comp = (component or "app")[:160]
    if comp not in _PERSIST_COMPONENTS:
        return None
    if comp == "sdwan_sync_batch" and batch_kind != "periodic":
        return None

    def _write(db: Session) -> int:
        rec = AppLogEvent(
            ts=_utc_now(),
            level=(level or "INFO").upper()[:12],
            component=comp,
            message=(message or "")[:4000],
            detail=(detail or "")[:4000],
            http_status=http_status,
            source=source[:16],
        )
        db.add(rec)
        db.flush()
        _prune_app_log_events_locked(db)
        return int(rec.id)

    try:
        rid: int = _with_db(_write)
        return rid
    except Exception:
        logger.debug("persist_log_event failed", exc_info=True)
        return None


def _prune_app_log_events_locked(db: Session) -> None:
    count = db.scalar(select(func.count()).select_from(AppLogEvent)) or 0
    excess = int(count) - _APP_LOG_EVENTS_MAX_ROWS
    if excess <= 0:
        return
    oldest_ids = list(
        db.scalars(
            select(AppLogEvent.id).order_by(AppLogEvent.id.asc()).limit(excess)
        )
    )
    if oldest_ids:
        db.execute(delete(AppLogEvent).where(AppLogEvent.id.in_(oldest_ids)))


def query_persisted_log_events(
    *,
    since_id: int = 0,
    limit: int = 200,
    pattern: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return (entries newest-first, tail_db_id)."""
    import fnmatch

    lim = max(1, min(int(limit), 500))
    sf = get_session_factory()
    with sf() as db:
        q = select(AppLogEvent).where(AppLogEvent.id > max(0, int(since_id)))
        rows = list(db.scalars(q.order_by(AppLogEvent.id.desc()).limit(lim * 4 if pattern else lim)))
        tail = db.scalar(select(func.max(AppLogEvent.id))) or 0

    pat = pattern.strip().lower() if isinstance(pattern, str) and pattern.strip() else None
    if pat:
        filtered: list[AppLogEvent] = []
        for rec in rows:
            hay = f"{rec.component} {rec.message} {rec.detail}".lower()
            if fnmatch.fnmatch(hay, pat):
                filtered.append(rec)
            if len(filtered) >= lim:
                break
        rows = filtered
    else:
        rows = rows[:lim]

    payload: list[dict[str, Any]] = []
    for rec in rows:
        payload.append(
            {
                "seq": 1_000_000_000 + int(rec.id),
                "db_id": int(rec.id),
                "ts": rec.ts.isoformat().replace("+00:00", "Z"),
                "level": rec.level,
                "component": rec.component,
                "message": rec.message,
                "detail": rec.detail,
                "http_status": rec.http_status,
                "source": rec.source,
            }
        )
    return payload, int(tail)


def search_persisted_log_events(pattern: str, *, limit: int = 500) -> tuple[list[dict[str, Any]], int]:
    return query_persisted_log_events(since_id=0, limit=limit, pattern=pattern)


def collector_state_from_row(row: CollectorStatus | None, *, interval_seconds: int) -> str:
    """Return ``alive``, ``stale``, or ``never``."""
    if row is None or row.last_heartbeat_at is None:
        return "never"
    hb = row.last_heartbeat_at
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=UTC)
    age = (_utc_now() - hb).total_seconds()
    interval = max(30, int(row.interval_seconds or interval_seconds))
    return "alive" if age <= 2 * interval else "stale"


def read_collector_status(*, default_interval_seconds: int) -> dict[str, Any]:
    """Structured payload for ``GET /api/v1/admin/collector-status``."""
    from terra.config import get_settings

    settings = get_settings()
    sf = get_session_factory()
    with sf() as db:
        row = db.get(CollectorStatus, _COLLECTOR_STATUS_ID)

    interval = int(row.interval_seconds if row and row.interval_seconds else default_interval_seconds)

    def _iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat().replace("+00:00", "Z")

    state = collector_state_from_row(row, interval_seconds=interval)
    return {
        "state": state,
        "service_name": (row.service_name if row else "collector") or "collector",
        "last_heartbeat_at_utc": _iso(row.last_heartbeat_at if row else None),
        "interval_seconds": interval,
        "last_error": (row.last_error if row else None) or None,
        "last_batch": {
            "run_id": (row.last_batch_run_id if row else None),
            "started_at_utc": _iso(row.last_batch_started_at if row else None),
            "finished_at_utc": _iso(row.last_batch_finished_at if row else None),
            "kind": (row.last_batch_kind if row else None),
            "managers": row.last_batch_managers if row else None,
            "ok": row.last_batch_ok if row else None,
            "warn": row.last_batch_warn if row else None,
            "err": row.last_batch_err if row else None,
            "rows": row.last_batch_rows if row else None,
            "wall_ms": row.last_batch_wall_ms if row else None,
            "cellular_buckets": row.last_batch_cellular_buckets if row else None,
            "cellular_errors": row.last_batch_cellular_errors if row else None,
        },
        "env": {
            "sdwan_background_sync": settings.sdwan_background_sync,
            "cellular_history_enabled": settings.cellular_history_enabled,
            "telemetry_push_enabled": settings.telemetry_push_enabled,
        },
    }
