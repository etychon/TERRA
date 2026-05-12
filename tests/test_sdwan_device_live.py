"""Live SD-WAN Manager device detail dataservice helpers."""

from __future__ import annotations

import httpx

from terra.sdwan_device_live import (
    fetch_live_device_dashboard,
    interface_row_from_live_api_dict,
    vmanage_device_id_candidates,
)


def test_vmanage_device_id_candidates_prefers_system_ip() -> None:
    inv = {"uuid": "u-1", "system-ip": "10.0.0.1"}
    assert vmanage_device_id_candidates(inv) == ["10.0.0.1", "u-1"]


def test_interface_row_from_live_api_dict_maps_ifname() -> None:
    row = interface_row_from_live_api_dict(
        {
            "ifname": "GigabitEthernet1",
            "ip-address": "192.168.1.1",
            "vpn-id": "0",
            "admin-state": "up",
            "oper-state": "up",
            "rx-kbps": "12",
        }
    )
    assert row["interface"] == "GigabitEthernet1"
    assert row["ip"] == "192.168.1.1"
    assert row["vpn_id"] == "0"
    assert row["service_vpn"] == "WAN"
    assert row["admin_status"] == "Up"
    assert "rx-kbps" in row["detail"]


def test_fetch_live_device_dashboard_interfaces() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if "dataservice/device/interface" in u and "deviceId=10.0.0.1" in u:
            return httpx.Response(
                200,
                json={"data": [{"ifname": "G0/0", "ip-address": "10.0.0.1", "vpn-id": "0", "admin-state": "up"}]},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(dispatch)
    with httpx.Client(transport=transport) as client:
        if_rows, sections, note = fetch_live_device_dashboard(
            client,
            "https://vmanager.example.invalid",
            {"system-ip": "10.0.0.1"},
        )
    assert len(if_rows) == 1
    assert if_rows[0]["interface"] == "G0/0"
    assert note is not None
    assert sections == []


def test_fetch_live_no_candidates() -> None:
    def _four_oh_four(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(_four_oh_four)) as client:
        if_rows, sections, note = fetch_live_device_dashboard(client, "https://vm.example", {})
    assert if_rows == []
    assert sections == []
    assert note is not None and "identifier" in note.lower()
