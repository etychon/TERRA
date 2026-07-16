"""Synced SD-WAN device pages and manual sync API."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from terra.db import get_session_factory
from terra.models import SdWanAuthMode, SdWanLinkStatus, SdWanManagerInstance, SyncedDevice, User
from terra.routers.device_pages import _manager_field_groups_from_parsed
from terra.secret_store import encrypt_json


def _login(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200


def test_manager_field_groups_by_value_type() -> None:
    data = {
        "name": "edge",
        "count": 3,
        "ratio": 1.5,
        "ok": True,
        "nothing": None,
        "cfg": {"a": 1},
        "tags": [1, 2],
    }
    groups = _manager_field_groups_from_parsed(data)
    cats = [g["category"] for g in groups]
    assert cats == ["Objects", "Arrays", "Text", "Numbers", "Boolean", "Null"]
    flat = sum(len(g["fields"]) for g in groups)
    assert flat == len(data)


def test_map_devices_telemetry_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/me/map-devices-telemetry").status_code == 401


def test_live_sdwan_device_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/me/devices/1/live-sdwan").status_code == 401


def test_live_sdwan_device_not_found(client: TestClient) -> None:
    _login(client)
    r = client.get("/api/v1/me/devices/999999/live-sdwan")
    assert r.status_code == 404


def test_map_devices_telemetry_empty_when_no_geo_devices(client: TestClient) -> None:
    _login(client)
    r = client.get("/api/v1/me/map-devices-telemetry")
    assert r.status_code == 200
    assert r.json() == {"devices": []}


def test_compare_requires_two_ids(client: TestClient) -> None:
    _login(client)
    assert client.get("/devices/compare?ids=1").status_code == 400


def test_detail_not_found(client: TestClient) -> None:
    _login(client)
    assert client.get("/devices/999999").status_code == 404


def test_devices_inventory_page(client: TestClient) -> None:
    _login(client)
    r = client.get("/devices")
    assert r.status_code == 200
    assert "terra-devices-grid-root" in r.text
    assert "/static/dist/devices-grid.js" in r.text
    assert "Devices across SD-WAN managers" in r.text
    assert "terra-sidebar-link" in r.text and "Devices" in r.text


def test_sync_api_returns_stats(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _login(client)

    @contextmanager
    def fake_open(secret_key: str, inst: SdWanManagerInstance) -> Iterator[Any]:
        class C:
            headers = httpx.Headers({})

            def get(self, url: str, *_a: Any, **_k: Any) -> httpx.Response:
                u = str(url)
                if "/dataservice/tenant" in u and "switch" not in u:
                    return httpx.Response(404)
                if "/dataservice/client/server" in u:
                    return httpx.Response(200, json={"data": [{"vmanageVersion": "20.10.0"}]})
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "uuid": "inv-test-1",
                                "host-name": "edge-test-1",
                                "serialNumber": "SN-TEST-1",
                                "deviceModel": "ISR1100-4G",
                                "softwareVersion": "17.9.4a",
                                "deviceType": "vedge",
                                "reachability": "reachable",
                            },
                        ],
                    },
                )

            def post(self, *_a: Any, **_k: Any) -> httpx.Response:
                return httpx.Response(404)

        yield C()

    monkeypatch.setattr("terra_sdwan.sdwan_sync.open_manager_http_client", fake_open)

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name="InvTestMgr",
            base_url="https://vmanager.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        manager_id = inst.id

    r = client.post("/api/v1/me/sync-sdwan-devices")
    assert r.status_code == 200
    body = r.json()
    assert body["managers"] >= 1
    assert body["rows_touched"] >= 1

    with sf() as db:
        n = db.execute(
            select(SyncedDevice).where(
                SyncedDevice.sdwan_instance_id == manager_id,
                SyncedDevice.source_device_uuid == "inv-test-1",
                SyncedDevice.sdwan_tenant_id == "",
            )
        ).scalar_one_or_none()
        assert n is not None
        did = n.id

    d = client.get(f"/devices/{did}")
    assert d.status_code == 200
    assert "edge-test-1" in d.text
    assert 'class="terra-manager-fields"' in d.text
    assert "terra-sync-now" in d.text


def test_device_sync_async_requires_auth() -> None:
    from terra.main import app

    with TestClient(app) as c:
        assert c.post("/api/v1/me/devices/1/sync/async").status_code == 401


def test_device_sync_async_queues_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from terra_sdwan import sdwan_sync_job_runner as runner

    _login(client)
    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name="DeviceSyncMgr",
            base_url="https://vmanager.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.flush()
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        dev = SyncedDevice(
            sdwan_instance_id=inst.id,
            source_device_uuid="edge-sync-1",
            hostname="edge-sync",
            device_type="vedge",
            reachability="reachable",
            state_changed_at_utc=now,
            synced_at_utc=now,
            raw_json='{"uuid":"edge-sync-1","system-ip":"10.1.2.3"}',
        )
        db.add(dev)
        db.commit()
        device_id = dev.id

    ran: list[int] = []

    def fake_run(job_id: str, user_id: int, device_id_arg: int, secret_key: str) -> None:
        ran.append(device_id_arg)
        snap = runner.get_job(job_id, user_id)
        assert snap is not None

    monkeypatch.setattr(runner, "_run_device_job", fake_run)

    r = client.post(f"/api/v1/me/devices/{device_id}/sync/async")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert job_id

    for _ in range(30):
        if ran:
            break
        time.sleep(0.05)
    assert ran == [device_id]
