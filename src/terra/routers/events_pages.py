"""HTML view for SD-WAN governance events explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from terra.crud import user_to_public
from terra.db import get_db
from terra.deps import get_current_user, user_is_admin
from terra.models import User

router = APIRouter(tags=["events"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/events", response_class=HTMLResponse)
def events_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> HTMLResponse:
    admin = user_is_admin(user)
    _ = db
    return templates.TemplateResponse(
        request,
        "events.html",
        {
            "title": "Events",
            "user": user_to_public(user),
            "is_admin": admin,
            "show_app_shell": True,
            "nav_is_admin": admin,
            "nav_active": "events",
        },
    )
