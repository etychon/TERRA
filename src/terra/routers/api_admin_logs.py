"""Admin-only JSON feed for in-memory application logs (Logs page polling)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from terra.app_log_buffer import query_entries, search_entries
from terra.deps import require_admin
from terra.models import User
from terra.schemas import AppLogFeedResponse, AppLogItem

router = APIRouter(prefix="/api/v1/admin", tags=["admin-api"])


@router.get("/logs", response_model=AppLogFeedResponse)
def admin_logs_feed(
    _: Annotated[User, Depends(require_admin)],
    since: int = 0,
    limit: int = 200,
    q: str | None = None,
) -> AppLogFeedResponse:
    """
    Return log entries: tail mode with ``since`` (``seq`` cursor), or full-buffer search when ``q`` is set.
    Wildcards use ``fnmatch`` (``*`` / ``?``) over component + message + detail (case-insensitive).
    """
    lim = max(1, min(int(limit), 500))
    if q and q.strip():
        raw, tail = search_entries(q.strip(), limit=lim)
    else:
        raw, tail = query_entries(since_seq=max(0, int(since)), limit=lim, pattern=None)
    entries = [AppLogItem.model_validate(r) for r in raw]
    return AppLogFeedResponse(entries=entries, tail_seq=tail)
