"""VictoriaMetrics sparse gauge import (Prometheus text)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from terra.config import get_settings


def test_push_skips_when_no_vm_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TERRA_VICTORIAMETRICS_URL", raising=False)
    monkeypatch.setenv("TERRA_TELEMETRY_PUSH_ENABLED", "true")
    get_settings.cache_clear()
    from terra.telemetry_vm import push_sdwan_sync_batch_telemetry

    push_sdwan_sync_batch_telemetry(results=[], batch_kind="periodic", _run_id="x")
    get_settings.cache_clear()


def test_push_posts_prometheus_import(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[str] = []
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        bodies.append(request.content)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("TERRA_VICTORIAMETRICS_URL", "http://vm.test.invalid:8428")
    monkeypatch.setenv("TERRA_TELEMETRY_PUSH_ENABLED", "true")
    get_settings.cache_clear()

    orig_client = httpx.Client

    def client_with_transport(**kwargs: Any) -> httpx.Client:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return orig_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", client_with_transport)
    from terra.telemetry_vm import push_sdwan_sync_batch_telemetry

    try:
        push_sdwan_sync_batch_telemetry(
            results=[
                {
                    "instance_id": 7,
                    "cluster": 'Edge"Lab',
                    "rows": 12,
                    "error": None,
                }
            ],
            batch_kind="periodic",
            _run_id="run1",
        )
    finally:
        get_settings.cache_clear()

    assert len(paths) == 1
    assert paths[0].endswith("/api/v1/import/prometheus")
    body = bodies[0].decode("utf-8")
    assert "terra_inventory_device_count" in body
    assert "terra_sdwan_sync_instance_ok" in body
    assert "terra_sdwan_batch_managers_processed" in body
    assert "manager_id=\"7\"" in body
    assert "batch_kind=\"periodic\"" in body
