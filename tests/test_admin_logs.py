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
    assert isinstance(data["entries"], list)


def test_async_sdwan_sync_job_completes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("terra.sdwan_sync_job_runner.sync_devices_for_instance", fast_sync)

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


def test_sync_sdwan_job_cancel_not_found(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.post("/api/v1/me/sync-sdwan-jobs/definitely-not-a-valid-job-id/cancel")
    assert r.status_code == 404


def test_async_sdwan_sync_job_cancelled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from terra.sdwan_sync import SdWanSyncCancelled

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

    monkeypatch.setattr("terra.sdwan_sync_job_runner.sync_devices_for_instance", cooperative_sync)

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
