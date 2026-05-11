"""Database operations for users and auth tokens."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from terra.config import get_settings
from terra.models import AuthToken, Role, User
from terra.security import (
    expires_at,
    hash_password,
    hash_token,
    new_opaque_token,
    utcnow,
    verify_password,
)

logger = logging.getLogger("terra.mail")


def user_to_public(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "email_verified_at": user.email_verified_at,
        "roles": [r.name for r in user.roles],
    }


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.execute(
        select(User).where(User.email == email.lower().strip()).options(selectinload(User.roles))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    is_active: bool,
    is_superuser: bool,
    role_names: list[str],
    email_verified_at: datetime | None = None,
) -> User:
    roles: list[Role] = []
    if role_names:
        unique = list(dict.fromkeys(role_names))
        roles = list(db.execute(select(Role).where(Role.name.in_(unique))).scalars().all())
        if len(roles) != len(unique):
            msg = "One or more role names are unknown."
            raise ValueError(msg)
    u = User(
        email=email.lower().strip(),
        display_name=display_name or email.split("@", 1)[0],
        hashed_password=hash_password(password),
        is_active=is_active,
        is_superuser=is_superuser,
        email_verified_at=email_verified_at,
    )
    u.roles.extend(roles)
    db.add(u)
    db.commit()
    db.refresh(u)
    return db.execute(select(User).where(User.id == u.id).options(selectinload(User.roles))).scalar_one()


def issue_auth_token(db: Session, user: User, kind: str) -> str:
    settings = get_settings()
    raw = new_opaque_token()
    row = AuthToken(
        user_id=user.id,
        kind=kind,
        token_hash=hash_token(raw),
        expires_at=expires_at(settings.token_ttl_hours),
    )
    db.add(row)
    db.commit()
    return raw


def consume_auth_token(db: Session, raw: str, kind: str) -> User | None:
    th = hash_token(raw)
    row = db.execute(
        select(AuthToken).where(
            AuthToken.token_hash == th,
            AuthToken.kind == kind,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > utcnow(),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    user = db.execute(select(User).where(User.id == row.user_id).options(selectinload(User.roles))).scalar_one()
    row.used_at = utcnow()
    db.add(row)
    db.commit()
    return user


def log_token_delivery(kind: str, user: User, raw_token: str, path: str) -> None:
    settings = get_settings()
    if settings.mail_mode != "log":
        return
    logger.info(
        "%s link for %s — %s?token=%s",
        kind,
        user.email,
        path,
        raw_token,
    )
    logger.info("MAIL_MODE=log — no SMTP; copy token from server logs or use API response in trusted env.")


def list_users(db: Session, *, skip: int, limit: int, q: str | None) -> list[User]:
    stmt = select(User).options(selectinload(User.roles)).order_by(User.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    return list(db.execute(stmt.offset(skip).limit(limit)).scalars().all())


def set_roles(db: Session, user: User, role_names: list[str]) -> User:
    unique = list(dict.fromkeys(role_names))
    roles = list(db.execute(select(Role).where(Role.name.in_(unique))).scalars().all()) if unique else []
    if unique and len(roles) != len(unique):
        msg = "One or more role names are unknown."
        raise ValueError(msg)
    user.roles.clear()
    user.roles.extend(roles)
    user.updated_at = utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)
    return db.execute(select(User).where(User.id == user.id).options(selectinload(User.roles))).scalar_one()


def apply_bulk_patch(db: Session, ids: list[int], patch: dict[str, object]) -> int:
    stmt = select(User).where(User.id.in_(ids)).options(selectinload(User.roles))
    users = list(db.execute(stmt).scalars().all())
    count = 0
    for u in users:
        if "is_active" in patch and patch["is_active"] is not None:
            u.is_active = bool(patch["is_active"])
        add_names = patch.get("role_names_add")
        if isinstance(add_names, list):
            for name in add_names:
                role = db.execute(select(Role).where(Role.name == str(name))).scalar_one_or_none()
                if role and role not in u.roles:
                    u.roles.append(role)
        rem_names = patch.get("role_names_remove")
        if isinstance(rem_names, list):
            rem_set = {str(x) for x in rem_names}
            for role in list(u.roles):
                if role.name in rem_set:
                    u.roles.remove(role)
        u.updated_at = utcnow()
        db.add(u)
        count += 1
    db.commit()
    return count


def purge_expired_tokens(db: Session) -> None:
    db.execute(delete(AuthToken).where(AuthToken.expires_at < utcnow()))
    db.commit()
