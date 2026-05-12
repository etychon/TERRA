"""SD-WAN administration HTML and manager registration."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.db import get_session_factory
from terra.main import app
from terra.models import SdWanAuthMode, SdWanLinkStatus, SdWanManagerInstance, User
from terra.sdwan_client import ProbeResult
from terra.secret_store import encrypt_json


def _dummy_jwt() -> str:
    h = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps({"exp": 2000000000}).encode()).decode().rstrip("=")
    return f"{h}.{p}.x"


def test_login_page_has_no_sidebar(client: TestClient) -> None:
    r = client.get("/auth/login")
    assert r.status_code == 200
    assert "terra-sidebar" not in r.text


def test_home_shows_sidebar_and_administration(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/")
    assert r.status_code == 200
    assert "terra-sidebar" in r.text
    assert "Devices" in r.text
    assert "Administration" in r.text


def test_sdwan_page_requires_login() -> None:
    """Isolated client so prior tests in this module cannot leave a browser session."""
    with TestClient(app) as c:
        assert c.get("/administration/sd-wan").status_code == 401


def test_sdwan_page_renders_and_add_jwt_mocked(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/administration/sd-wan")
    assert r.status_code == 200
    assert "Cisco Catalyst SD-WAN Manager" in r.text
    assert "JWT" in r.text
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m
    csrf = m.group(1)
    tok = _dummy_jwt()

    def fake_probe_jwt(base_url: str, token: str, *, verify_tls: bool) -> ProbeResult:
        assert token == tok
        assert base_url.startswith("https://")
        return ProbeResult(True, "Connected with JWT.", 200, manager_version="20.16", expires_at=None)

    monkeypatch.setattr("terra.routers.sdwan_pages.probe_jwt", fake_probe_jwt)
    monkeypatch.setattr("terra.routers.sdwan_pages._detect_and_store_credential_scope", lambda *_a, **_k: None)
    label = f"Lab vManage {uuid.uuid4().hex[:8]}"
    r2 = client.post(
        "/administration/sd-wan/add",
        data={
            "csrf_token": csrf,
            "display_name": label,
            "base_url": "https://vmanager.example.invalid",
            "auth_mode": "jwt",
            "jwt_token": tok,
            "sdwan_username": "",
            "sdwan_password": "",
            "verify_tls": "on",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303
    r3 = client.get("/administration/sd-wan")
    assert r3.status_code == 200
    assert label in r3.text
    assert "connected" in r3.text
    assert "Last inventory sync" in r3.text
    assert "Edge devices" in r3.text
    assert "Credential scope" in r3.text
    assert "terra-sdwan-sync-inline-row" in r3.text


def test_sync_single_sdwan_cluster_requires_login() -> None:
    with TestClient(app) as c:
        assert c.post("/api/v1/me/sync-sdwan-devices/1").status_code == 401


def test_sync_single_sdwan_cluster_not_found(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.post("/api/v1/me/sync-sdwan-devices/999999")
    assert r.status_code == 404


def test_sync_single_sdwan_cluster_ok(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200

    def fake_sync(db: Session, secret_key: str, inst: SdWanManagerInstance, **_: Any) -> tuple[int, str | None]:
        inst.devices_last_sync_at_utc = datetime.now(tz=UTC)
        return (2, None)

    monkeypatch.setattr("terra.routers.api_me.sync_devices_for_instance", fake_sync)

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name="SyncOneTestMgr",
            base_url="https://vmanager-sync-one.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        iid = inst.id

    r = client.post(f"/api/v1/me/sync-sdwan-devices/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["managers"] == 1
    assert body["rows_touched"] == 2
    assert body["errors"] == 0
    assert body.get("last_sync_at_utc")
    assert body.get("error_detail") in (None, "")


def test_sync_single_sdwan_cluster_error_includes_error_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200

    def fake_sync(db: Session, secret_key: str, inst: SdWanManagerInstance, **_: Any) -> tuple[int, str | None]:
        return (0, "device inventory HTTP 403 (JWT may lack Device / Configuration read scope)")

    monkeypatch.setattr("terra.routers.api_me.sync_devices_for_instance", fake_sync)

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name=f"SyncErrTestMgr-{uuid.uuid4().hex[:8]}",
            base_url="https://vmanager-sync-err.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        iid = inst.id

    r = client.post(f"/api/v1/me/sync-sdwan-devices/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == 1
    assert body["rows_touched"] == 0
    assert "403" in (body.get("error_detail") or "")


def test_sync_single_sdwan_multitenant_empty_inventory_error_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200

    monkeypatch.setattr(
        "terra.sdwan_sync._gather_inventory_with_tenant_scopes",
        lambda _c, _u, **_kw: ([], True),
    )
    monkeypatch.setattr("terra.sdwan_sync.read_manager_version", lambda _c, _u, **_kw: None)

    sf = get_session_factory()
    with sf() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        blob = encrypt_json(
            os.environ["TERRA_SECRET_KEY"],
            {"mode": SdWanAuthMode.jwt.value, "token": "dummy.jwt.token"},
        )
        inst = SdWanManagerInstance(
            user_id=user.id,
            display_name=f"SyncMtEmpty-{uuid.uuid4().hex[:8]}",
            base_url="https://vmanager-mt-empty.test.invalid",
            auth_mode=SdWanAuthMode.jwt.value,
            credentials_encrypted=blob,
            verify_tls=True,
            link_status=SdWanLinkStatus.connected.value,
        )
        db.add(inst)
        db.commit()
        iid = inst.id

    r = client.post(f"/api/v1/me/sync-sdwan-devices/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == 1
    assert "Multitenant inventory" in (body.get("error_detail") or "")
