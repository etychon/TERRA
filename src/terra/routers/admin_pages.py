"""Admin-only HTML: user lifecycle (create, delete, reset password, roles)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from terra.crud import create_user, list_users, set_roles, user_to_public
from terra.db import get_db
from terra.deps import ensure_csrf, require_admin, require_csrf
from terra.models import User
from terra.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin-pages"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _role_flags(
    role_admin: Annotated[str | None, Form()] = None,
    role_operator: Annotated[str | None, Form()] = None,
    role_viewer: Annotated[str | None, Form()] = None,
) -> list[str]:
    names: list[str] = []
    if role_admin == "on":
        names.append("admin")
    if role_operator == "on":
        names.append("operator")
    if role_viewer == "on":
        names.append("viewer")
    return names


@router.get("/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_admin)],
) -> HTMLResponse:
    users = list_users(db, skip=0, limit=500, q=None)
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "title": "Users — TERRA",
            "users": [user_to_public(u) for u in users],
            "csrf_token": ensure_csrf(request),
            "current_id": admin.id,
            "show_superuser_field": admin.is_superuser,
            "show_app_shell": True,
            "nav_is_admin": True,
            "nav_active": "users",
        },
    )


@router.post("/users/create", response_model=None)
def admin_create_user_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
    is_superuser: Annotated[str | None, Form()] = None,
    role_admin: Annotated[str | None, Form()] = None,
    role_operator: Annotated[str | None, Form()] = None,
    role_viewer: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    role_names = _role_flags(role_admin, role_operator, role_viewer)
    if not role_names:
        role_names = ["viewer"]
    su = is_superuser == "on" and current.is_superuser
    try:
        create_user(
            db,
            email=email,
            password=password,
            display_name=display_name,
            is_active=True,
            is_superuser=su,
            role_names=role_names,
            email_verified_at=datetime.now(tz=UTC),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email may already exist).",
        ) from e
    return RedirectResponse(url="/admin/users?created=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/delete", response_model=None)
def admin_delete_user_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
    user_id: int,
    csrf_token: Annotated[str, Form()],
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(u)
    db.commit()
    return RedirectResponse(url="/admin/users?deleted=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/password", response_model=None)
def admin_reset_password_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    user_id: int,
    new_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    if len(new_password) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password too short (min 10).")
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    u.hashed_password = hash_password(new_password)
    u.updated_at = datetime.now(tz=UTC)
    db.add(u)
    db.commit()
    return RedirectResponse(url="/admin/users?password=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/roles", response_model=None)
def admin_set_roles_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    user_id: int,
    csrf_token: Annotated[str, Form()],
    role_admin: Annotated[str | None, Form()] = None,
    role_operator: Annotated[str | None, Form()] = None,
    role_viewer: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    u = db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role_names = _role_flags(role_admin, role_operator, role_viewer)
    if not role_names:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one role.")
    try:
        set_roles(db, u, role_names)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return RedirectResponse(url="/admin/users?roles=1", status_code=status.HTTP_303_SEE_OTHER)
