"""Signed-in home dashboard (device inventory lives under ``/devices``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from terra.crud import user_to_public
from terra.crud_devices import list_all_devices_for_ui
from terra.db import get_db
from terra.deps import get_current_user_optional, user_is_admin
from terra.inventory_extract import extract_geo_lat_lng
from terra.models import User

router = APIRouter(tags=["home"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _map_markers_from_db(db: Session) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for d, _owner in list_all_devices_for_ui(db):
        try:
            raw = json.loads(d.raw_json)
            if not isinstance(raw, dict):
                raw = {}
        except json.JSONDecodeError:
            raw = {}
        lat, lng = extract_geo_lat_lng(raw)
        if lat is None or lng is None:
            continue
        name = (d.hostname or "").strip() or (d.serial_number or "").strip() or f"Device {d.id}"
        markers.append(
            {
                "id": d.id,
                "lat": lat,
                "lng": lng,
                "name": name,
                "online": (d.reachability or "").lower() == "reachable",
                "model": d.model or "",
                "site": d.site_id or "",
                "serial": d.serial_number or "",
                "reachability": d.reachability or "",
            }
        )
    return markers


@router.get("/", response_class=HTMLResponse, response_model=None)
def index(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: User | None = Depends(get_current_user_optional),
) -> HTMLResponse | RedirectResponse:
    if user is None:
        return RedirectResponse(url="/auth/login", status_code=302)
    admin = user_is_admin(user)
    markers = _map_markers_from_db(db)
    map_markers_json = json.dumps(markers, separators=(",", ":")).replace("<", "\\u003c")
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": "TERRA",
            "user": user_to_public(user),
            "is_admin": admin,
            "show_app_shell": True,
            "nav_is_admin": admin,
            "nav_active": "home",
            "map_has_markers": len(markers) > 0,
            "map_markers_json": map_markers_json,
        },
    )
