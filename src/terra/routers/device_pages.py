"""HTML views for synced SD-WAN device drill-down and comparison."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.crud import user_to_public
from terra.crud_devices import (
    device_to_home_row,
    get_device_for_user,
    get_devices_for_user_by_ids,
    list_all_devices_for_ui,
)
from terra.db import get_db
from terra.deps import ensure_csrf, get_current_user, user_is_admin
from terra.inventory_extract import (
    display_serial,
    extract_cellular_kv,
    extract_interface_rows,
    utc_iso_for_json,
)
from terra.models import User

router = APIRouter(prefix="/devices", tags=["devices"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

_MANAGER_FIELD_CATEGORY_ORDER = (
    "Objects",
    "Arrays",
    "Text",
    "Numbers",
    "Boolean",
    "Null",
    "Other",
)


def _manager_value_category(value: Any) -> str:
    if value is None:
        return "Null"
    if isinstance(value, bool):
        return "Boolean"
    if isinstance(value, dict):
        return "Objects"
    if isinstance(value, list):
        return "Arrays"
    if isinstance(value, (int, float)):
        return "Numbers"
    if isinstance(value, str):
        return "Text"
    return "Other"


def _manager_field_groups_from_parsed(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Group top-level Manager JSON keys by Python value type for readable detail pages."""
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for k, v in sorted(parsed.items(), key=lambda x: str(x[0])):
        label = str(k).replace("-", " ").replace("_", " ").replace(".", " › ").title()
        if isinstance(v, (dict, list)):
            value = json.dumps(v, indent=2, sort_keys=True, default=str)
            if len(value) > 12000:
                value = value[:12000] + "\n…"
        else:
            value = str(v)
        cat = _manager_value_category(v)
        buckets[cat].append({"key": str(k), "label": label, "value": value})
    return [
        {"category": cat, "fields": buckets[cat]}
        for cat in _MANAGER_FIELD_CATEGORY_ORDER
        if buckets.get(cat)
    ]


