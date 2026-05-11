"""Admin user management (RBAC: requires `admin` role or superuser)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from terra.crud import apply_bulk_patch, create_user, list_users, set_roles, user_to_public
from terra.db import get_db
from terra.deps import get_current_user, require_admin
from terra.models import User
from terra.schemas import (
    MessageResponse,
    RolesAssign,
    UserBulkPatch,
    UserCreate,
    UserPublic,
    UserUpdate,
)
from terra.security import hash_password

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-users"],
    dependencies=[Depends(require_admin)],
)


@router.get("/users", response_model=list[UserPublic])
def admin_list_users(
    db: Annotated[Session, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    q: Annotated[str | None, Query()] = None,
) -> list[UserPublic]:
    rows = list_users(db, skip=skip, limit=limit, q=q)
    return [UserPublic.model_validate(user_to_public(u)) for u in rows]


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def admin_create_user(db: Annotated[Session, Depends(get_db)], body: UserCreate) -> UserPublic:
    try:
        u = create_user(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            is_active=body.is_active,
            is_superuser=body.is_superuser,
            role_names=body.role_names,
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
    return UserPublic.model_validate(user_to_public(u))


@router.get("/users/{user_id}", response_model=UserPublic)
def admin_get_user(db: Annotated[Session, Depends(get_db)], user_id: int) -> UserPublic:
    u = db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserPublic.model_validate(user_to_public(u))


@router.patch("/users/{user_id}", response_model=UserPublic)
def admin_patch_user(
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    user_id: int,
    body: UserUpdate,
) -> UserPublic:
    u = db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.is_active is not None:
        if u.id == current.id and not body.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")
        u.is_active = body.is_active
    if body.password is not None:
        u.hashed_password = hash_password(body.password)
    u.updated_at = datetime.now(tz=UTC)
    db.add(u)
    db.commit()
    db.refresh(u)
    u2 = db.execute(select(User).where(User.id == u.id).options(selectinload(User.roles))).scalar_one()
    return UserPublic.model_validate(user_to_public(u2))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_user(
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[User, Depends(get_current_user)],
    user_id: int,
) -> None:
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    db.delete(u)
    db.commit()


@router.put("/users/{user_id}/roles", response_model=UserPublic)
def admin_set_roles(
    db: Annotated[Session, Depends(get_db)],
    user_id: int,
    body: RolesAssign,
) -> UserPublic:
    u = db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        u2 = set_roles(db, u, body.role_names)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return UserPublic.model_validate(user_to_public(u2))


@router.post("/users/bulk", response_model=MessageResponse)
def admin_bulk_users(
    db: Annotated[Session, Depends(get_db)],
    body: UserBulkPatch,
) -> MessageResponse:
    patch: dict[str, object] = {}
    if body.is_active is not None:
        patch["is_active"] = body.is_active
    if body.role_names_add is not None:
        patch["role_names_add"] = body.role_names_add
    if body.role_names_remove is not None:
        patch["role_names_remove"] = body.role_names_remove
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No bulk fields supplied")
    n = apply_bulk_patch(db, body.ids, patch)
    return MessageResponse(detail=f"Updated {n} user(s).")
