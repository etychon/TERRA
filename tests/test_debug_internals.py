"""Lab-only /debug/* diagnostics (gated by TERRA_DEBUG_* settings)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from terra.config import get_settings
from terra.main import app as default_app
from terra.main import create_app


def test_default_app_has_no_debug_routes() -> None:
    with TestClient(default_app) as c:
        assert c.get("/debug/summary").status_code == 404


def test_debug_not_mounted_when_token_missing() -> None:
    s = get_settings().model_copy(update={"debug_expose_internals": True, "debug_token": None})
    with TestClient(create_app(s)) as c:
        assert c.get("/debug/summary", headers={"X-Terra-Debug-Token": "any"}).status_code == 404


def test_debug_summary_requires_matching_token() -> None:
    s = get_settings().model_copy(update={"debug_expose_internals": True, "debug_token": "correct-token"})
    with TestClient(create_app(s)) as c:
        assert c.get("/debug/summary").status_code == 403
        assert c.get("/debug/summary", headers={"X-Terra-Debug-Token": "wrong"}).status_code == 403
        r = c.get("/debug/summary", headers={"X-Terra-Debug-Token": "correct-token"})
        assert r.status_code == 200
        payload = r.json()
        assert "terra" in payload and "counts" in payload
        assert "database_url_redacted" in payload["terra"]
        assert "secret_key" not in payload["terra"]


def test_debug_accepts_query_token() -> None:
    s = get_settings().model_copy(update={"debug_expose_internals": True, "debug_token": "qtok"})
    with TestClient(create_app(s)) as c:
        r = c.get("/debug/summary", params={"debug_token": "qtok"})
        assert r.status_code == 200
