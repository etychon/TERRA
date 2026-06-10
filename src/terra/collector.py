"""Long-running SD-WAN collector worker (periodic inventory sync + optional telemetry push)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from terra.config import get_settings
from terra.crud import purge_expired_tokens
from terra.db import get_session_factory, init_db

logger = logging.getLogger(__name__)


async def _sdwan_background_loop() -> None:
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


async def _async_main() -> None:
    from terra.app_log_buffer import configure_ring_buffer, install_ring_buffer_logging

    configure_ring_buffer(3000)
    install_ring_buffer_logging()
    init_db()
    sf = get_session_factory()
    with sf() as db:
        purge_expired_tokens(db)
    settings = get_settings()
    if not settings.sdwan_background_sync:
        logger.warning("TERRA_SDWAN_BACKGROUND_SYNC is false — collector exiting (nothing to do)")
        return
    task = asyncio.create_task(_sdwan_background_loop(), name="terra-collector-sdwan")
    try:
        await task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        from terra_sdwan.sdwan_sync_job_runner import shutdown_executor

        shutdown_executor()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(_async_main())
