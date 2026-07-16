"""SQLAlchemy models for users, roles, and auth tokens."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, back_populates="users")
    tokens: Mapped[list[AuthToken]] = relationship(back_populates="user", cascade="all, delete")
    sdwan_managers: Mapped[list[SdWanManagerInstance]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class SdWanAuthMode(StrEnum):
    jwt = "jwt"
    session = "session"


class SdWanLinkStatus(StrEnum):
    unknown = "unknown"
    connected = "connected"
    auth_failed = "auth_failed"
    unreachable = "unreachable"


class SdWanManagerInstance(Base):
    """Per-user Catalyst SD-WAN Manager (vManage) connection profile (secrets encrypted at rest)."""

    __tablename__ = "sdwan_manager_instances"
    __table_args__ = (UniqueConstraint("user_id", "display_name", name="uq_sdwan_user_display_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    link_status: Mapped[str] = mapped_column(String(32), nullable=False, default=SdWanLinkStatus.unknown.value)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_version: Mapped[str | None] = mapped_column(String(128))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(1024))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devices_last_sync_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credential_scope_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="sdwan_managers")
    synced_devices: Mapped[list[SyncedDevice]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
    )


class SyncedDevice(Base):
    """Device inventory snapshot from one SD-WAN Manager (UTC timestamps; raw JSON for drill-down)."""

    __tablename__ = "synced_devices"
    __table_args__ = (
        UniqueConstraint(
            "sdwan_instance_id",
            "source_device_uuid",
            "sdwan_tenant_id",
            name="uq_synced_device_per_manager_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sdwan_instance_id: Mapped[int] = mapped_column(
        ForeignKey("sdwan_manager_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_device_uuid: Mapped[str] = mapped_column(String(160), nullable=False)
    #: Multitenant Manager: tenant id used in ``POST …/tenant/{id}/switch``; empty for single-tenant / legacy rows.
    sdwan_tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    #: Human-readable tenant label from Manager (may be empty when only an id exists).
    sdwan_tenant_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    serial_number: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    software_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    site_id: Mapped[str | None] = mapped_column(String(64))
    reachability: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    state_changed_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    #: JSON map ``slot:active_sim`` → max ingested EIOLTE ``entry_time`` (epoch ms) for incremental history.
    cellular_stats_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)

    instance: Mapped[SdWanManagerInstance] = relationship(back_populates="synced_devices")


class AuthTokenKind(StrEnum):
    password_reset = "password_reset"
    email_verify = "email_verify"


class CollectorStatus(Base):
    """Singleton row (id=1) tracking background collector heartbeat and last batch summary."""

    __tablename__ = "collector_status"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    service_name: Mapped[str] = mapped_column(String(32), nullable=False, default="collector")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_batch_run_id: Mapped[str | None] = mapped_column(String(32))
    last_batch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_batch_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_batch_kind: Mapped[str | None] = mapped_column(String(32))
    last_batch_managers: Mapped[int | None] = mapped_column(Integer)
    last_batch_ok: Mapped[int | None] = mapped_column(Integer)
    last_batch_warn: Mapped[int | None] = mapped_column(Integer)
    last_batch_err: Mapped[int | None] = mapped_column(Integer)
    last_batch_rows: Mapped[int | None] = mapped_column(Integer)
    last_batch_wall_ms: Mapped[int | None] = mapped_column(Integer)
    last_batch_cellular_buckets: Mapped[int | None] = mapped_column(Integer)
    last_batch_cellular_errors: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppLogEvent(Base):
    """Cross-process operator log rows (collector batch events visible to core Logs UI)."""

    __tablename__ = "app_log_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(12), nullable=False)
    component: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    http_status: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="collector")


class SdWanGovernanceEvent(Base):
    """Normalized alarm/event/audit row from Manager governance POST queries."""

    __tablename__ = "sdwan_governance_events"
    __table_args__ = (
        UniqueConstraint("sdwan_instance_id", "source_key", name="uq_governance_event_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sdwan_instance_id: Mapped[int] = mapped_column(
        ForeignKey("sdwan_manager_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sdwan_tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    sdwan_tenant_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stream_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    severity_norm: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    system_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    site_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    synced_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("synced_devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    component: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    rule_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    loguser: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    logfeature: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SdWanGovernanceSyncState(Base):
    """Incremental cursor for governance ingest per manager/tenant/stream."""

    __tablename__ = "sdwan_governance_sync_state"
    __table_args__ = (
        UniqueConstraint(
            "sdwan_instance_id",
            "sdwan_tenant_id",
            "stream_kind",
            name="uq_governance_sync_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sdwan_instance_id: Mapped[int] = mapped_column(
        ForeignKey("sdwan_manager_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    sdwan_tenant_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    stream_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    last_entry_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(512))
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="tokens")
