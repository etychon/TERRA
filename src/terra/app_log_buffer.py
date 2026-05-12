"""In-memory ring buffer for operator-visible application logs (admin Logs UI + API)."""

from __future__ import annotations

import fnmatch
import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_lock = threading.RLock()
_buffer: deque[_AppLogRecord] | None = None
_seq = 0


@dataclass(frozen=True)
class _AppLogRecord:
    seq: int
    ts: datetime
    level: str
    component: str
    message: str
    detail: str
    http_status: int | None


def configure_ring_buffer(maxlen: int = 3000) -> None:
    """Initialize or resize the buffer (called from app lifespan)."""
    global _buffer
    with _lock:
        if _buffer is None or _buffer.maxlen != maxlen:
            _buffer = deque(maxlen=maxlen)


def _ensure_buffer() -> deque[_AppLogRecord]:
    global _buffer
    with _lock:
        if _buffer is None:
            _buffer = deque(maxlen=3000)
        return _buffer


def append_event(
    level: str,
    component: str,
    message: str,
    *,
    detail: str = "",
    http_status: int | None = None,
) -> None:
    """Append one structured row (thread-safe)."""
    global _seq
    buf = _ensure_buffer()
    lvl = (level or "INFO").upper()[:12]
    comp = (component or "app")[:160]
    msg = (message or "")[:4000]
    det = (detail or "")[:4000]
    with _lock:
        _seq += 1
        rec = _AppLogRecord(
            seq=_seq,
            ts=datetime.now(tz=UTC),
            level=lvl,
            component=comp,
            message=msg,
            detail=det,
            http_status=http_status,
        )
        buf.append(rec)


def _matches_pattern(rec: _AppLogRecord, pattern: str) -> bool:
    hay = f"{rec.component} {rec.message} {rec.detail}".lower()
    pat = pattern.strip().lower()
    if not pat:
        return True
    return fnmatch.fnmatch(hay, pat)


def query_entries(
    *,
    since_seq: int = 0,
    limit: int = 200,
    pattern: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Return (entries, tail_seq) where entries are **newest-first** dicts for JSON (most recent at index 0).
    ``since_seq``: only records with ``seq > since_seq``.
    ``pattern``: case-insensitive ``fnmatch`` (``*`` / ``?``) against component + message + detail.
    """
    buf = _ensure_buffer()
    lim = max(1, min(int(limit), 500))
    pat = pattern.strip() if isinstance(pattern, str) else None
    with _lock:
        tail = _seq
        rows = list(buf)
    out: list[_AppLogRecord] = []
    if pat:
        for rec in rows:
            if rec.seq <= since_seq:
                continue
            if _matches_pattern(rec, pat):
                out.append(rec)
        out = out[-lim:]
    else:
        if since_seq <= 0:
            out = list(rows)[-lim:]
        else:
            for rec in rows:
                if rec.seq > since_seq:
                    out.append(rec)
                if len(out) >= lim:
                    break
    out.reverse()
    payload: list[dict[str, Any]] = []
    for rec in out:
        payload.append(
            {
                "seq": rec.seq,
                "ts": rec.ts.isoformat().replace("+00:00", "Z"),
                "level": rec.level,
                "component": rec.component,
                "message": rec.message,
                "detail": rec.detail,
                "http_status": rec.http_status,
            }
        )
    return payload, tail


def search_entries(pattern: str, *, limit: int = 500) -> tuple[list[dict[str, Any]], int]:
    """Scan newest-first matches (full buffer), return newest-first slice up to ``limit``."""
    buf = _ensure_buffer()
    lim = max(1, min(int(limit), 500))
    pat = pattern.strip().lower()
    with _lock:
        tail = _seq
        rows = list(reversed(buf))
    picked: list[_AppLogRecord] = []
    for rec in rows:
        if _matches_pattern(rec, pat):
            picked.append(rec)
            if len(picked) >= lim:
                break
    payload: list[dict[str, Any]] = []
    for rec in picked:
        payload.append(
            {
                "seq": rec.seq,
                "ts": rec.ts.isoformat().replace("+00:00", "Z"),
                "level": rec.level,
                "component": rec.component,
                "message": rec.message,
                "detail": rec.detail,
                "http_status": rec.http_status,
            }
        )
    return payload, tail


class RingBufferLoggingHandler(logging.Handler):
    """Captures ``logging`` records into the ring buffer (no network I/O)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            append_event(
                record.levelname,
                record.name,
                msg,
                detail="",
                http_status=getattr(record, "http_status", None),
            )
        except Exception:
            self.handleError(record)


def install_ring_buffer_logging(*, buffer_maxlen: int = 3000) -> None:
    """Attach handler to the ``terra`` logger tree (idempotent)."""
    configure_ring_buffer(buffer_maxlen)
    log = logging.getLogger("terra")
    # Avoid duplicate handlers on reload (e.g. tests).
    for h in log.handlers:
        if isinstance(h, RingBufferLoggingHandler):
            return
    h = RingBufferLoggingHandler()
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(h)


def log_http_request(*, method: str, path: str, status_code: int, detail: str = "") -> None:
    """Structured HTTP line for the Logs UI (component ``http``)."""
    m = (method or "?")[:16].upper()
    p = (path or "")[:512]
    lvl = "ERROR" if status_code >= 500 else "WARNING" if status_code >= 400 else "INFO"
    det = (detail or "")[:4000]
    append_event(lvl, "http", f"{m} {p}", detail=det, http_status=status_code)
