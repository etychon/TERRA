"""RSSI quality bands for cellular UI (dot color)."""

from __future__ import annotations

from terra.config import get_settings


def parse_rssi_thresholds_dbm() -> list[float]:
    """Descending dBm cutoffs: excellent >= t0, good >= t1, fair >= t2, else poor."""
    raw = (get_settings().cellular_rssi_quality_thresholds_dbm or "-65,-75,-85").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[float] = []
    for p in parts[:6]:
        try:
            out.append(float(p))
        except ValueError:
            continue
    if len(out) < 3:
        return [-65.0, -75.0, -85.0]
    return out


def rssi_quality_band(rssi: float | None) -> str:
    """Return ``excellent``, ``good``, ``fair``, ``poor``, or ``unknown``."""
    if rssi is None:
        return "unknown"
    t0, t1, t2 = parse_rssi_thresholds_dbm()[:3]
    if rssi >= t0:
        return "excellent"
    if rssi >= t1:
        return "good"
    if rssi >= t2:
        return "fair"
    return "poor"
