from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.auth import AuthenticatedPrincipal, require_roles
from app.db import get_db
from app.models import Role, ServiceEngineerProfile, UserCreate, UserOut, UserUpdate
from app.models.common import utcnow
from app.routers.common import from_doc, to_oid
from app.security import hash_password
from app.services import duplicate_key_error, ensure_unique, insert_user, next_engineer_id, role_values

router = APIRouter(prefix="/users", tags=["users"])
admin_only = [Depends(require_roles(Role.ADMIN))]

# Never return the password hash.
_PROJECTION = {"hashed_password": 0}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_user(user: UserCreate):
    return from_doc(await insert_user(user))


@router.get("", response_model=list[UserOut], dependencies=admin_only)
async def list_users(role: Role | None = None, limit: int = 100):
    query = {"roles": role.value} if role else {}
    return [from_doc(d) async for d in get_db().users.find(query, _PROJECTION).limit(limit)]


@router.get("/me", response_model=UserOut)
async def get_me(principal: AuthenticatedPrincipal):
    doc = await get_db().users.find_one({"_id": principal.user_id}, _PROJECTION)
    return from_doc(doc)


@router.get("/{user_id}", response_model=UserOut, dependencies=admin_only)
async def get_user(user_id: str):
    doc = await get_db().users.find_one({"_id": to_oid(user_id)}, _PROJECTION)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return from_doc(doc)


@router.patch("/{user_id}", response_model=UserOut, dependencies=admin_only)
async def update_user(user_id: str, user: UserUpdate):
    db = get_db()
    oid = to_oid(user_id)
    existing = await db.users.find_one({"_id": oid}, {"roles": 1, "service_engineer": 1})
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    changes = user.model_dump(exclude_unset=True, exclude={"password", "service_engineer"})
    if user.roles is not None:
        changes["roles"] = role_values(user.roles)
    if user.password is not None:
        changes["hashed_password"] = hash_password(user.password.get_secret_value())
        changes["password_changed_at"] = utcnow()

    final_roles = changes.get("roles", existing.get("roles", []))
    is_engineer = Role.SERVICE_ENGINEER.value in final_roles
    profile_update = user.service_engineer.model_dump(exclude_unset=True) if user.service_engineer else None
    if profile_update is not None and not is_engineer:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "service_engineer profile is only allowed with the service_engineer role",
        )
    if existing.get("service_engineer"):
        # Keep the profile (and its engineer ID) even if the role is removed.
        for field, value in (profile_update or {}).items():
            changes[f"service_engineer.{field}"] = value
    elif is_engineer:
        if profile_update is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "service_engineer profile is required for the service_engineer role",
            )
        profile = ServiceEngineerProfile(**profile_update)
        if "email" in changes or "username" in changes:
            await ensure_unique(**{k: changes[k] for k in ("email", "username") if k in changes})
        changes["service_engineer"] = {"engineer_id": await next_engineer_id()} | profile.model_dump()

    changes["updated_at"] = utcnow()
    try:
        doc = await db.users.find_one_and_update(
            {"_id": oid},
            {"$set": changes},
            projection=_PROJECTION,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise duplicate_key_error(exc)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return from_doc(doc)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_user(user_id: str):
    oid = to_oid(user_id)
    result = await get_db().users.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
