"""Read cellular time series from VictoriaMetrics (PromQL query_range)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from terra.config import get_settings

logger = logging.getLogger(__name__)

_METRIC_BY_NAME = {
    "rssi": "terra_cellular_rssi",
    "rsrp": "terra_cellular_rsrp",
    "rsrq": "terra_cellular_rsrq",
}


def _vm_query_range_url() -> str | None:
    base = (get_settings().victoriametrics_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/prometheus/api/v1/query_range"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _label_selector(labels: dict[str, str]) -> str:
    parts = [f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items()) if v != ""]
    return "{" + ",".join(parts) + "}" if parts else ""


def query_cellular_range(
    metric: str,
    *,
    device_id: int,
    start_unix: float,
    end_unix: float,
    step_seconds: int = 60,
    slot: str | None = None,
    active_sim: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query VictoriaMetrics for one metric and device.

    Returns a list of series dicts: ``{slot, active_sim, timestamps[], values[]}``.
    """
    url = _vm_query_range_url()
    if url is None:
        return []
    metric_name = _METRIC_BY_NAME.get(metric.lower(), metric)
    labels: dict[str, str] = {"device_id": str(device_id)}
    if slot is not None:
        labels["slot"] = slot
    if active_sim is not None:
        labels["active_sim"] = active_sim
    query = f"{metric_name}{_label_selector(labels)}"
    params = {
        "query": query,
        "start": str(start_unix),
        "end": str(end_unix),
        "step": str(max(15, step_seconds)),
    }
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(url, params=params)
            if r.status_code >= 400:
                logger.debug("VM query_range %s: %s", r.status_code, r.text[:300])
                return []
            body = r.json()
    except Exception:
        logger.debug("VM query_range failed", exc_info=True)
        return []
    if not isinstance(body, dict) or body.get("status") != "success":
        return []
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, list):
        return []
    series_list: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        metric_labels = item.get("metric")
        if not isinstance(metric_labels, dict):
            metric_labels = {}
        values_raw = item.get("values")
        if not isinstance(values_raw, list):
            continue
        timestamps: list[int] = []
        values: list[float] = []
        for pair in values_raw:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                ts = int(float(pair[0]))
                val = float(pair[1])
            except (TypeError, ValueError):
                continue
            if val != val:  # NaN
                continue
            timestamps.append(ts)
            values.append(val)
        series_list.append(
            {
                "slot": str(metric_labels.get("slot", "")),
                "active_sim": str(metric_labels.get("active_sim", "")),
                "timestamps": timestamps,
                "values": values,
            }
        )
    return series_list


def default_history_window_seconds(hours: int = 24) -> tuple[float, float]:
    end = time.time()
    start = end - hours * 3600
    return start, end
