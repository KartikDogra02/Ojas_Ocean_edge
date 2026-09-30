from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

from app.auth import require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.permission import (
    MENU_IDS,
    MENU_ITEMS,
    MatrixUpdate,
    MatrixUpdateResult,
    MenuItemPermissions,
    PermissionMatrix,
    default_menu_permissions,
)
from app.models.role import Role, RoleCreate, RoleOut, RoleUpdate
from app.routers.common import from_doc

router = APIRouter(prefix="/roles", tags=["roles"])
admin_only = [Depends(require_roles(Role.ADMIN))]
admin_or_hr = [Depends(require_roles(Role.ADMIN, Role.HR_TEAM))]

_SYSTEM_ROLE_ERROR = "Cannot modify code or system attributes of built-in system role"


def _lookup(role_id_or_code: str) -> dict:
    code_query = {"code": role_id_or_code.lower()}
    if ObjectId.is_valid(role_id_or_code):
        return {"$or": [{"_id": ObjectId(role_id_or_code)}, code_query]}
    return code_query


async def _get_role(role_id_or_code: str, not_found: str = "Role not found") -> dict:
    role = await get_db().roles.find_one(_lookup(role_id_or_code))
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, not_found)
    return role


async def _user_counts(codes: list[str]) -> dict[str, int]:
    pipeline = [
        {"$match": {"roles": {"$in": codes}}},
        {"$unwind": "$roles"},
        {"$group": {"_id": "$roles", "count": {"$sum": 1}}},
    ]
    return {d["_id"]: d["count"] async for d in await get_db().users.aggregate(pipeline)}


async def _out(role: dict) -> RoleOut:
    counts = await _user_counts([role["code"]])
    return RoleOut(**from_doc(role), user_count=counts.get(role["code"], 0))


# ---- Menu permission matrix (declared before /{role_id_or_code} routes) ----


@router.get("/permissions/matrix", response_model=PermissionMatrix)
async def get_permission_matrix():
    """Which roles can see each menu item. Admin always has access to everything."""
    roles = [r async for r in get_db().roles.find({}, {"code": 1, "menu_permissions": 1}).sort("code", 1)]
    return PermissionMatrix(
        menu_items=[
            MenuItemPermissions(
                **item.model_dump(),
                permissions={
                    r["code"]: r["code"] == Role.ADMIN or r.get("menu_permissions", {}).get(item.menu_id, False)
                    for r in roles
                },
            )
            for item in MENU_ITEMS
        ]
    )


@router.put("/permissions/matrix", response_model=MatrixUpdateResult, dependencies=admin_only)
async def update_permission_matrix(body: MatrixUpdate):
    """Validate every entry first, then apply them all in one bulk write."""
    unknown_menus = sorted({e.menu_id for e in body.matrix} - MENU_IDS)
    codes = {e.role_code for e in body.matrix}
    unknown_roles = sorted(codes - set(await get_db().roles.distinct("code", {"code": {"$in": list(codes)}})))
    if unknown_menus:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown menu_id(s): {', '.join(unknown_menus)}")
    if unknown_roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown role code(s): {', '.join(unknown_roles)}")
    if any(e.role_code == Role.ADMIN and not e.is_allowed for e in body.matrix):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin always has access to every menu")

    now = utcnow()
    await get_db().roles.bulk_write(
        [
            UpdateOne(
                {"code": e.role_code}, {"$set": {f"menu_permissions.{e.menu_id}": e.is_allowed, "updated_at": now}}
            )
            for e in body.matrix
        ]
    )
    return MatrixUpdateResult(
        detail="Role menu permissions matrix updated successfully", updated_records=len(body.matrix), timestamp=now
    )


# ---- Roles CRUD ----


@router.get("", response_model=list[RoleOut], dependencies=admin_or_hr)
async def list_roles(skip: int = 0, limit: int = 100, is_active: bool | None = None):
    query = {} if is_active is None else {"is_active": is_active}
    roles = [r async for r in get_db().roles.find(query).sort("created_at", 1).skip(skip).limit(limit)]
    counts = await _user_counts([r["code"] for r in roles])
    return [RoleOut(**from_doc(r), user_count=counts.get(r["code"], 0)) for r in roles]


@router.get("/{role_id_or_code}", response_model=RoleOut, dependencies=admin_or_hr)
async def get_role(role_id_or_code: str):
    return await _out(await _get_role(role_id_or_code, f"Role '{role_id_or_code}' not found"))


@router.post("", response_model=RoleOut, status_code=status.HTTP_201_CREATED, dependencies=admin_only)
async def create_role(body: RoleCreate):
    now = utcnow()
    doc = body.model_dump() | {
        "is_system": False,
        "menu_permissions": default_menu_permissions(body.code),
        "created_at": now,
        "updated_at": now,
    }
    try:
        await get_db().roles.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Role code '{body.code}' already exists")
    return RoleOut(**from_doc(doc), user_count=0)


@router.patch("/{role_id_or_code}", response_model=RoleOut, dependencies=admin_only)
async def update_role(role_id_or_code: str, body: RoleUpdate):
    role = await _get_role(role_id_or_code)
    # name and is_active can't be cleared; description can (null removes it).
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "description"}
    if role["is_system"] and (
        changes.get("name", role["name"]) != role["name"] or changes.get("is_active", True) is False
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, _SYSTEM_ROLE_ERROR)
    changes["updated_at"] = utcnow()
    updated = await get_db().roles.find_one_and_update(
        {"_id": role["_id"]}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    return await _out(updated)


@router.delete("/{role_id_or_code}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_role(role_id_or_code: str):
    db = get_db()
    role = await _get_role(role_id_or_code)
    if role["is_system"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Built-in system roles ({', '.join(r.value for r in Role)}) cannot be deleted",
        )
    active_users = await db.users.count_documents({"roles": role["code"], "is_active": True})
    if active_users:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot delete role assigned to {active_users} active user(s). Reassign users first.",
        )
    # Inactive users may still hold the role; remove it from them too.
    await db.users.update_many({"roles": role["code"]}, {"$pull": {"roles": role["code"]}})
    await db.roles.delete_one({"_id": role["_id"]})
