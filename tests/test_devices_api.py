"""Devices list API for React grid."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import select

from terra.db import get_session_factory
from terra.models import SdWanAuthMode, SdWanLinkStatus, SdWanManagerInstance, SyncedDevice, User
from terra.secret_store import encrypt_json


def _login(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200


def test_devices_list_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/me/devices").status_code == 401


def test_devices_list_pagination_and_hide_control(client: TestClient) -> None:
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
            display_name="GridTestMgr",
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
        edge = SyncedDevice(
            sdwan_instance_id=inst.id,
            source_device_uuid="edge-uuid-1",
            hostname="edge-alpha",
            device_type="vedge",
            reachability="reachable",
            state_changed_at_utc=now,
            synced_at_utc=now,
            raw_json='{"system-ip":"10.1.1.1"}',
        )
        ctrl = SyncedDevice(
            sdwan_instance_id=inst.id,
            source_device_uuid="vmanage-uuid",
            hostname="vmanage",
            device_type="vmanage",
            reachability="reachable",
            state_changed_at_utc=now,
            synced_at_utc=now,
            raw_json="{}",
        )
        db.add(edge)
        db.add(ctrl)
        db.commit()

    r = client.get("/api/v1/me/devices?limit=10&hide_control=true&q=GridTestMgr")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["hostname"] == "edge-alpha"
    assert "cluster" in body["items"][0]
    assert "has_cellular" in body["items"][0]

    r2 = client.get("/api/v1/me/devices?hide_control=false&q=GridTestMgr")
    assert r2.status_code == 200
    assert r2.json()["total"] == 2


def test_devices_list_search(client: TestClient) -> None:
    _login(client)
    r = client.get("/api/v1/me/devices?q=edge-alpha")
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_devices_list_sort_allowlist(client: TestClient) -> None:
    _login(client)
    r = client.get("/api/v1/me/devices?sort=not_a_column&dir=desc")
    assert r.status_code == 200
    assert "items" in r.json()
