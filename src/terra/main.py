"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from terra.config import Settings, get_settings
from terra.crud import purge_expired_tokens
from terra.db import get_session_factory, init_db
from terra.routers import (
    admin_pages,
    api_admin_logs,
    api_auth,
    api_governance,
    api_me,
    api_users,
    auth_pages,
    device_pages,
    events_pages,
    home,
    sdwan_pages,
)

logger = logging.getLogger(__name__)


async def _sdwan_background_loop() -> None:
    """Periodic inventory pull — Cisco Manager has no standard push channel for full device lists."""
    from terra.config import get_settings
    from terra_sdwan.sdwan_sync import sync_all_connected_managers

    settings = get_settings()
    if not settings.sdwan_background_sync:
        return
    await asyncio.sleep(settings.sdwan_sync_startup_delay_seconds)
    while True:
        try:
            s = get_settings()
            await asyncio.to_thread(sync_all_connected_managers, s.secret_key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SD-WAN background device sync failed")
        s2 = get_settings()
        await asyncio.sleep(s2.sdwan_sync_interval_seconds)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        from terra.app_log_buffer import configure_ring_buffer, install_ring_buffer_logging

        configure_ring_buffer(3000)
        install_ring_buffer_logging()
        init_db()
        sf = get_session_factory()
        with sf() as db:
            purge_expired_tokens(db)
        task: asyncio.Task[None] | None = None
        if settings.sdwan_background_sync:
            task = asyncio.create_task(_sdwan_background_loop(), name="terra-sdwan-device-sync")
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        from terra_sdwan.sdwan_sync_job_runner import shutdown_executor

        shutdown_executor()

    app = FastAPI(
        title="TERRA API",
        description="Dashboard telemetry backend — authentication and user RBAC.",
        lifespan=lifespan,
    )
    app.state.terra_settings = settings

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness/readiness for orchestration (Docker Compose, k8s-style probes)."""
        return {"status": "ok"}

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(home.router)
    app.include_router(device_pages.router)
    app.include_router(events_pages.router)
    app.include_router(sdwan_pages.router)
    app.include_router(admin_pages.router)
    app.include_router(auth_pages.router)
    app.include_router(api_auth.router)
    app.include_router(api_me.router)
    app.include_router(api_governance.router)
    app.include_router(api_admin_logs.router)
    app.include_router(api_users.router)

    @app.middleware("http")
    async def terra_http_access_log(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        try:
            p = request.url.path
            if p.startswith("/static") or p.startswith("/docs") or p.startswith("/openapi.json") or p == "/health":
                return response
            if not p.startswith(("/api/", "/admin", "/devices", "/administration", "/auth")):
                return response
            if request.method == "GET" and any(
                frag in p
                for frag in (
                    "/sync-sdwan-jobs/",
                    "/api/v1/admin/logs",
                    "/api/v1/admin/collector-status",
                    "/map-devices-telemetry",
                )
            ):
                return response
            from terra.app_log_buffer import log_http_request
            from terra.db import get_session_factory
            from terra_sdwan.sdwan_operator_log import http_access_log_detail_for_path

            detail = ""
            if (
                "/sync-sdwan-devices/" in p
                or "/live-sdwan" in p
                or p.rstrip("/").endswith("/sync-sdwan-devices")
            ):
                try:
                    sf = get_session_factory()
                    with sf() as db:
                        detail = http_access_log_detail_for_path(db, p)
                except Exception:
                    detail = ""

            log_http_request(method=request.method, path=p, status_code=response.status_code, detail=detail)
        except Exception:
            logger.debug("TERRA access log middleware skipped", exc_info=True)
        return response

    from terra.routers.debug_internals import attach_debug_routes

    attach_debug_routes(settings, app)
    if settings.debug_expose_internals and (settings.debug_token or "").strip():
        logger.warning(
            "TERRA debug internals enabled: /debug/* is reachable with X-Terra-Debug-Token "
            "(lab / Docker debug compose only; never expose to the Internet)."
        )
    elif settings.debug_expose_internals:
        logger.error(
            "TERRA_DEBUG_EXPOSE_INTERNALS is true but TERRA_DEBUG_TOKEN is empty — /debug routes not mounted."
        )

    return app


app = create_app()
