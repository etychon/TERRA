"""Pytest fixtures: configure env before importing the FastAPI app."""

from __future__ import annotations

import os
from collections.abc import Generator

# Must run before `terra` is imported so settings and DB bind correctly.
os.environ.setdefault("TERRA_SECRET_KEY", "unittest-terra-secret-key-32chars-min!")
os.environ.setdefault("TERRA_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TERRA_SDWAN_BACKGROUND_SYNC", "false")
os.environ.setdefault("TERRA_ADMIN_EMAIL", "admin@test.tld")
os.environ.setdefault("TERRA_ADMIN_PASSWORD", "TestAdminPass-long10")

import pytest
from fastapi.testclient import TestClient

import terra.config as terra_config
import terra.db as terra_db

terra_config.get_settings.cache_clear()
terra_db._engine = None
terra_db.SessionLocal = None

from terra.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c
