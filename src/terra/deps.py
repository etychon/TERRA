"""FastAPI dependencies: DB session, current user, RBAC."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from terra.db import get_db
from terra.models import User


def ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not isinstance(token, str) or len(token) < 8:
        import secrets

        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def require_csrf(request: Request, form_csrf: str | None) -> None:
    expected = request.session.get("csrf")
    if not form_csrf or not isinstance(expected, str) or form_csrf != expected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    raw_uid = request.session.get("uid")
    uid: int | None
    if isinstance(raw_uid, int):
        uid = raw_uid
    elif isinstance(raw_uid, str) and raw_uid.isdigit():
        uid = int(raw_uid)
    else:
        return None
    user = db.execute(select(User).where(User.id == uid).options(selectinload(User.roles))).scalar_one_or_none()
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def user_is_admin(user: User) -> bool:
    """True if user has the `admin` role or is a superuser."""
    if user.is_superuser:
        return True
    return any(r.name == "admin" for r in user.roles)


def require_roles(*role_names: str) -> Callable[[User], User]:
    names = frozenset(role_names)

    def _inner(user: User = Depends(get_current_user)) -> User:
        if user.is_superuser:
            return user
        user_roles = {r.name for r in user.roles}
        if not user_roles.intersection(names):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _inner


require_admin = require_roles("admin")
