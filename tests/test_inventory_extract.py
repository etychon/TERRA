"""inventory_extract helpers — serial, geo, interfaces."""

from __future__ import annotations

from datetime import UTC, datetime

from terra.inventory_extract import (
    deep_find_serial,
    display_serial,
    extract_geo_lat_lng,
    extract_interface_rows,
    prepare_interface_detail_tables,
    utc_iso_for_json,
)


def test_utc_iso_for_json_z_suffix() -> None:
    dt = datetime(2024, 11, 5, 18, 14, 23, tzinfo=UTC)
    assert utc_iso_for_json(dt) == "2024-11-05T18:14:23Z"


def test_deep_find_serial_nested() -> None:
    row = {
        "uuid": "x",
        "lifeCycle": {"serialNumber": "SN-DEEP-9"},
        "host-name": "e1",
    }
    assert deep_find_serial(row) == "SN-DEEP-9"


def test_extract_geo_nested_geolocation() -> None:
    body = {"geoLocation": {"latitude": 48.8566, "longitude": 2.3522}}
    lat, lng = extract_geo_lat_lng(body)
    assert lat == 48.8566
    assert lng == 2.3522


def test_extract_interface_ip_skips_dash_for_secondary() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Cellular0/4/0",
                    "ip-address": "-",
                    "secondary-address": "100.64.0.12",
                    "vpn-id": "0",
                    "if-admin-status": "up",
                },
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["ip"] == "100.64.0.12"


def test_extract_interface_rows_from_device_interface() -> None:
    parsed = {
        "deviceInterface": [
            {
                "ifname": "GigabitEthernet1",
                "ip-address": "10.1.1.1",
                "vrfName": "default",
                "admin-state": "up",
            }
        ]
    }
    rows = extract_interface_rows(parsed)
    assert len(rows) == 1
    assert rows[0]["interface"] == "GigabitEthernet1"
    assert rows[0]["ip"] == "10.1.1.1"
    assert rows[0]["vrf"] == "default"


def test_extract_interface_rows_dict_mapping() -> None:
    parsed = {
        "interface": {
            "GigabitEthernet0/0": {"ip-address": "10.0.0.1"},
            "GigabitEthernet0/1": {"ipv4Address": "10.0.1.1", "vrfName": "1"},
        }
    }
    rows = extract_interface_rows(parsed)
    assert len(rows) == 2
    names = {r["interface"] for r in rows}
    assert names == {"GigabitEthernet0/0", "GigabitEthernet0/1"}


def test_extract_interface_rows_nested_running() -> None:
    parsed = {
        "running": {
            "interfaces": [
                {"ifname": "eth0", "ip-address": "1.1.1.1"},
            ]
        }
    }
    rows = extract_interface_rows(parsed)
    assert len(rows) == 1
    assert rows[0]["interface"] == "eth0"


def test_extract_interface_rows_vmanage_aliases() -> None:
    parsed = {
        "deviceInterface": [
            {"vpn-interface-name": "GE0/1", "interfaceIp": "10.2.2.2"},
        ]
    }
    rows = extract_interface_rows(parsed)
    assert len(rows) == 1
    assert rows[0]["interface"] == "GE0/1"
    assert rows[0]["ip"] == "10.2.2.2"


def test_display_serial_prefers_stored() -> None:
    assert display_serial("SN1", {"serialNumber": "SN2"}) == "SN1"


def test_prepare_interface_detail_tables_wan_before_lan() -> None:
    parsed = {
        "deviceInterface": [
            {
                "ifname": "GigabitEthernet2",
                "ip-address": "10.0.2.1",
                "vpn-id": "1",
                "if-admin-status": "up",
                "ipv4-prefix-length": "24",
            },
            {
                "ifname": "GigabitEthernet1",
                "ip-address": "10.0.0.1",
                "vpn-id": "0",
                "if-admin-status": "up",
                "ipv4-prefix-length": "24",
            },
        ]
    }
    primary, deferred = prepare_interface_detail_tables(extract_interface_rows(parsed))
    assert [r["interface"] for r in primary] == ["GigabitEthernet1", "GigabitEthernet2"]
    assert deferred == []


