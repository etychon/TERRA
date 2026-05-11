"""Browser HTML flows: login, logout, password reset, email verification (no public self-registration)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from terra.crud import (
    authenticate,
    consume_auth_token,
    issue_auth_token,
    log_token_delivery,
)
from terra.db import get_db
from terra.deps import ensure_csrf, require_csrf
from terra.models import AuthTokenKind
from terra.security import hash_password

router = APIRouter(tags=["auth-pages"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Full-width auth pages (no left navigation chrome).
_SOLO_NAV = {"show_app_shell": False, "nav_is_admin": False, "nav_active": ""}


@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    csrf = ensure_csrf(request)
    return templates.TemplateResponse(
        request,
        "login.html",
        {**_SOLO_NAV, "title": "Sign in — TERRA", "error": None, "csrf_token": csrf},
    )


@router.post("/auth/login", response_model=None)
def login_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    require_csrf(request, csrf_token)
    user = authenticate(db, email, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                **_SOLO_NAV,
                "title": "Sign in — TERRA",
                "error": "Invalid email or password.",
                "csrf_token": ensure_csrf(request),
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session.clear()
    ensure_csrf(request)
    request.session["uid"] = user.id
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)


@router.api_route("/auth/register", methods=["GET", "POST"], response_model=None)
def register_disabled() -> None:
    """Self-service registration removed; administrators create users under /admin/users."""
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/auth/forgot-password", response_class=HTMLResponse)
def forgot_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            **_SOLO_NAV,
            "title": "Reset password — TERRA",
            "error": None,
            "info": None,
            "csrf_token": ensure_csrf(request),
        },
    )


@router.post("/auth/forgot-password")
def forgot_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    email: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    from sqlalchemy import select

    from terra.models import User

    user = db.execute(select(User).where(User.email == email.lower().strip())).scalar_one_or_none()
    info = (
        "If an account exists for that email, a reset link has been prepared. "
        "With mail disabled, check server logs or ask an administrator."
    )
    if user is not None and user.is_active:
        raw = issue_auth_token(db, user, AuthTokenKind.password_reset.value)
        log_token_delivery("password_reset", user, raw, "/auth/reset-password")
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {
            **_SOLO_NAV,
            "title": "Reset password — TERRA",
            "error": None,
            "info": info,
            "csrf_token": ensure_csrf(request),
        },
    )


@router.get("/auth/reset-password", response_class=HTMLResponse)
def reset_page(request: Request, token: str = "") -> HTMLResponse:
    if not token:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {
                **_SOLO_NAV,
                "title": "Set new password — TERRA",
                "error": "Missing token.",
                "token": "",
                "csrf_token": ensure_csrf(request),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return templates.TemplateResponse(
        request,
        "reset_password.html",
        {
            **_SOLO_NAV,
            "title": "Set new password — TERRA",
            "error": None,
            "token": token,
            "csrf_token": ensure_csrf(request),
        },
    )


@router.post("/auth/reset-password", response_model=None)
def reset_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
) -> RedirectResponse | HTMLResponse:
    require_csrf(request, csrf_token)
    user = consume_auth_token(db, token, AuthTokenKind.password_reset.value)
    if user is None:
        return templates.TemplateResponse(
            request,
            "reset_password.html",
            {
                **_SOLO_NAV,
                "title": "Set new password — TERRA",
                "error": "Invalid or expired token.",
                "token": "",
                "csrf_token": ensure_csrf(request),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(tz=UTC)
    db.add(user)
    db.commit()
    return RedirectResponse(url="/auth/login?reset=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, db: Annotated[Session, Depends(get_db)], token: str = "") -> HTMLResponse:
    if not token:
        return templates.TemplateResponse(
            request,
            "verify_result.html",
            {**_SOLO_NAV, "title": "Email verification — TERRA", "ok": False, "message": "Missing token."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = consume_auth_token(db, token, AuthTokenKind.email_verify.value)
    if user is None:
        return templates.TemplateResponse(
            request,
            "verify_result.html",
            {
                **_SOLO_NAV,
                "title": "Email verification — TERRA",
                "ok": False,
                "message": "Invalid or expired token.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user.email_verified_at = datetime.now(tz=UTC)
    db.add(user)
    db.commit()
    return templates.TemplateResponse(
        request,
        "verify_result.html",
        {
            **_SOLO_NAV,
            "title": "Email verification — TERRA",
            "ok": True,
            "message": "Your email is verified. You can sign in.",
        },
    )
