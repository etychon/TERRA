"""SD-WAN inventory JSON shapes and Manager version parsing."""

from __future__ import annotations

import httpx

from terra.sdwan_client import _manager_version_from_server_json
from terra.sdwan_dataservice_rows import rows_from_dataservice_body
from terra.sdwan_sync import fetch_device_inventory, normalize_inventory_row


def test_rows_from_top_level_list() -> None:
    body = [{"uuid": "a", "host-name": "e1"}]
    assert rows_from_dataservice_body(body) == body


def test_rows_from_dict_data_objects() -> None:
    body = {"data": [{"uuid": "b", "host-name": "e2"}]}
    assert rows_from_dataservice_body(body) == [{"uuid": "b", "host-name": "e2"}]


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