def test_prepare_interface_detail_tables_tunnels_last() -> None:
    parsed = {
        "deviceInterface": [
            {
                "ifname": "Tunnel1",
                "ip-address": "10.0.0.3",
                "vpn-id": "0",
                "if-admin-status": "up",
                "ipv4-prefix-length": "24",
            },
            {
                "ifname": "GigabitEthernet1",
                "ip-address": "10.0.0.1",
                "vpn-id": "0",
                "if-admin-status": "up",
                "ipv4-prefix-length": "24",
            },
        ]
    }
    primary, _ = prepare_interface_detail_tables(extract_interface_rows(parsed))
    assert [r["interface"] for r in primary] == ["GigabitEthernet1", "Tunnel1"]


def test_interface_ip_cidr_from_prefix_length() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Ethernet1",
                    "ip-address": "192.168.2.3",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                },
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["ip_cidr"] == "192.168.2.3/24"
    assert rows[0]["service_vpn"] == "WAN"


def test_prepare_interface_defers_admin_down_or_no_ip() -> None:
    parsed = {
        "deviceInterface": [
            {
                "ifname": "Gi0",
                "ip-address": "10.0.0.1",
                "vpn-id": "0",
                "if-admin-status": "2",
                "ipv4-prefix-length": "24",
            },
            {"ifname": "Gi1", "vpn-id": "0", "if-admin-status": "1"},
            {
                "ifname": "Gi2",
                "ip-address": "10.0.0.2",
                "vpn-id": "0",
                "if-admin-status": "1",
                "ipv4-prefix-length": "24",
            },
        ]
    }
    primary, deferred = prepare_interface_detail_tables(extract_interface_rows(parsed))
    assert [r["interface"] for r in primary] == ["Gi2"]
    assert {r["interface"] for r in deferred} == {"Gi0", "Gi1"}


def test_interface_line_state_uses_if_oper_state_ready_when_oper_unknown() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Ethernet1",
                    "ip-address": "10.0.0.1",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                    "if-oper-status": "0",
                    "if-oper-state-ready": "true",
                },
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["oper_status"] == "Up"
    assert rows[0]["oper_tone"] == "success"


def test_interface_line_state_if_oper_status_is_leaf_name_uses_ready_field() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Ethernet9",
                    "ip-address": "10.0.0.9",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                    "if-oper-status": "if-oper-state-ready",
                    "if-oper-state-ready": "true",
                },
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["oper_status"] == "Up"
    assert rows[0]["oper_tone"] == "success"


def test_interface_line_state_oper_state_ready_variant() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Ethernet1",
                    "ip-address": "10.0.0.1",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                    "oper-state": "oper-state-ready",
                },
            ]
        }
    )
    assert rows[0]["oper_status"] == "Up"
    assert rows[0]["oper_tone"] == "success"


def test_interface_line_state_unicode_hyphen_leaf_echo() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "EthernetU",
                    "ip-address": "10.0.0.7",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                    "if-oper-status": "if\u2011oper\u2011state\u2011ready",
                },
            ]
        }
    )
    assert rows[0]["oper_status"] == "Up"
    assert rows[0]["oper_tone"] == "success"


def test_interface_line_state_placeholder_without_ready_is_up() -> None:
    rows = extract_interface_rows(
        {
            "deviceInterface": [
                {
                    "ifname": "Ethernet8",
                    "ip-address": "10.0.0.8",
                    "ipv4-prefix-length": "24",
                    "vpn-id": "0",
                    "if-admin-status": "1",
                    "if-oper-status": "if-oper-state-ready",
                },
            ]
        }
    )
    assert rows[0]["oper_status"] == "Up"
    assert rows[0]["oper_tone"] == "success"
