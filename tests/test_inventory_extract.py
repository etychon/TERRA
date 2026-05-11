"""inventory_extract helpers — serial, geo, interfaces."""

from __future__ import annotations

from datetime import UTC, datetime

from terra.inventory_extract import (
    deep_find_serial,
    display_serial,
    extract_geo_lat_lng,
    extract_interface_rows,
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


def test_display_serial_fallback_raw() -> None:
    assert display_serial("", {"serialNumber": "SN-FROM-RAW"}) == "SN-FROM-RAW"
