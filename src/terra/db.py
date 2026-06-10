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


def sdwan_batch_needs_serial_execution() -> bool:
    """When True, SD-WAN manager sync batch must not use concurrent workers on one DB connection.

    In-memory SQLite uses :class:`~sqlalchemy.pool.StaticPool` (single shared connection).
    Concurrent threads issuing ORM operations can race and return empty rows (e.g. ``Session.get``).
    """
    return _sqlite_is_memory(get_settings().database_url)


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
        if "credential_scope" not in names:
            conn.execute(text("ALTER TABLE sdwan_manager_instances ADD COLUMN credential_scope VARCHAR(32)"))
            logger.info("Applied SQLite patch: sdwan_manager_instances.credential_scope")
        if "credential_scope_detail" not in names:
            conn.execute(
                text("ALTER TABLE sdwan_manager_instances ADD COLUMN credential_scope_detail VARCHAR(512)")
            )
            logger.info("Applied SQLite patch: sdwan_manager_instances.credential_scope_detail")

        dev_exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='synced_devices'")
        ).scalar()
        if dev_exists is not None:
            dev_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(synced_devices)")).fetchall()}
            if "cellular_stats_cursor" not in dev_cols:
                conn.execute(text("ALTER TABLE synced_devices ADD COLUMN cellular_stats_cursor TEXT"))
                logger.info("Applied SQLite patch: synced_devices.cellular_stats_cursor")


def _postgres_add_missing_columns(engine: Engine) -> None:
    """Lightweight ALTER for Postgres deployments (create_all does not migrate)."""
    url = str(engine.url)
    if not url.startswith("postgresql"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE synced_devices ADD COLUMN IF NOT EXISTS cellular_stats_cursor TEXT"
            )
        )


def _sqlite_migrate_synced_devices_multitenant(engine: Engine) -> None:
    """
    Add sdwan_tenant_id / sdwan_tenant_name and replace the 2-col unique index with a 3-col one.
    SQLite cannot ALTER constraints in place; rebuild the table when the new columns are missing.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='synced_devices'")
        ).scalar()
        if exists is None:
            return
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(synced_devices)")).fetchall()}
        if "sdwan_tenant_id" in cols and "sdwan_tenant_name" in cols:
            return
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                """
                CREATE TABLE synced_devices__new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    sdwan_instance_id INTEGER NOT NULL,
                    source_device_uuid VARCHAR(160) NOT NULL,
                    sdwan_tenant_id VARCHAR(160) NOT NULL DEFAULT '',
                    sdwan_tenant_name VARCHAR(255) NOT NULL DEFAULT '',
                    hostname VARCHAR(255) NOT NULL,
                    serial_number VARCHAR(128) NOT NULL,
                    model VARCHAR(128) NOT NULL,
                    software_version VARCHAR(128) NOT NULL,
                    device_type VARCHAR(64) NOT NULL,
                    site_id VARCHAR(64),
                    reachability VARCHAR(32) NOT NULL,
                    state_changed_at_utc TIMESTAMP NOT NULL,
                    synced_at_utc TIMESTAMP NOT NULL,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(sdwan_instance_id) REFERENCES sdwan_manager_instances (id) ON DELETE CASCADE,
                    UNIQUE (sdwan_instance_id, source_device_uuid, sdwan_tenant_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO synced_devices__new (
                    id, sdwan_instance_id, source_device_uuid, sdwan_tenant_id, sdwan_tenant_name,
                    hostname, serial_number, model, software_version, device_type, site_id,
                    reachability, state_changed_at_utc, synced_at_utc, raw_json
                )
                SELECT
                    id, sdwan_instance_id, source_device_uuid, '', '',
                    hostname, serial_number, model, software_version, device_type, site_id,
                    reachability, state_changed_at_utc, synced_at_utc, raw_json
                FROM synced_devices
                """
            )
        )
        conn.execute(text("DROP TABLE synced_devices"))
        conn.execute(text("ALTER TABLE synced_devices__new RENAME TO synced_devices"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        logger.info(
            "Applied SQLite migration: synced_devices tenant columns + uq_synced_device_per_manager_tenant"
        )


def init_db() -> None:
    eng = get_engine()
    Base.metadata.create_all(bind=eng)
    _sqlite_add_missing_columns(eng)
    _sqlite_migrate_synced_devices_multitenant(eng)
    _postgres_add_missing_columns(eng)
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
