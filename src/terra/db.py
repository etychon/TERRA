"""Database engine, session factory, and bootstrap."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from terra.config import get_settings
from terra.models import Base, Role, User
from terra.security import hash_password

logger = logging.getLogger(__name__)

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _sqlite_is_memory(database_url: str) -> bool:
    """True for in-memory SQLite URLs where each pooled connection would otherwise be an empty DB."""
    base = database_url.split("?", 1)[0].lower()
    return base.startswith("sqlite") and ":memory:" in base


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite") and not _sqlite_is_memory(url):
            raw_path = url.replace("sqlite:///", "").split("?")[0]
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        pool_kw: dict[str, Any] = {}
        if _sqlite_is_memory(url):
            # Single shared connection so create_all + requests see the same schema.
            pool_kw["poolclass"] = StaticPool
        _engine = create_engine(url, connect_args=connect_args, future=True, **pool_kw)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global SessionLocal
    if SessionLocal is None:
        SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            future=True,
            expire_on_commit=False,
        )
    return SessionLocal


def _sqlite_add_missing_columns(engine: Engine) -> None:
    """
    SQLAlchemy create_all() creates new tables but does not ALTER existing ones.
    Upgraded deployments may hit OperationalError (500) until missing columns exist.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sdwan_manager_instances'")
        ).scalar()
        if exists is None:
            return
        cols = conn.execute(text("PRAGMA table_info(sdwan_manager_instances)")).fetchall()
        names = {row[1] for row in cols}
        if "devices_last_sync_at_utc" not in names:
            conn.execute(
                text("ALTER TABLE sdwan_manager_instances ADD COLUMN devices_last_sync_at_utc TIMESTAMP")
            )
            logger.info("Applied SQLite patch: sdwan_manager_instances.devices_last_sync_at_utc")


def init_db() -> None:
    eng = get_engine()
    Base.metadata.create_all(bind=eng)
    _sqlite_add_missing_columns(eng)
    seed_rbac()


def seed_rbac() -> None:
    settings = get_settings()
    sf = get_session_factory()
    with sf() as db:
        for name, desc in (
            ("admin", "Full user and role management"),
            ("operator", "Day-to-day operations (dashboard)"),
            ("viewer", "Read-only dashboard access"),
        ):
            row = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
            if row is None:
                db.add(Role(name=name, description=desc))
        db.commit()

        if (
            db.execute(select(User).where(User.email == settings.admin_email.lower().strip()))
            .scalar_one_or_none()
            is not None
        ):
            return

        admin_role = db.execute(select(Role).where(Role.name == "admin")).scalar_one()
        viewer = db.execute(select(Role).where(Role.name == "viewer")).scalar_one()
        admin_user = User(
            email=settings.admin_email.lower().strip(),
            display_name="Administrator",
            hashed_password=hash_password(settings.admin_password),
            is_active=True,
            is_superuser=True,
            email_verified_at=None,
        )
        admin_user.roles.extend([admin_role, viewer])
        db.add(admin_user)
        db.commit()
        logger.info("Seeded default admin user for email %s", settings.admin_email)


def get_db() -> Generator[Session, None, None]:
    sf = get_session_factory()
    db = sf()
    try:
        yield db
    finally:
        db.close()
