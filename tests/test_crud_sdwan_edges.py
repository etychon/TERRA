"""SD-WAN manager admin helpers (edge inventory labels)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from terra.crud_sdwan import edge_inventory_labels_for_manager
from terra.db import get_session_factory, init_db
from terra.models import SdWanManagerInstance, SyncedDevice, User
from terra.secret_store import encrypt_json


def test_edge_inventory_labels_exclude_controllers_and_show_tenant() -> None:
    init_db()
    sf = get_session_factory()
    now = datetime.now(tz=UTC)
    with sf() as db:
        admin = db.execute(select(User).where(User.email == os.environ["TERRA_ADMIN_EMAIL"])).scalar_one()
        blob = encrypt_json(os.environ["TERRA_SECRET_KEY"], {"mode": "jwt", "token": "dummy.jwt.token"})
        name = f"EdgeLabelTestMgr-{uuid.uuid4().hex[:8]}"
        inst = SdWanManagerInstance(
            user_id=admin.id,
            display_name=name,
            base_url="https://vm-edge-label.test.invalid",
            auth_mode="jwt",
            credentials_encrypted=blob,
            verify_tls=True,
            link_status="connected",
        )
        db.add(inst)
        db.flush()
        iid = inst.id
        for uid, host, dtype, tid, tname in [
            ("u1", "vSmart", "vsmart", "", ""),
            ("u2", "vBond", "vbond", "", ""),
            ("u3", "wan-a", "vedge", "", ""),
            ("u4", "wan-b", "vedge", "t1", "TenantOne"),
        ]:
            db.add(
                SyncedDevice(
                    sdwan_instance_id=iid,
                    source_device_uuid=uid,
                    sdwan_tenant_id=tid,
                    sdwan_tenant_name=tname,
                    hostname=host,
                    state_changed_at_utc=now,
                    synced_at_utc=now,
                    device_type=dtype,
                )
            )
        db.commit()

        total, labels = edge_inventory_labels_for_manager(db, iid, max_labels=10)
        assert total == 2
        assert "wan-a" in labels
        assert "wan-b (TenantOne)" in labels
