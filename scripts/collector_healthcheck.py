"""Docker healthcheck: collector loop heartbeat must be fresh in Postgres."""

from __future__ import annotations

import sys

from terra.collector_status import collector_state_from_row
from terra.config import get_settings
from terra.db import get_session_factory
from terra.models import CollectorStatus


def main() -> int:
    settings = get_settings()
    if not settings.sdwan_background_sync:
        return 0
    sf = get_session_factory()
    with sf() as db:
        row = db.get(CollectorStatus, 1)
    state = collector_state_from_row(
        row,
        interval_seconds=settings.sdwan_sync_interval_seconds,
    )
    if state == "never":
        # Startup grace: collector may not have ticked yet.
        return 0
    if state == "stale":
        sys.stderr.write("collector heartbeat stale\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
