"""Admin-only JSON feed for in-memory application logs (Logs page polling)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from terra.app_log_buffer import query_entries_merged
from terra.collector_status import read_collector_status
from terra.config import get_settings
from terra.deps import require_admin
from terra.models import User
from terra.schemas import (
    AppLogFeedResponse,
    AppLogItem,
    CollectorBatchSummary,
    CollectorEnvHints,
    CollectorStatusResponse,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-api"])


@router.get("/logs", response_model=AppLogFeedResponse)
def admin_logs_feed(
    _: Annotated[User, Depends(require_admin)],
    since: int = 0,
    since_db: int = 0,
    limit: int = 200,
    q: str | None = None,
) -> AppLogFeedResponse:
    """
    Return log entries: tail mode with ``since`` / ``since_db`` cursors, or merged search when ``q`` is set.
    Wildcards use ``fnmatch`` (``*`` / ``?``) over component + message + detail (case-insensitive).
    """
    lim = max(1, min(int(limit), 500))
    if q and q.strip():
        raw, tail_seq, tail_db = query_entries_merged(limit=lim, pattern=q.strip())
    else:
        raw, tail_seq, tail_db = query_entries_merged(
            since_seq=max(0, int(since)),
            since_db_id=max(0, int(since_db)),
            limit=lim,
        )
    entries: list[AppLogItem] = []
    for r in raw:
        source = str(r.get("source") or "memory")
        entries.append(
            AppLogItem(
                seq=int(r["seq"]),
                ts=str(r["ts"]),
                level=str(r["level"]),
                component=str(r["component"]),
                message=str(r["message"]),
                detail=str(r.get("detail") or ""),
                http_status=r.get("http_status"),
                source=source,
                db_id=int(r["db_id"]) if r.get("db_id") is not None else None,
            )
        )
    return AppLogFeedResponse(entries=entries, tail_seq=tail_seq, tail_db_id=tail_db)


@router.get("/collector-status", response_model=CollectorStatusResponse)
def admin_collector_status(
    _: Annotated[User, Depends(require_admin)],
) -> CollectorStatusResponse:
    """Background collector heartbeat and last periodic batch summary (Postgres singleton)."""
    settings = get_settings()
    payload = read_collector_status(default_interval_seconds=settings.sdwan_sync_interval_seconds)
    batch = payload.get("last_batch") or {}
    env = payload.get("env") or {}
    return CollectorStatusResponse(
        state=str(payload.get("state") or "never"),
        service_name=str(payload.get("service_name") or "collector"),
        last_heartbeat_at_utc=payload.get("last_heartbeat_at_utc"),
        interval_seconds=int(payload.get("interval_seconds") or settings.sdwan_sync_interval_seconds),
        last_error=payload.get("last_error"),
        last_batch=CollectorBatchSummary.model_validate(batch),
        env=CollectorEnvHints.model_validate(env),
    )
