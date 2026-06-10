"""Periodic / bulk SD-WAN manager sync batch: logging, isolation, bounded concurrency."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from terra.db import get_session_factory, init_db
from terra.models import SdWanManagerInstance, SyncedDevice, User
from terra.secret_store import encrypt_json
from terra_sdwan.sdwan_sync import sync_all_connected_managers, sync_user_sdwan_devices


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    from terra.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_sync_all_batch_logs_run_id_and_survives_one_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    sf = get_session_factory()
    with sf() as db:
        db.execute(delete(SyncedDevice))
        db.execute(delete(SdWanManagerInstance))
        db.commit()

    captured: list[tuple[str, str, str, str]] = []

    def fake_append(
        level: str,
        component: str,
        message: str,
        detail: str = "",
        http_status: int | None = None,
    ) -> None:
        captured.append((level, component, message, detail))

    monkeypatch.setattr("terra_sdwan.sdwan_sync.append_event", fake_append)

    def fake_sync(
        db: Session,
        secret_key: str,
        inst: SdWanManagerInstance,
        progress_notify: Callable[[str, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, str | None]:
        if "CRASH" in (inst.display_name or ""):
            raise RuntimeError("intentional worker failure")
        return (3, None)

    monkeypatch.setattr("terra_sdwan.sdwan_sync.sync_devices_for_instance", fake_sync)

    sf = get_session_factory()
    sk = os.environ["TERRA_SECRET_KEY"]
    blob = encrypt_json(sk, {"mode": "jwt", "token": "dummy.jwt.token"})
    now = datetime.now(tz=UTC)
    with sf() as db:
        admin = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        for label in ("BatchOkMgr", "BatchCRASH-Mgr"):
            db.add(
                SdWanManagerInstance(
                    user_id=admin.id,
                    display_name=label,
                    base_url=f"https://{uuid.uuid4().hex[:12]}.test.invalid",
                    auth_mode="jwt",
                    credentials_encrypted=blob,
                    verify_tls=True,
                    link_status="connected",
                    devices_last_sync_at_utc=now,
                )
            )
        db.commit()

    sync_all_connected_managers(sk)

    batch_events = [e for e in captured if e[1] == "sdwan_sync_batch"]
    assert len(batch_events) >= 4
    starts = [e for e in batch_events if "batch started" in e[2].lower()]
    ends = [e for e in batch_events if "batch completed" in e[2].lower()]
    assert len(starts) == 1
    assert len(ends) == 1
    assert "run_id=" in starts[0][3]
    assert "max_concurrent=" in starts[0][3]
    assert "batch_kind=periodic" in starts[0][3]
    assert "managers=2" in starts[0][3]
    assert any(e[0] == "ERROR" and "Manager sync failed" in e[2] for e in batch_events)
    assert any(e[0] == "INFO" and "Manager sync ok" in e[2] for e in batch_events)


def test_sync_user_bulk_uses_batch_component(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db()
    sf = get_session_factory()
    with sf() as db:
        db.execute(delete(SyncedDevice))
        db.execute(delete(SdWanManagerInstance))
        db.commit()

    captured: list[str] = []

    def fake_append(
        level: str,
        component: str,
        message: str,
        detail: str = "",
        http_status: int | None = None,
    ) -> None:
        if component == "sdwan_sync_batch":
            captured.append(detail)

    monkeypatch.setattr("terra_sdwan.sdwan_sync.append_event", fake_append)

    def fake_sync(
        db: Session,
        secret_key: str,
        inst: SdWanManagerInstance,
        progress_notify: Callable[[str, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, str | None]:
        return (1, None)

    monkeypatch.setattr("terra_sdwan.sdwan_sync.sync_devices_for_instance", fake_sync)

    sf = get_session_factory()
    sk = os.environ["TERRA_SECRET_KEY"]
    blob = encrypt_json(sk, {"mode": "jwt", "token": "dummy.jwt.token"})
    with sf() as db:
        admin = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        db.add(
            SdWanManagerInstance(
                user_id=admin.id,
                display_name="UserBulkMgr",
                base_url="https://user-bulk.test.invalid",
                auth_mode="jwt",
                credentials_encrypted=blob,
                verify_tls=True,
                link_status="connected",
            )
        )
        db.commit()
        uid = admin.id

    stats = sync_user_sdwan_devices(db, sk, uid)
    assert stats["managers"] == 1
    assert stats["rows_touched"] == 1
    assert stats["errors"] == 0
    assert any("batch_kind=user_bulk" in d for d in captured)
