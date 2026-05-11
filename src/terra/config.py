"""Runtime configuration (environment-driven, no secrets in code)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TERRA_", env_file=".env", extra="ignore")

    secret_key: str = Field(
        default="dev-local-terra-secret-key-32charmin!",
        min_length=32,
        description="Signing key for sessions and tokens (set TERRA_SECRET_KEY in production).",
    )
    database_url: str = Field(default="sqlite:///./data/terra.db")
    mail_mode: str = Field(
        default="log",
        pattern="^(log|none)$",
        description="When mail cannot send, reset/verify links are logged server-side.",
    )
    admin_email: str = Field(default="admin@example.local")
    admin_password: str = Field(default="ChangeMe!Admin-1st-login")
    session_cookie_name: str = Field(default="terra_session")
    session_cookie_secure: bool = Field(
        default=False,
        description="When True, session cookies use Secure (use behind HTTPS reverse proxy).",
    )
    token_ttl_hours: int = Field(default=24, ge=1, le=168)
    sdwan_background_sync: bool = Field(
        default=True,
        description="When True, periodically pull /dataservice/device from connected managers (no native push).",
    )
    sdwan_sync_interval_seconds: int = Field(default=300, ge=30, le=86400)
    sdwan_sync_startup_delay_seconds: int = Field(default=10, ge=0, le=600)
    sdwan_sync_enrich_device_details: bool = Field(
        default=True,
        description="During inventory sync, merge per-device interface/cellular dataservice rows into raw_json.",
    )
    sdwan_sync_enrich_max_inventory_devices: int = Field(
        default=400,
        ge=0,
        le=20000,
        description="Skip per-device enrichment when Manager inventory row count exceeds this (bounds sync time).",
    )
    sdwan_sync_enrich_request_timeout_seconds: float = Field(
        default=8.0,
        ge=1.0,
        le=45.0,
        description="HTTP timeout (seconds) for each per-device enrich GET during sync.",
    )
    device_live_poll_interval_seconds: int = Field(
        default=5,
        ge=3,
        le=120,
        description="Default interval for device detail 'live data' UI polling when enabled.",
    )
    device_live_http_timeout_seconds: float = Field(
        default=25.0,
        ge=5.0,
        le=120.0,
        description="HTTP timeout for each Manager dataservice call used by device live polling API.",
    )
    debug_expose_internals: bool = Field(
        default=False,
        description="Lab only: mount unauthenticated /debug/* routes (requires TERRA_DEBUG_TOKEN).",
    )
    debug_token: str | None = Field(
        default=None,
        description="Bearer for /debug/* (header X-Terra-Debug-Token or query debug_token).",
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()
