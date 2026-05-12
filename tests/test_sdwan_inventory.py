"""SD-WAN inventory JSON shapes and Manager version parsing."""

from __future__ import annotations

import httpx

from terra.sdwan_client import _manager_version_from_server_json
from terra.sdwan_dataservice_rows import rows_from_dataservice_body
from terra.sdwan_sync import (
    _gather_inventory_with_tenant_scopes,
    fetch_device_inventory,
    fetch_tenant_list,
    normalize_inventory_row,
)


def test_rows_from_top_level_list() -> None:
    body = [{"uuid": "a", "host-name": "e1"}]
    assert rows_from_dataservice_body(body) == body


def test_rows_from_dict_data_objects() -> None:
    body = {"data": [{"uuid": "b", "host-name": "e2"}]}
    assert rows_from_dataservice_body(body) == [{"uuid": "b", "host-name": "e2"}]


def test_rows_from_dict_data_single_device_object() -> None:
    """Managers sometimes return one device as ``data: { ... }`` instead of a one-element list."""
    row = {
        "uuid": "solo-u",
        "host-name": "solo-edge",
        "deviceType": "vedge",
        "reachability": "reachable",
    }
    assert rows_from_dataservice_body({"data": row}) == [row]


def test_rows_from_client_server_dict_not_treated_as_device_row() -> None:
    body = {
        "header": {},
        "data": {"platformVersion": "20.15.2", "userMode": "provider", "CSRFToken": "x"},
    }
    assert rows_from_dataservice_body(body) == []


def test_rows_from_tabular_header() -> None:
    body = {
        "header": {
            "fields": [
                {"property": "uuid"},
                {"property": "host-name"},
                {"property": "reachability"},
            ]
        },
        "data": [
            ["u1", "edge-1", "reachable"],
            ["u2", "edge-2", "unreachable"],
        ],
    }
    rows = rows_from_dataservice_body(body)
    assert len(rows) == 2
    assert rows[0] == {"uuid": "u1", "host-name": "edge-1", "reachability": "reachable"}


def test_manager_version_first_row_then_second() -> None:
    body = {"data": [{"placeholder": True}, {"vmanageVersion": "20.18.1"}]}
    assert _manager_version_from_server_json(body) == "20.18.1"


def test_manager_version_from_tabular_client_server_shape() -> None:
    body = {
        "header": {
            "fields": [
                {"property": "version"},
                {"property": "other"},
            ]
        },
        "data": [["20.17.1", "x"]],
    }
    assert _manager_version_from_server_json(body) == "20.17.1"


def test_manager_version_nested_server() -> None:
    body = {"data": [], "server": {"compositeVersion": "17.17.0a"}}
    assert _manager_version_from_server_json(body) == "17.17.0a"


def test_manager_version_dict_data_object_platform_version() -> None:
    """Newer / multitenant ``client/server`` responses use ``data`` as a dict (not a list)."""
    body = {
        "header": {},
        "data": {
            "platformVersion": "20.15.2",
            "userMode": "provider",
            "CSRFToken": "x",
        },
    }
    assert _manager_version_from_server_json(body) == "20.15.2"


def test_fetch_tenant_list_403_is_non_multitenant() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        assert fetch_tenant_list(client, "https://vm.example.invalid") == []


def test_fetch_tenant_list_405_is_non_multitenant() -> None:
    """Single-tenant / CVD builds may respond 405 on ``GET /dataservice/tenant`` (endpoint not used)."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(405)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        assert fetch_tenant_list(client, "https://vm-cvd.example.invalid") == []


def test_fetch_tenant_list_400_is_non_multitenant() -> None:
    """Some managers return 400 when multitenant tenant listing is not applicable (treat as single-tenant)."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "not supported"})

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        assert fetch_tenant_list(client, "https://vm-400-tenant.example.invalid") == []


