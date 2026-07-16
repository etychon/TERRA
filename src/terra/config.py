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
    sdwan_sync_enrich_concurrency: int = Field(
        default=6,
        ge=1,
        le=32,
        description=(
            "Max parallel Manager HTTP sessions used for per-device enrich during inventory sync (JWT only). "
            "Session/cookie auth forces 1 to avoid invalidating a shared login."
        ),
    )
    sdwan_sync_inventory_timeout_seconds: float = Field(
        default=120.0,
        ge=10.0,
        le=600.0,
        description=(
            "HTTP timeout (seconds) for inventory-phase dataservice calls during sync "
            "(tenant list, device list, tenant switch, manager version). "
            "Separate from the long-lived httpx client default used for rare bulk operations."
        ),
    )
    sdwan_batch_max_concurrent_managers: int = Field(
        default=3,
        ge=1,
        le=16,
        description=(
            "Max concurrent Manager inventory syncs in the periodic background batch and "
            "in POST /api/v1/me/sync-sdwan-devices. Each worker uses its own DB session. "
            "Lower on SQLite if you see database is locked."
        ),
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
    victoriametrics_url: str | None = Field(
        default=None,
        description="VictoriaMetrics base URL (e.g. http://victoriametrics:8428) for sparse gauge import.",
    )
    telemetry_push_enabled: bool = Field(
        default=True,
        description="When True and victoriametrics_url is set, push SD-WAN sync summary metrics after each batch.",
    )
    cellular_history_enabled: bool = Field(
        default=True,
        description="After inventory sync, pull EIOLTE statistics history for cellular-capable WAN edges.",
    )
    cellular_history_hours: int = Field(
        default=2,
        ge=1,
        le=168,
        description="Lookback hours for incremental cellular history when a per-device cursor exists.",
    )
    cellular_history_backfill_hours: int = Field(
        default=48,
        ge=1,
        le=168,
        description="Lookback hours on first cellular history pull (no cursor yet).",
    )
    cellular_history_histogram_minutes: int = Field(
        default=30,
        ge=1,
        le=120,
        description="EIOLTE uniqueAggregation histogram bucket width in minutes.",
    )
    cellular_history_max_devices_per_sync: int = Field(
        default=200,
        ge=0,
        le=5000,
        description="Max cellular-capable devices polled per Manager per sync (0 = unlimited).",
    )
    cellular_history_http_timeout_seconds: float = Field(
        default=45.0,
        ge=5.0,
        le=120.0,
        description="HTTP timeout for each EIOLTE statistics POST.",
    )
    cellular_history_omit_ps_domain_filter: bool = Field(
        default=False,
        description="When True, omit ps_domain Attached filter from EIOLTE queries.",
    )
    cellular_rssi_quality_thresholds_dbm: str = Field(
        default="-65,-75,-85",
        description="Comma-separated RSSI (dBm) cutoffs for excellent/good/fair/poor (descending).",
    )
    governance_sync_enabled: bool = Field(
        default=True,
        description="When True, collector periodically ingests Manager alarms/events/audit into Postgres.",
    )
    governance_sync_interval_seconds: int = Field(default=300, ge=60, le=86400)
    governance_backfill_hours: int = Field(default=24, ge=1, le=168)
    governance_overlap_minutes: int = Field(default=15, ge=1, le=120)
    governance_http_timeout_seconds: float = Field(default=45.0, ge=5.0, le=120.0)
    governance_query_size: int = Field(default=2000, ge=100, le=10000)
    governance_retention_days: int = Field(default=30, ge=1, le=365)


@lru_cache
def get_settings() -> Settings:
    return Settings()
