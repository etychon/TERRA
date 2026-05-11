"""SD-WAN Manager instance persistence (per-user)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.models import SdWanManagerInstance


def list_sdwan_managers(db: Session, user_id: int) -> list[SdWanManagerInstance]:
    q = (
        select(SdWanManagerInstance)
        .where(SdWanManagerInstance.user_id == user_id)
        .order_by(SdWanManagerInstance.display_name.asc(), SdWanManagerInstance.id.asc())
    )
    return list(db.scalars(q))


def get_sdwan_manager(db: Session, user_id: int, instance_id: int) -> SdWanManagerInstance | None:
    return db.execute(
        select(SdWanManagerInstance).where(
            SdWanManagerInstance.user_id == user_id,
            SdWanManagerInstance.id == instance_id,
        )
    ).scalar_one_or_none()


def delete_sdwan_manager(db: Session, row: SdWanManagerInstance) -> None:
    db.delete(row)
    db.commit()
