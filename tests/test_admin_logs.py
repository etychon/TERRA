"""Admin logs page and JSON API."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from terra.db import get_session_factory
from terra.main import app
from terra.models import SdWanAuthMode, SdWanLinkStatus, SdWanManagerInstance, User
from terra.secret_store import encrypt_json


def test_admin_logs_page_requires_login() -> None:
    with TestClient(app) as c:
        assert c.get("/admin/logs").status_code == 401


def test_admin_logs_page_renders_for_admin(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/admin/logs")
    assert r.status_code == 200
    assert "Application logs" in r.text
    assert "terra-logs.js" in r.text


def test_admin_logs_api_returns_json(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/api/v1/admin/logs?since=0&limit=20")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data and "tail_seq" in data
    assert "tail_db_id" in data
    assert isinstance(data["entries"], list)


def test_admin_collector_status_api(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/api/v1/admin/collector-status")
    assert r.status_code == 200
    data = r.json()
    assert data["state"] in ("alive", "stale", "never")
    assert "last_batch" in data
    assert "env" in data


def test_admin_logs_merged_persisted_batch_events(client: TestClient) -> None:
    from terra.collector_status import persist_log_event

    persist_log_event(
        "INFO",
        "sdwan_sync_batch",
        "Periodic SD-WAN sync batch completed (1 manager(s))",
        detail="run_id=test123 ok=1",
        source="collector",
        batch_kind="periodic",
    )
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/api/v1/admin/logs?since=0&since_db=0&limit=50")
    assert r.status_code == 200
    data = r.json()
    assert any(e.get("source") == "collector" for e in data["entries"])


def test_async_sdwan_sync_job_completes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cellular_calls: list[int] = []

    def fast_sync(
        _db: Any,
        _secret_key: str,
        _inst: Any,
        progress_notify: Callable[[str, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, str | None]:
        if progress_notify:
            progress_notify("saving", 88, "unit test")
        return (3, None)

    def fake_cellular(_db: Any, _secret_key: str, inst: Any) -> dict[str, Any]:
        cellular_calls.append(int(inst.id))
        return {"buckets_pushed": 2, "errors": 0, "devices_fetched": 1, "devices_seen": 1}

    monkeypatch.setattr("terra_sdwan.sdwan_sync_job_runner.sync_devices_for_instance", fast_sync)
    monkeypatch.setattr("terra_sdwan.sdwan_sync_job_runner.sync_cellular_history_best_effort", fake_cellular)

    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name=f"AsyncJobTest-{uuid.uuid4().hex[:8]}",
            base_url="https://vmanager-async-job.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        iid = inst.id

    r0 = client.post(f"/api/v1/me/sync-sdwan-devices/{iid}/async")
    assert r0.status_code == 200
    job_id = r0.json()["job_id"]
    assert job_id

    deadline = time.time() + 5.0
    last = None
    while time.time() < deadline:
        rj = client.get(f"/api/v1/me/sync-sdwan-jobs/{job_id}")
        assert rj.status_code == 200
        last = rj.json()
        if last.get("status") in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)

    assert last is not None
    assert last["status"] == "done"
    assert last["rows_touched"] == 3
    assert last["errors"] == 0
    assert cellular_calls == [iid]


def test_sync_sdwan_job_cancel_not_found(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.post("/api/v1/me/sync-sdwan-jobs/definitely-not-a-valid-job-id/cancel")
    assert r.status_code == 404


def test_async_sdwan_sync_job_cancelled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from terra_sdwan.sdwan_sync import SdWanSyncCancelled

    def cooperative_sync(
        _db: Any,
        _secret_key: str,
        _inst: Any,
        progress_notify: Callable[[str, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[int, str | None]:
        for _ in range(8000):
            if cancel_check and cancel_check():
                raise SdWanSyncCancelled()
            time.sleep(0.0005)
        return (1, None)

    monkeypatch.setattr("terra_sdwan.sdwan_sync_job_runner.sync_devices_for_instance", cooperative_sync)

    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name=f"CancelJobTest-{uuid.uuid4().hex[:8]}",
            base_url="https://vmanager-cancel-job.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        iid = inst.id

    r0 = client.post(f"/api/v1/me/sync-sdwan-devices/{iid}/async")
    assert r0.status_code == 200
    job_id = r0.json()["job_id"]
    assert job_id

    rc = client.post(f"/api/v1/me/sync-sdwan-jobs/{job_id}/cancel")
    assert rc.status_code == 200
    assert rc.json().get("accepted") is True

    deadline = time.time() + 8.0
    last = None
    while time.time() < deadline:
        rj = client.get(f"/api/v1/me/sync-sdwan-jobs/{job_id}")
        assert rj.status_code == 200
        last = rj.json()
        if last.get("status") == "cancelled":
            break
        time.sleep(0.03)

    assert last is not None
    assert last["status"] == "cancelled"
