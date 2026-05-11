"""JSON auth endpoints (session cookies; suitable for SPA or scripts)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from terra.config import get_settings
from terra.crud import (
    authenticate,
    consume_auth_token,
    issue_auth_token,
    log_token_delivery,
    user_to_public,
)
from terra.db import get_db
from terra.deps import ensure_csrf, get_current_user
from terra.models import AuthTokenKind, User
from terra.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenDeliveryResponse,
    UserPublic,
)
from terra.security import hash_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth-api"])


@router.post("/login", response_model=UserPublic)
def api_login(
    request: Request,
    body: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> UserPublic:
    user = authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    request.session.clear()
    ensure_csrf(request)
    request.session["uid"] = user.id
    return UserPublic.model_validate(user_to_public(user))


@router.post("/logout", response_model=MessageResponse)
def api_logout(request: Request) -> MessageResponse:
    request.session.clear()
    return MessageResponse(detail="Signed out")


@router.get("/me", response_model=UserPublic)
def api_me(user: Annotated[User, Depends(get_current_user)]) -> UserPublic:
    return UserPublic.model_validate(user_to_public(user))


@router.post("/register", response_model=None)
def api_register_disabled() -> None:
    """Public registration disabled; use POST /api/v1/admin/users as an administrator."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Public registration is disabled. Administrators create users via "
            "POST /api/v1/admin/users or the /admin/users UI."
        ),
    )


@router.post("/forgot-password", response_model=TokenDeliveryResponse)
def api_forgot_password(
    db: Annotated[Session, Depends(get_db)],
    body: ForgotPasswordRequest,
) -> TokenDeliveryResponse:
    settings = get_settings()
    user = db.execute(select(User).where(User.email == body.email.lower().strip())).scalar_one_or_none()
    detail = (
        "If an account exists for that email, instructions have been recorded. "
        "With MAIL_MODE=log, use server logs or the token field in trusted environments."
    )
    if user is None or not user.is_active:
        return TokenDeliveryResponse(detail=detail, token=None, verify_url=None)
    raw = issue_auth_token(db, user, AuthTokenKind.password_reset.value)
    log_token_delivery("password_reset", user, raw, "/auth/reset-password")
    token_out = raw if settings.mail_mode == "log" else None
    return TokenDeliveryResponse(
        detail=detail,
        token=token_out,
        verify_url="/auth/reset-password" if settings.mail_mode == "log" else None,
    )


@router.post("/reset-password", response_model=MessageResponse)
def api_reset_password(db: Annotated[Session, Depends(get_db)], body: ResetPasswordRequest) -> MessageResponse:
    user = consume_auth_token(db, body.token, AuthTokenKind.password_reset.value)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    user.hashed_password = hash_password(body.new_password)
    user.updated_at = datetime.now(tz=UTC)
    db.add(user)
    db.commit()
    return MessageResponse(detail="Password updated")


@router.post("/verify-email", response_model=MessageResponse)
def api_verify_email(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Query(min_length=8)],
) -> MessageResponse:
    user = consume_auth_token(db, token, AuthTokenKind.email_verify.value)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    user.email_verified_at = datetime.now(tz=UTC)
    db.add(user)
    db.commit()
    return MessageResponse(detail="Email verified")
