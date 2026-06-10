"""Unit tests for parallel / two-pass SD-WAN inventory enrich."""

from __future__ import annotations

from typing import Any

import pytest

from terra.models import SdWanLinkStatus, SdWanManagerInstance
from terra_sdwan.sdwan_http import manager_credential_mode
from terra_sdwan.sdwan_sync import _enrich_rows_scoped_parallel


def _minimal_inst(**kwargs: Any) -> SdWanManagerInstance:
    return SdWanManagerInstance(
        id=1,
        user_id=1,
        display_name="lab",
        base_url="https://vmanage.example",
        auth_mode="jwt",
        credentials_encrypted="{}",
        link_status=SdWanLinkStatus.connected.value,
        verify_tls=True,
        **kwargs,
    )


def test_parallel_enrich_calls_worker_per_row(monkeypatch: pytest.MonkeyPatch) -> None:
    inst = _minimal_inst()
    rows = [({"deviceId": f"d{i}"}, "", "") for i in range(5)]
    seen: list[int] = []

    def fake_enrich_one(
        _sk: str,
        _inst: SdWanManagerInstance,
        row_tuple: tuple[dict[str, Any], str, str],
        _to: float,
    ) -> tuple[dict[str, Any], str, str]:
        seen.append(1)
        return (dict(row_tuple[0]), row_tuple[1], row_tuple[2])

    monkeypatch.setattr("terra_sdwan.sdwan_sync._enrich_one_scoped_row", fake_enrich_one)
    out = _enrich_rows_scoped_parallel("x" * 32, inst, rows, 8.0, 4, None, None)
    assert len(seen) == 5
    assert len(out) == 5


def test_sequential_enrich_single_worker_uses_one_client(monkeypatch: pytest.MonkeyPatch) -> None:
    inst = _minimal_inst()
    rows = [({"deviceId": "a"}, "", "")]
    opened = {"n": 0}

    class _DummyCtx:
        def __enter__(self) -> object:
            opened["n"] += 1
            return object()

        def __exit__(self, *args: object) -> None:
            return None

    def fake_open(_sk: str, _inst: SdWanManagerInstance, **_: object) -> _DummyCtx:
        return _DummyCtx()

    enrich_calls = {"n": 0}

    def fake_enrich(*_a: object, **_k: object) -> dict[str, Any]:
        enrich_calls["n"] += 1
        return {"deviceId": "a", "ok": True}

    monkeypatch.setattr("terra_sdwan.sdwan_sync.open_manager_http_client", fake_open)
    monkeypatch.setattr("terra_sdwan.sdwan_sync.enrich_inventory_row_for_sync", fake_enrich)
    out = _enrich_rows_scoped_parallel("x" * 32, inst, rows, 8.0, 1, None, None)
    assert opened["n"] == 1
    assert enrich_calls["n"] == 1
    assert out[0][0].get("ok") is True


def test_manager_credential_mode_reads_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    inst = _minimal_inst()

    def fake_decrypt(_sk: str, _blob: str) -> dict[str, Any]:
        return {"mode": "jwt", "token": "x"}

    monkeypatch.setattr("terra_sdwan.sdwan_http.decrypt_json", fake_decrypt)
    assert manager_credential_mode("k" * 32, inst) == "jwt"
