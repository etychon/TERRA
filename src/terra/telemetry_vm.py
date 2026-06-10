"""Push sparse operational gauges to VictoriaMetrics (Prometheus text import)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from terra.config import get_settings

logger = logging.getLogger(__name__)

_LABEL_BAD = re.compile(r'([\\"])')


def _escape_label_value(value: str) -> str:
    return _LABEL_BAD.sub(r"\\\1", value)[:200]


def _format_line(metric: str, labels: dict[str, str], value: float, ts_ms: int) -> str:
    parts = [f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())]
    lab = "{" + ",".join(parts) + "}" if parts else ""
    return f"{metric}{lab} {value} {ts_ms}\n"


def push_sdwan_sync_batch_telemetry(
    *,
    results: list[dict[str, Any]],
    batch_kind: str,
    _run_id: str,
) -> None:
    """Emit per-manager inventory gauges after a sync batch (best-effort)."""
    settings = get_settings()
    base = (settings.victoriametrics_url or "").strip().rstrip("/")
    if not base or not settings.telemetry_push_enabled:
        return
    url = f"{base}/api/v1/import/prometheus"
    ts_ms = int(time.time() * 1000)
    lines: list[str] = []
    for res in results:
        mid = str(int(res.get("instance_id") or 0))
        cluster = str(res.get("cluster") or "unknown")[:120]
        rows = float(int(res.get("rows") or 0))
        ok = 1.0 if not res.get("error") and not res.get("crashed") else 0.0
        labels_common = {"manager_id": mid, "cluster": cluster, "batch_kind": batch_kind[:32]}
        lines.append(_format_line("terra_inventory_device_count", labels_common, rows, ts_ms))
        lines.append(_format_line("terra_sdwan_sync_instance_ok", labels_common, ok, ts_ms))
    if results:
        lines.append(
            _format_line(
                "terra_sdwan_batch_managers_processed",
                {"batch_kind": batch_kind[:32]},
                float(len(results)),
                ts_ms,
            )
        )
    body = "".join(lines)
    try:
        with httpx.Client(timeout=8.0) as client:
            r = client.post(url, content=body.encode("utf-8"), headers={"Content-Type": "text/plain"})
            if r.status_code >= 400:
                logger.warning("VictoriaMetrics import returned %s: %s", r.status_code, r.text[:500])
    except Exception:
        logger.debug("VictoriaMetrics import failed", exc_info=True)


def push_cellular_samples(
    *,
    samples: list[tuple[str, dict[str, str], float, int]],
) -> None:
    """Push ``terra_cellular_*`` gauge samples (best-effort)."""
    settings = get_settings()
    base = (settings.victoriametrics_url or "").strip().rstrip("/")
    if not base or not settings.telemetry_push_enabled or not samples:
        return
    url = f"{base}/api/v1/import/prometheus"
    lines = [_format_line(metric, labels, value, ts_ms) for metric, labels, value, ts_ms in samples]
    body = "".join(lines)
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(url, content=body.encode("utf-8"), headers={"Content-Type": "text/plain"})
            if r.status_code >= 400:
                logger.warning("VictoriaMetrics cellular import returned %s: %s", r.status_code, r.text[:500])
    except Exception:
        logger.debug("VictoriaMetrics cellular import failed", exc_info=True)
