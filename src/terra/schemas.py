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
    #: When ``managers == 1``, UTC ISO time for that manager's ``devices_last_sync_at_utc`` after sync.
    last_sync_at_utc: str | None = None
    #: When ``errors > 0`` on single-manager sync, Manager-facing reason (HTTP message, inventory phase, etc.).
    error_detail: str | None = None


class SyncJobQueued(BaseModel):
    """Async SD-WAN inventory job was queued (poll ``SyncJobStatus``)."""

    job_id: str


class SyncJobStatus(BaseModel):
    """Progress / outcome for ``POST …/sync-sdwan-devices/{id}/async``."""

    job_id: str
    #: ``queued``, ``running``, ``done``, ``failed``, or ``cancelled``
    status: str
    phase: str
    percent: int
    message: str
    rows_touched: int | None = None
    errors: int | None = None
    error_detail: str | None = None
    last_sync_at_utc: str | None = None


class SyncJobCancelResponse(BaseModel):
    """Result of ``POST …/sync-sdwan-jobs/{job_id}/cancel``."""

    accepted: bool
    message: str = ""


class AppLogItem(BaseModel):
    """One in-memory application log row (admin Logs UI)."""

    seq: int
    ts: str
    level: str
    component: str
    message: str
    detail: str = ""
    http_status: int | None = None


class AppLogFeedResponse(BaseModel):
    entries: list[AppLogItem]
    tail_seq: int


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
    ip_cidr: str = ""
    admin_status: str = ""
    admin_tone: str = ""
    oper_status: str = ""
    oper_tone: str = ""
    speed: str = ""
    vpn_id: str = ""
    service_vpn: str = ""
    is_tunnel: str = ""
    row_defer: str = ""


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
