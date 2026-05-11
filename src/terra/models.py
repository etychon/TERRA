"""SQLAlchemy models for users, roles, and auth tokens."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint, func
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
        UniqueConstraint("sdwan_instance_id", "source_device_uuid", name="uq_synced_device_per_manager"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sdwan_instance_id: Mapped[int] = mapped_column(
        ForeignKey("sdwan_manager_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_device_uuid: Mapped[str] = mapped_column(String(160), nullable=False)
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

    instance: Mapped[SdWanManagerInstance] = relationship(back_populates="synced_devices")


class AuthTokenKind(StrEnum):
    password_reset = "password_reset"
    email_verify = "email_verify"


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
