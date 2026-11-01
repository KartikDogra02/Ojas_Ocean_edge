from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.auth import AuthenticatedPrincipal, Principal, require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.role import Role
from app.models.user import UserCreate, UserOut, UserUpdate
from app.routers.common import USER_PROJECTION, Limit, Skip, from_doc, require_found, set_total, to_oid
from app.security import hash_password
from app.services import duplicate_key_error, ensure_roles_exist, insert_user, role_values

router = APIRouter(prefix="/users", tags=["users"])
admin_only = [Depends(require_roles(Role.ADMIN))]
Admin: TypeAlias = Annotated[Principal, Depends(require_roles(Role.ADMIN))]

_ENGINEER_ROLE_ERROR = "The service_engineer role is managed through /service-engineers"


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_user(user: UserCreate):
    if Role.SERVICE_ENGINEER in user.roles:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _ENGINEER_ROLE_ERROR)
    # The admin chose this password, so the user must replace it at first login.
    return from_doc(await insert_user(user))


@router.get("", response_model=list[UserOut], dependencies=admin_only)
async def list_users(response: Response, role: str | None = None, skip: Skip = 0, limit: Limit = 100):
    query = {"roles": role.lower()} if role else {}
    await set_total(response, get_db().users, query)
    cursor = get_db().users.find(query, USER_PROJECTION).sort("username", 1).skip(skip).limit(limit)
    return [from_doc(d) async for d in cursor]


@router.get("/me", response_model=UserOut)
async def get_me(principal: AuthenticatedPrincipal):
    doc = await get_db().users.find_one({"_id": principal.user_id}, USER_PROJECTION)
    return from_doc(require_found(doc, "User not found"))


@router.get("/{user_id}", response_model=UserOut, dependencies=admin_only)
async def get_user(user_id: str):
    doc = await get_db().users.find_one({"_id": to_oid(user_id)}, USER_PROJECTION)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return from_doc(doc)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, user: UserUpdate, admin: Admin):
    db = get_db()
    oid = to_oid(user_id)
    existing = await db.users.find_one({"_id": oid}, {"roles": 1})
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    is_engineer = Role.SERVICE_ENGINEER.value in existing.get("roles", [])

    changes = user.model_dump(exclude_unset=True, exclude={"password", "service_engineer"})
    if user.roles is not None:
        if (Role.SERVICE_ENGINEER in user.roles) != is_engineer:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _ENGINEER_ROLE_ERROR)
        await ensure_roles_exist(user.roles)
        changes["roles"] = role_values(user.roles)
    if user.password is not None:
        changes["hashed_password"] = hash_password(user.password.get_secret_value())
        changes["password_changed_at"] = utcnow()
        # A password set by an admin for someone else is temporary.
        if oid != admin.user_id:
            changes["must_change_password"] = True
    if user.service_engineer is not None:
        if not is_engineer:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "User is not a service engineer")
        for field, value in user.service_engineer.model_dump(exclude_unset=True).items():
            changes[f"service_engineer.{field}"] = value

    changes["updated_at"] = utcnow()
    try:
        doc = await db.users.find_one_and_update(
            {"_id": oid}, {"$set": changes}, projection=USER_PROJECTION, return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError as exc:
        raise duplicate_key_error(exc) from exc
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return from_doc(doc)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_user(user_id: str):
    result = await get_db().users.delete_one({"_id": to_oid(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
