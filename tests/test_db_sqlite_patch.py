"""SQLite lightweight migrations after model changes."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from terra.db import _sqlite_add_missing_columns


def test_sqlite_patch_adds_devices_last_sync_column(tmp_path: Path) -> None:
    dbfile = tmp_path / "legacy.db"
    url = f"sqlite:///{dbfile}"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE sdwan_manager_instances ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL)"
            )
        )
    _sqlite_add_missing_columns(eng)
    with eng.connect() as conn:
        names = {row[1] for row in conn.execute(text("PRAGMA table_info(sdwan_manager_instances)")).fetchall()}
    assert "devices_last_sync_at_utc" in names
