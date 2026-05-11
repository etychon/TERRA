"""Authenticated end-user utilities (non-admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.db import get_db
from terra.deps import get_current_user
from terra.models import User
from terra.schemas import SyncDevicesStats
from terra.sdwan_sync import sync_user_sdwan_devices

router = APIRouter(prefix="/api/v1/me", tags=["me"])


@router.post("/sync-sdwan-devices", response_model=SyncDevicesStats)
def sync_sdwan_devices_now(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SyncDevicesStats:
    """Pull device inventory from all connected SD-WAN managers for the current user."""
    settings = get_settings()
    stats = sync_user_sdwan_devices(db, settings.secret_key, user.id)
    return SyncDevicesStats.model_validate(stats)
