"""EIOLTE cellular history request builder, parser, and dedupe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from terra.inventory_extract import device_has_cellular_capability, system_ip_from_inventory
from terra_sdwan.sdwan_cellular_history import (
    CellularBucket,
    build_eiolte_unique_aggregation_body,
    dedupe_buckets,
    filter_buckets_after_cursor,
    merge_buckets_into_cursor,
    parse_eiolte_buckets,
    post_eiolte_history,
)


def test_build_eiolte_body_has_aggregation_and_vdevice_name() -> None:
    body = build_eiolte_unique_aggregation_body("10.1.2.3", 24, histogram_minutes=15)
    assert "aggregation" in body
    assert body["aggregation"]["histogram"]["interval"] == 15
    rules = body["query"]["rules"]
    fields = {r["field"]: r for r in rules}
    assert fields["vdevice_name"]["value"] == ["10.1.2.3"]
    assert fields["entry_time"]["operator"] == "last_n_hours"
    assert fields["rssi"]["operator"] == "not_equal"


def test_build_eiolte_omit_ps_domain() -> None:
    body = build_eiolte_unique_aggregation_body("10.0.0.1", 2, omit_ps_domain=True)
    fields = {r["field"] for r in body["query"]["rules"]}
    assert "ps_domain" not in fields


def test_parse_eiolte_buckets_from_fixture() -> None:
    payload = {
        "header": {"fields": [{"property": "entry_time"}, {"property": "rssi"}, {"property": "rsrp"}]},
        "data": [
            {
                "entry_time": 1700000000000,
                "rssi": -75.0,
                "rsrp": -95.0,
                "rsrq": -12.0,
                "slot": "0",
                "active_sim": "1",
                "count": 3,
            },
            {"entry_time": 1700000180000, "rssi": -80, "slot": "0", "active_sim": "1"},
        ],
    }
    buckets = parse_eiolte_buckets(payload)
    assert len(buckets) == 2
    assert buckets[0].rssi == -75.0
    assert buckets[0].slot == "0"


def test_dedupe_buckets_keeps_last_per_key() -> None:
    a = CellularBucket(1000, -90.0, None, -70.0, "0", "1")
    b = CellularBucket(1000, -95.0, None, -75.0, "0", "1")
    c = CellularBucket(2000, -88.0, None, -72.0, "0", "1")
    out = dedupe_buckets([a, b, c])
    assert len(out) == 2
    assert out[0].rssi == -75.0
    assert out[1].rssi == -72.0


def test_filter_buckets_after_cursor() -> None:
    buckets = [
        CellularBucket(1000, None, None, -70.0, "0", "1"),
        CellularBucket(2000, None, None, -72.0, "0", "1"),
    ]
    cursor = {"0:1": 1500}
    kept = filter_buckets_after_cursor(buckets, cursor)
    assert len(kept) == 1
    assert kept[0].entry_time_ms == 2000


def test_merge_cursor_updates_max() -> None:
    buckets = [CellularBucket(5000, None, None, -65.0, "1", "2")]
    merged = merge_buckets_into_cursor({"1:2": 4000}, buckets)
    assert merged["1:2"] == 5000


def test_system_ip_from_inventory_prefers_system_ip() -> None:
    parsed = {"uuid": "abc", "system-ip": "10.100.5.111"}
    assert system_ip_from_inventory(parsed) == "10.100.5.111"


def test_device_has_cellular_from_enrichment() -> None:
    parsed: dict[str, object] = {"terraEnrichedFromSync": {"cellular_sync_dataservice_device_cellular_modem": []}}
    assert device_has_cellular_capability(parsed) is True


def test_post_eiolte_history_success() -> None:
    body = build_eiolte_unique_aggregation_body("10.0.0.2", 1)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={"data": [{"entry_time": 1, "rssi": -80, "slot": "0", "active_sim": ""}]},
        )
    )
    client = httpx.Client(transport=transport, base_url="https://mgr.example")
    status, payload = post_eiolte_history(client, "https://mgr.example", body, timeout=5.0)
    assert status == 200
    assert isinstance(payload, dict)


def test_sync_cellular_multitenant_switch_before_post() -> None:
    from terra.models import SdWanManagerInstance, SyncedDevice
    from terra_sdwan.sdwan_cellular_history import sync_cellular_history_for_instance

    inst = SdWanManagerInstance(
        id=1,
        user_id=1,
        display_name="lab",
        base_url="https://mgr.example",
        auth_mode="jwt",
        credentials_encrypted="x",
        link_status="connected",
    )
    dev = SyncedDevice(
        id=10,
        sdwan_instance_id=1,
        source_device_uuid="u1",
        sdwan_tenant_id="tenant-a",
        sdwan_tenant_name="A",
        hostname="edge-1",
        device_type="vedge",
        model="IR1101-K9",
        raw_json='{"system-ip":"10.1.1.1","terraEnrichedFromSync":{"cellular_sync_x":{}}}',
        state_changed_at_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
        synced_at_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    db = MagicMock()
    db.scalars.return_value = iter([dev])

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with (
        patch("terra_sdwan.sdwan_cellular_history.get_settings") as gs,
        patch("terra_sdwan.sdwan_cellular_history.open_manager_http_client", return_value=mock_client),
        patch(
            "terra_sdwan.sdwan_cellular_history.refresh_sdwan_dataservice_csrf_header",
            return_value=True,
        ) as csrf,
        patch("terra_sdwan.sdwan_cellular_history.switch_tenant") as st,
        patch("terra_sdwan.sdwan_cellular_history.post_eiolte_history", return_value=(200, {"data": []})),
        patch("terra_sdwan.sdwan_cellular_history.push_cellular_samples"),
    ):
        settings = gs.return_value
        settings.cellular_history_enabled = True
        settings.telemetry_push_enabled = True
        settings.victoriametrics_url = "http://vm:8428"
        settings.cellular_history_max_devices_per_sync = 100
        settings.cellular_history_hours = 2
        settings.cellular_history_backfill_hours = 48
        settings.cellular_history_histogram_minutes = 30
        settings.cellular_history_omit_ps_domain_filter = False
        settings.cellular_history_http_timeout_seconds = 30.0
        settings.sdwan_sync_inventory_timeout_seconds = 120.0

        sync_cellular_history_for_instance(db, "secret", inst)
        csrf.assert_called()
        st.assert_called_once()
        assert st.call_args[0][2] == "tenant-a"
