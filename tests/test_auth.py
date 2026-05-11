"""Authentication and RBAC API tests."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_login_page_renders(client: TestClient) -> None:
    r = client.get("/auth/login")
    assert r.status_code == 200
    assert "TERRA" in r.text
    assert "Sign in" in r.text
    assert "/static/brand/terra-logo.png" in r.text
    assert "terra-site-header" in r.text
    # Root-relative CSS avoids mixed-content blocking when the page is served over HTTPS.
    assert 'href="/static/css/terra-fonts.css"' in r.text
    assert 'href="/static/css/terra-auth.css"' in r.text
    assert "fonts.googleapis.com" not in r.text
    assert "terra-card-accent" in r.text
    assert "/static/brand/terra-logo.svg" in r.text
    assert "Telemetry for Edge and Remote Routable Assets" in r.text
    assert "Create an account" not in r.text
    assert "terra-sidebar" not in r.text


def test_public_register_disabled(client: TestClient) -> None:
    assert client.get("/auth/register").status_code == 404
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "x@y.z", "password": "longenough10"},
    )
    assert r.status_code == 403


def test_admin_users_requires_login(client: TestClient) -> None:
    assert client.get("/admin/users").status_code == 401


def test_admin_users_page_for_admin(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    assert client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    r = client.get("/admin/users")
    assert r.status_code == 200
    assert "User management" in r.text
    assert "/static/brand/terra-logo.png" in r.text
    assert "Add user" in r.text
    assert 'id="terra-show-add-user"' in r.text
    assert "terra-add-user-panel" in r.text
    assert "terra-sidebar" in r.text
    assert "Administration" in r.text


def test_api_login_and_me(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == email
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_admin_lists_users(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    client.post("/api/v1/auth/login", json={"email": email, "password": password})
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert any(u["email"] == email for u in body)


def test_admin_users_requires_auth(client: TestClient) -> None:
    c2 = TestClient(client.app)
    r = c2.get("/api/v1/admin/users")
    assert r.status_code == 401


def test_logout_clears_session(client: TestClient) -> None:
    email = os.environ["TERRA_ADMIN_EMAIL"]
    password = os.environ["TERRA_ADMIN_PASSWORD"]
    client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
