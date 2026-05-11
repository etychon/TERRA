"""SD-WAN administration HTML and manager registration."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from terra.main import app
from terra.sdwan_client import ProbeResult


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
