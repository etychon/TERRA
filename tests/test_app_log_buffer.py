"""In-memory application log ring buffer."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from terra import app_log_buffer as alb


@pytest.fixture(autouse=True)
def _reset_buffer() -> Generator[None, None, None]:
    alb.configure_ring_buffer(80)
    yield


def test_query_tail_returns_most_recent_when_since_zero() -> None:
    for i in range(9):
        alb.append_event("INFO", "terra.test_buffer", f"log-{i}")
    rows, tail = alb.query_entries(since_seq=0, limit=4)
    assert len(rows) == 4
    assert "log-8" in rows[0]["message"]
    assert "log-5" in rows[-1]["message"]
    assert tail >= rows[0]["seq"]


def test_query_incremental_since_seq() -> None:
    alb.append_event("INFO", "terra.a", "first")
    alb.append_event("INFO", "terra.b", "second")
    rows1, _tail = alb.query_entries(since_seq=0, limit=50)
    m = max(r["seq"] for r in rows1)
    alb.append_event("INFO", "terra.c", "third")
    rows2, _ = alb.query_entries(since_seq=m, limit=50)
    assert len(rows2) >= 1
    assert all(r["seq"] > m for r in rows2)
    assert any(r["message"] == "third" for r in rows2)


def test_search_entries_wildcard() -> None:
    alb.append_event("INFO", "terra.sdwan_sync", "inventory ok", detail="")
    alb.append_event("ERROR", "http", "GET /api/v1/x 500", detail="trace")
    rows, _ = alb.search_entries("*inventory*", limit=20)
    assert any("inventory" in r["message"] for r in rows)
