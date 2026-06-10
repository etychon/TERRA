"""SD-WAN credential scope classification (multitenant vs single-tenant heuristics)."""

from __future__ import annotations

import httpx

from terra_sdwan.sdwan_credential_scope import (
    credential_scope_public_label,
    detect_credential_scope,
)


def test_public_label_none() -> None:
    assert "Verify" in credential_scope_public_label(None)


def test_detect_non_multitenant_empty_tenant_list() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        if str(request.url).rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(403)
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "non_multitenant"
    assert det.switchable_count == 0


def test_detect_multitenant_provider_two_switches() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"tenantId": "t1", "name": "A"},
                        {"tenantId": "t2", "name": "B"},
                    ],
                },
            )
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "csrf-x"}})
        if request.method == "POST" and "/dataservice/tenant/t1/switch" in u:
            return httpx.Response(200, json={})
        if request.method == "POST" and "/dataservice/tenant/t2/switch" in u:
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "multitenant_provider"
    assert det.switch_ok_distinct == 2


def test_detect_multitenant_tenant_token_one_switch_only() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"tenantId": "t1", "name": "A"},
                        {"tenantId": "t2", "name": "B"},
                    ],
                },
            )
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "csrf-x"}})
        if request.method == "POST" and "/dataservice/tenant/t1/switch" in u:
            return httpx.Response(200, json={})
        if request.method == "POST" and "/dataservice/tenant/t2/switch" in u:
            return httpx.Response(403, text="nope")
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "multitenant_tenant_token"
    assert det.switch_ok_distinct == 1


def test_detect_multitenant_provider_switches_fail_device_ok() -> None:
    """Aligns with sync fallback: provider inventory without tenant switch."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "csrf-fallback-test"}})
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"tenantId": "bad", "name": "X"},
                        {"tenantId": "bad2", "name": "Y"},
                    ],
                },
            )
        if request.method == "POST" and "/switch" in u:
            return httpx.Response(403, text="forbidden")
        if "/dataservice/device" in u:
            return httpx.Response(
                200,
                json={"data": [{"uuid": "p1", "host-name": "root-edge", "reachability": "reachable"}]},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "multitenant_provider"
    assert det.switch_ok_distinct == 0


def test_detect_multitenant_ambiguous_one_tenant_switch_ok() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(200, json={"data": [{"tenantId": "only", "name": "Only"}]})
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "csrf-x"}})
        if request.method == "POST" and "/dataservice/tenant/only/switch" in u:
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "multitenant_ambiguous"


def test_detect_unknown_tenant_rows_without_switch_id() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(200, json={"data": [{"name": "orphan-name-only"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        det = detect_credential_scope(client, "https://vm.example.invalid")
    assert det.code == "unknown"