def test_gather_inventory_multitenant_device_singleton_dict() -> None:
    """Per-tenant ``/dataservice/device`` may return ``data`` as one object dict."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(200, json={"data": [{"tenantId": "t1", "name": "Alpha"}]})
        if request.method == "POST" and "/dataservice/tenant/t1/switch" in u:
            return httpx.Response(200, json={})
        if "/dataservice/device" in u:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "uuid": "d-solo",
                        "host-name": "mt-solo-edge",
                        "deviceType": "vedge",
                        "reachability": "reachable",
                    },
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        rows, err = _gather_inventory_with_tenant_scopes(client, "https://vm.example.invalid")
    assert err is False
    assert len(rows) == 1
    assert rows[0][1] == "t1"
    assert rows[0][0]["host-name"] == "mt-solo-edge"


def test_gather_inventory_multitenant_switches_per_tenant() -> None:
    state = {"tenant": ""}

    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"tenantId": "t1", "name": "Alpha"},
                        {"tenantId": "t2", "name": "Bravo"},
                    ],
                },
            )
        if request.method == "POST" and "/dataservice/tenant/t1/switch" in u:
            state["tenant"] = "t1"
            return httpx.Response(200, json={})
        if request.method == "POST" and "/dataservice/tenant/t2/switch" in u:
            state["tenant"] = "t2"
            return httpx.Response(200, json={})
        if "/dataservice/device" in u:
            if state["tenant"] == "t1":
                return httpx.Response(
                    200,
                    json={"data": [{"uuid": "d1", "host-name": "e1", "reachability": "reachable"}]},
                )
            if state["tenant"] == "t2":
                return httpx.Response(
                    200,
                    json={"data": [{"uuid": "d2", "host-name": "e2", "reachability": "reachable"}]},
                )
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        rows, err = _gather_inventory_with_tenant_scopes(client, "https://vm.example.invalid")
    assert err is False
    assert len(rows) == 2
    assert rows[0][1] == "t1" and rows[0][2] == "Alpha"
    assert rows[1][1] == "t2" and rows[1][2] == "Bravo"


def test_gather_inventory_multitenant_fallback_provider_when_all_switches_fail() -> None:
    """JWT CSRF is refreshed; if every tenant switch still fails, pull provider /device once."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if "/dataservice/client/server" in u:
            return httpx.Response(200, json={"data": {"CSRFToken": "csrf-fallback-test"}})
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(200, json={"data": [{"tenantId": "bad-tenant", "name": "X"}]})
        if request.method == "POST" and "/switch" in u:
            return httpx.Response(403, text="forbidden")
        if "/dataservice/device" in u and "switch" not in u:
            return httpx.Response(
                200,
                json={"data": [{"uuid": "prov-1", "host-name": "root-edge", "reachability": "reachable"}]},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer unit-test-token"},
    ) as client:
        rows, err = _gather_inventory_with_tenant_scopes(client, "https://vm.example.invalid")
    assert err is False
    assert len(rows) == 1
    assert rows[0][1] == "" and rows[0][2] == ""
    assert rows[0][0]["host-name"] == "root-edge"


def test_gather_inventory_multitenant_no_switchable_ids_errors() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/tenant"):
            return httpx.Response(200, json={"data": [{"name": "orphan-name-only"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        rows, err = _gather_inventory_with_tenant_scopes(client, "https://vm.example.invalid")
    assert rows == []
    assert err is True


def test_fetch_device_inventory_fallback_when_device_empty() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u.rstrip("/").endswith("/dataservice/device"):
            return httpx.Response(200, json={"data": []})
        if "/dataservice/system/device/vedges" in u:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "uuid": "vedge-1",
                            "host-name": "vEdge1",
                            "serialNumber": "SN9",
                            "reachability": "reachable",
                            "deviceModel": "vedge-cloud",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        rows = fetch_device_inventory(client, "https://vmanager.example.invalid")
    assert len(rows) == 1
    assert rows[0]["host-name"] == "vEdge1"


def test_normalize_inventory_row_serial_from_nested_object() -> None:
    row = {
        "uuid": "u-nest",
        "host-name": "edge-nest",
        "hardware": {"serialNumber": "SN-NEST-1"},
        "reachability": "reachable",
    }
    norm = normalize_inventory_row(row)
    assert norm["serial_number"] == "SN-NEST-1"


def test_normalize_inventory_row_serial_number_as_int() -> None:
    row = {
        "uuid": "u-int",
        "host-name": "edge-int",
        "serialNumber": 987654321,
        "deviceModel": "C8000V",
        "reachability": "reachable",
    }
    norm = normalize_inventory_row(row)
    assert norm["serial_number"] == "987654321"
    assert norm["model"] == "C8000V"


def test_normalize_inventory_row_prefers_device_model_over_cpu_platform() -> None:
    row = {
        "uuid": "u-arch",
        "host-name": "edge-arch",
        "serialNumber": "SNZ",
        "platform": "aarch64",
        "deviceModel": "C8000V",
        "reachability": "reachable",
    }
    norm = normalize_inventory_row(row)
    assert norm["model"] == "C8000V"


def test_normalize_inventory_row_skips_cpu_arch_in_model_field_when_pid_present() -> None:
    row = {
        "uuid": "u-pid",
        "host-name": "edge-pid",
        "model": "aarch64",
        "pid": "ISR4331/K9",
        "reachability": "reachable",
    }
    norm = normalize_inventory_row(row)
    assert norm["model"] == "ISR4331/K9"


def test_normalize_inventory_row_falls_back_to_platform_when_only_arch() -> None:
    row = {
        "uuid": "u-only",
        "host-name": "edge-only",
        "platform": "x86_64",
        "reachability": "reachable",
    }
    norm = normalize_inventory_row(row)
    assert norm["model"] == "x86_64"


def test_fetch_device_inventory_accepts_top_level_array() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"uuid": "x1", "host-name": "top", "reachability": "reachable"}],
        )

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        rows = fetch_device_inventory(client, "https://vm2.example.invalid")
    assert len(rows) == 1
    assert rows[0]["uuid"] == "x1"
