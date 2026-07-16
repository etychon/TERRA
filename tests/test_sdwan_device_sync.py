"""Unit tests for per-device SD-WAN sync (sync now on device detail)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from terra.models import SdWanLinkStatus, SdWanManagerInstance, SyncedDevice
from terra_sdwan.sdwan_sync import sync_synced_device_detail


def _device_and_instance() -> tuple[SyncedDevice, SdWanManagerInstance]:
    now = datetime.now(tz=UTC)
    inst = SdWanManagerInstance(
        id=1,
        user_id=1,
        display_name="LabMgr",
        base_url="https://manager.test.invalid",
        auth_mode="jwt",
        credentials_encrypted="enc",
        verify_tls=True,
        link_status=SdWanLinkStatus.connected.value,
    )
    dev = SyncedDevice(
        id=9,
        sdwan_instance_id=1,
        source_device_uuid="uuid-9",
        hostname="edge-9",
        device_type="vedge",
        reachability="reachable",
        state_changed_at_utc=now,
        synced_at_utc=now,
        raw_json='{"uuid":"uuid-9","system-ip":"10.9.9.9","host-name":"edge-9"}',
    )
    return dev, inst


def test_device_sync_uses_stored_inventory_when_list_unavailable() -> None:
    dev, inst = _device_and_instance()
    db = MagicMock()
    enriched = {"uuid": "uuid-9", "deviceInterface": [{"ifname": "GigabitEthernet0/0/0"}]}

    with (
        patch("terra_sdwan.sdwan_sync.open_manager_http_client") as open_client,
        patch(
            "terra_sdwan.sdwan_sync._best_effort_refresh_inventory_row",
            return_value=None,
        ),
        patch(
            "terra_sdwan.sdwan_sync.enrich_inventory_row_for_sync",
            return_value=enriched,
        ) as enrich,
        patch(
            "terra_sdwan.sdwan_cellular_history.sync_cellular_history_for_device",
            return_value={"devices_seen": 0},
        ),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        ok, err = sync_synced_device_detail(db, "secret", dev, inst)

    assert ok is True
    assert err is None
    enrich.assert_called_once()
    assert dev.raw_json is not None


def test_device_sync_fails_without_stored_inventory_when_list_unavailable() -> None:
    dev, inst = _device_and_instance()
    dev.raw_json = "{}"
    db = MagicMock()

    with (
        patch("terra_sdwan.sdwan_sync.open_manager_http_client") as open_client,
        patch(
            "terra_sdwan.sdwan_sync._best_effort_refresh_inventory_row",
            return_value=None,
        ),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        ok, err = sync_synced_device_detail(db, "secret", dev, inst)

    assert ok is False
    assert err is not None
    assert "LabMgr" in err


def test_device_sync_continues_when_tenant_switch_fails() -> None:
    dev, inst = _device_and_instance()
    dev.sdwan_tenant_id = "tenant-a"
    db = MagicMock()

    with (
        patch("terra_sdwan.sdwan_sync.open_manager_http_client") as open_client,
        patch("terra_sdwan.sdwan_sync._best_effort_switch_tenant", return_value=False),
        patch(
            "terra_sdwan.sdwan_sync._best_effort_refresh_inventory_row",
            return_value=None,
        ),
        patch(
            "terra_sdwan.sdwan_sync.enrich_inventory_row_for_sync",
            return_value={"uuid": "uuid-9"},
        ),
        patch(
            "terra_sdwan.sdwan_cellular_history.sync_cellular_history_for_device",
            return_value={"devices_seen": 0},
        ),
    ):
        open_client.return_value.__enter__.return_value = MagicMock()
        ok, err = sync_synced_device_detail(db, "secret", dev, inst)

    assert ok is True
    assert err is None
