"""Governance events API and RBAC scoping."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from terra.db import get_session_factory
from terra.models import (
    SdWanAuthMode,
    SdWanGovernanceEvent,
    SdWanLinkStatus,
    SdWanManagerInstance,
    SyncedDevice,
    User,
)
from terra.secret_store import encrypt_json


def _login(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200


def _seed_governance_row(
    *,
    user_id: int,
    instance_name: str | None = None,
    hostname: str = "edge-gov",
) -> tuple[int, int, int]:
    if instance_name is None:
        instance_name = f"GovTestMgr-{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as db:
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user_id,
            display_name=instance_name,
            base_url="https://vmanager.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.flush()
        now = datetime.now(tz=UTC)
        dev = SyncedDevice(
            sdwan_instance_id=inst.id,
            source_device_uuid="gov-edge-uuid",
            hostname=hostname,
            device_type="vedge",
            reachability="reachable",
            state_changed_at_utc=now,
            synced_at_utc=now,
            raw_json='{"system-ip":"10.9.9.9"}',
        )
        db.add(dev)
        db.flush()
        ev = SdWanGovernanceEvent(
            sdwan_instance_id=inst.id,
            sdwan_tenant_id="default",
            sdwan_tenant_name="Default",
            user_id=user_id,
            stream_kind="alarm",
            source_key=f"alarm:test123-{uuid.uuid4().hex[:8]}",
            entry_time_utc=now,
            ingested_at_utc=now,
            severity_raw="Major",
            severity_norm="major",
            active=True,
            system_ip="10.9.9.9",
            site_id="site-1",
            synced_device_id=dev.id,
            title="Test alarm",
            summary="Synthetic alarm for tests",
            component="bfd",
            rule_name="BFD",
            loguser="",
            logfeature="",
            raw_json=json.dumps({"uuid": "test123"}),
            degraded=False,
        )
        db.add(ev)
        db.commit()
        return inst.id, dev.id, ev.id


def test_governance_events_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/me/governance/events").status_code == 401


def test_governance_events_list_and_device_scope(client: TestClient) -> None:
    _login(client)
    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        user_id = user.id
    _, device_id, event_id = _seed_governance_row(user_id=user_id)

    r = client.get("/api/v1/me/governance/events?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(item["id"] == event_id for item in body["items"])

    r2 = client.get(f"/api/v1/me/devices/{device_id}/events?limit=25&hours=24")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["total"] >= 1
    assert all(item.get("device_id") == device_id for item in body2["items"])

    r3 = client.get(f"/api/v1/me/governance/events/{event_id}")
    assert r3.status_code == 200
    assert r3.json()["title"] == "Test alarm"


def test_governance_events_facets(client: TestClient) -> None:
    _login(client)
    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        _seed_governance_row(user_id=user.id)

    r = client.get("/api/v1/me/governance/events/facets")
    assert r.status_code == 200
    data = r.json()
    assert "severities" in data and "streams" in data and "clusters" in data


def test_governance_events_page_renders(client: TestClient) -> None:
    _login(client)
    r = client.get("/events")
    assert r.status_code == 200
    assert "terra-events-grid-root" in r.text
    assert "events-grid.js" in r.text
