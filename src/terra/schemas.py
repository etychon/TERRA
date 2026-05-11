"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    is_active: bool
    is_superuser: bool
    email_verified_at: datetime | None
    roles: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = ""
    password: str = Field(min_length=10, max_length=128)
    is_active: bool = True
    is_superuser: bool = False
    role_names: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class UserBulkPatch(BaseModel):
    ids: list[int] = Field(min_length=1)
    is_active: bool | None = None
    role_names_add: list[str] | None = None
    role_names_remove: list[str] | None = None


class RolesAssign(BaseModel):
    role_names: list[str]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = ""
    password: str = Field(min_length=10, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=128)


class MessageResponse(BaseModel):
    detail: str


class TokenDeliveryResponse(BaseModel):
    """Returned when mail_mode=log so operators can complete reset without SMTP."""

    detail: str
    token: str | None = None
    verify_url: str | None = None


class SyncDevicesStats(BaseModel):
    """Result of an on-demand SD-WAN device inventory sync for the signed-in user."""

    managers: int
    rows_touched: int
    errors: int


class MapDeviceTelemetryItem(BaseModel):
    """One map-plotted device for client polling (inventory / reachability fingerprint)."""

    id: int
    synced_at_utc: str
    state_changed_at_utc: str
    reachability: str


class MapDeviceTelemetryResponse(BaseModel):
    devices: list[MapDeviceTelemetryItem]


class LiveSdWanInterfaceRow(BaseModel):
    """One row in the live interface table (device detail polling)."""

    interface: str
    ip: str
    vrf: str
    detail: str


class LiveSdWanCellularTable(BaseModel):
    """Tabular block from Manager cellular/WAN dataservice (live polling)."""

    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class LiveSdWanDeviceResponse(BaseModel):
    """Live Manager snapshot for one synced device (non-blocking HTML; used by polling fetch)."""

    ok: bool
    fetched_at: str | None = None
    note: str | None = None
    interfaces: list[LiveSdWanInterfaceRow] = Field(default_factory=list)
    cellular_tables: list[LiveSdWanCellularTable] = Field(default_factory=list)
