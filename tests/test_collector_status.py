"""Collector heartbeat, persisted logs, and admin status API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from terra.collector_status import (
    collector_state_from_row,
    persist_log_event,
    query_persisted_log_events,
    read_collector_status,
    record_batch_finish,
    touch_collector_heartbeat,
)
from terra.db import get_session_factory, init_db
from terra.models import AppLogEvent, CollectorStatus


@pytest.fixture(autouse=True)
def _fresh_collector_tables() -> None:
    init_db()
    sf = get_session_factory()
    with sf() as db:
        db.execute(delete(AppLogEvent))
        db.execute(delete(CollectorStatus))
        db.commit()


def test_touch_collector_heartbeat_creates_singleton() -> None:
    touch_collector_heartbeat(interval_seconds=300)
    sf = get_session_factory()
    with sf() as db:
        row = db.get(CollectorStatus, 1)
        assert row is not None
        assert row.interval_seconds == 300
        assert row.last_heartbeat_at is not None


def test_collector_state_stale_after_two_intervals() -> None:
    sf = get_session_factory()
    with sf() as db:
        row = CollectorStatus(
            id=1,
            service_name="collector",
            interval_seconds=60,
            last_heartbeat_at=datetime.now(tz=UTC) - timedelta(seconds=200),
        )
        db.add(row)
        db.commit()
        assert collector_state_from_row(row, interval_seconds=60) == "stale"


def test_persist_log_event_and_query() -> None:
    row_id = persist_log_event(
        "INFO",
        "sdwan_sync_batch",
        "Periodic SD-WAN sync batch started (1 manager(s))",
        detail="run_id=abc batch_kind=periodic",
        source="collector",
        batch_kind="periodic",
    )
    assert row_id is not None
    entries, tail = query_persisted_log_events(since_id=0, limit=10)
    assert tail >= 1
    assert len(entries) == 1
    assert entries[0]["component"] == "sdwan_sync_batch"
    assert entries[0]["source"] == "collector"
    assert entries[0]["seq"] == 1_000_000_000 + row_id


def test_persist_skips_user_bulk_batch_kind() -> None:
    skipped = persist_log_event(
        "INFO",
        "sdwan_sync_batch",
        "User bulk batch",
        detail="batch_kind=user_bulk",
        source="core",
        batch_kind="user_bulk",
    )
    assert skipped is None


def test_record_batch_finish_updates_status() -> None:
    touch_collector_heartbeat(interval_seconds=120)
    record_batch_finish(
        run_id="deadbeef",
        batch_kind="periodic",
        managers=2,
        ok=2,
        warn=0,
        err=0,
        rows=10,
        wall_ms=1500,
        cellular_buckets=4,
        cellular_errors=0,
    )
    payload = read_collector_status(default_interval_seconds=120)
    assert payload["last_batch"]["run_id"] == "deadbeef"
    assert payload["last_batch"]["rows"] == 10
    assert payload["last_batch"]["cellular_buckets"] == 4


def test_persist_log_prune_keeps_recent_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    import terra.collector_status as cs

    monkeypatch.setattr(cs, "_APP_LOG_EVENTS_MAX_ROWS", 5)
    for i in range(8):
        persist_log_event(
            "INFO",
            "collector",
            f"tick {i}",
            detail="",
            source="collector",
            batch_kind="periodic",
        )
    sf = get_session_factory()
    with sf() as db:
        count = db.scalar(select(func.count()).select_from(AppLogEvent)) or 0
    assert count <= 5