@router.get("", response_class=HTMLResponse, response_model=None)
def devices_inventory(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    """Full-fabric device grid (Material / Tabulator); same inventory as former Home table."""
    pairs = list_all_devices_for_ui(db)
    devices_payload = [device_to_home_row(db, d, owner_email=owner) for d, owner in pairs]
    devices_json = json.dumps(devices_payload, separators=(",", ":")).replace("<", "\\u003c")
    return templates.TemplateResponse(
        request,
        "devices.html",
        {
            "title": "Devices — TERRA",
            "user": user_to_public(user),
            "is_admin": user_is_admin(user),
            "show_app_shell": True,
            "nav_is_admin": user_is_admin(user),
            "nav_active": "devices",
            "show_device_owner": True,
            "devices_json": devices_json,
        },
    )


def _flatten_device(
    obj: Any,
    prefix: str = "",
    depth: int = 0,
    out: dict[str, str] | None = None,
    *,
    max_depth: int = 8,
    max_keys: int = 2500,
) -> dict[str, str]:
    """Flatten Manager JSON for compare (deep enough for useful diffs; capped for HTML size)."""
    if out is None:
        out = {}
    if depth > max_depth or len(out) >= max_keys:
        return out
    if isinstance(obj, dict):
        for k, v in sorted(obj.items(), key=lambda x: str(x[0])):
            if len(out) >= max_keys:
                break
            p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                _flatten_device(v, p, depth + 1, out, max_depth=max_depth, max_keys=max_keys)
            elif isinstance(v, list):
                if v and all(not isinstance(x, (dict, list)) for x in v[:50]):
                    out[p] = json.dumps(v, default=str)[:2000]
                else:
                    _flatten_device(v, p, depth + 1, out, max_depth=max_depth, max_keys=max_keys)
            else:
                out[p] = str(v)[:2000]
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            if len(out) >= max_keys:
                break
            p = f"{prefix}[{i}]" if prefix else f"[{i}]"
            if isinstance(v, (dict, list)):
                _flatten_device(v, p, depth + 1, out, max_depth=max_depth, max_keys=max_keys)
            else:
                out[p] = str(v)[:2000]
    return out


def _compare_rows_for_template(
    all_keys: list[str],
    flat_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build rows for Jinja: each field row has cells with value + whether to highlight as different."""
    rows_out: list[dict[str, Any]] = []
    n = len(flat_rows)
    for key in all_keys:
        vals = [flat_rows[j].get(key, "") or "—" for j in range(n)]
        distinct = {v for v in vals}
        row_diff = len(distinct) > 1
        ref = vals[0] if vals else ""
        cells: list[dict[str, Any]] = []
        for v in vals:
            cell_diff = row_diff and n > 1 and v != ref
            cells.append({"value": v, "diff": cell_diff})
        key_label = key.replace(".", " · ").replace("_", " ").replace("-", " ")
        rows_out.append({"key": key, "key_label": key_label, "cells": cells})
    return rows_out


@router.get("/compare", response_class=HTMLResponse)
def device_compare(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    ids: str = "",
) -> HTMLResponse:
    raw_ids = [x.strip() for x in ids.split(",") if x.strip().isdigit()]
    id_list = [int(x) for x in raw_ids[:5]]
    if len(id_list) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least two device ids as comma-separated query ids=1,2,3 (max 5).",
        )
    rows = get_devices_for_user_by_ids(db, user.id, id_list)
    if len(rows) != len(id_list):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more devices not found")
    by_id = {r.id: r for r in rows}
    rows_ordered = [by_id[i] for i in id_list if i in by_id]
    flattened: list[dict[str, str]] = []
    for r in rows_ordered:
        try:
            p = json.loads(r.raw_json)
            if not isinstance(p, dict):
                p = {}
        except json.JSONDecodeError:
            p = {}
        flattened.append(_flatten_device(p))
    all_keys = sorted(set().union(*(f.keys() for f in flattened)))
    compare_rows = _compare_rows_for_template(all_keys, flattened)
    return templates.TemplateResponse(
        request,
        "device_compare.html",
        {
            "title": "Compare devices — TERRA",
            "user": user_to_public(user),
            "is_admin": user_is_admin(user),
            "show_app_shell": True,
            "nav_is_admin": user_is_admin(user),
            "nav_active": "devices",
            "csrf_token": ensure_csrf(request),
            "devices": rows_ordered,
            "flat_rows": flattened,
            "compare_rows": compare_rows,
        },
    )


@router.get("/{device_id}", response_class=HTMLResponse)
def device_detail(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    device_id: int,
) -> HTMLResponse:
    row = get_device_for_user(db, user.id, device_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    try:
        parsed: dict[str, Any] = json.loads(row.raw_json)
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    manager_field_groups = _manager_field_groups_from_parsed(parsed)
    cellular_kv = extract_cellular_kv(parsed)
    serial_display = display_serial(row.serial_number, parsed)
    # Interfaces and cellular hints come from last synced inventory only (background sync),
    # not blocking Manager dataservice calls on page load.
    interface_rows = extract_interface_rows(parsed)
    settings = get_settings()

    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "title": f"{row.hostname or 'Device'} — TERRA",
            "user": user_to_public(user),
            "is_admin": user_is_admin(user),
            "show_app_shell": True,
            "nav_is_admin": user_is_admin(user),
            "nav_active": "devices",
            "csrf_token": ensure_csrf(request),
            "device": row,
            "serial_display": serial_display,
            "state_changed_iso": utc_iso_for_json(row.state_changed_at_utc),
            "synced_iso": utc_iso_for_json(row.synced_at_utc),
            "interface_rows": interface_rows,
            "cellular_kv": cellular_kv,
            "manager_field_groups": manager_field_groups,
            "pretty_json": json.dumps(parsed, indent=2, sort_keys=True, default=str)[:120000],
            "device_live_poll_interval_ms": max(3000, settings.device_live_poll_interval_seconds * 1000),
        },
    )
