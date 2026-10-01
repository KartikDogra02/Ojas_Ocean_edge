from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import UpdateOne

from app.auth import CurrentPrincipal, require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.permission import (
    MENU_IDS,
    MENU_ITEMS,
    AuthorizedMenu,
    MatrixUpdate,
    MatrixUpdateResult,
    MenuItemPermissions,
    MyPermissions,
    PermissionMatrix,
    PermissionsUpdate,
    PermissionsUpdateResult,
    RoleSummary,
)
from app.models.role import Role

router = APIRouter(tags=["permissions"])
admin_only = [Depends(require_roles(Role.ADMIN, detail="Admin access required"))]

_UPDATED = "Role menu permissions matrix updated successfully"


async def _matrix() -> PermissionMatrix:
    """Which roles can see each menu item. Admin always has access to everything."""
    roles = [r async for r in get_db().roles.find({}, {"code": 1, "name": 1, "menu_permissions": 1}).sort("_id", 1)]
    return PermissionMatrix(
        roles=[RoleSummary(code=r["code"], name=r["name"]) for r in roles],
        menu_items=[
            MenuItemPermissions(
                **item.model_dump(),
                permissions={
                    r["code"]: r["code"] == Role.ADMIN or r.get("menu_permissions", {}).get(item.menu_id, False)
                    for r in roles
                },
            )
            for item in MENU_ITEMS
        ],
    )


async def _apply(changes: list[tuple[str, str, bool]]) -> datetime:
    """Validate every (menu_id, role_code, allowed) change first, then save them all in one bulk write."""
    unknown_menus = sorted({menu_id for menu_id, _, _ in changes} - MENU_IDS)
    if unknown_menus:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown menu_id(s): {', '.join(unknown_menus)}")
    codes = {code for _, code, _ in changes}
    unknown_roles = sorted(codes - set(await get_db().roles.distinct("code", {"code": {"$in": list(codes)}})))
    if unknown_roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown role code(s): {', '.join(unknown_roles)}")
    if any(code == Role.ADMIN and not allowed for _, code, allowed in changes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin always has access to every menu")

    now = utcnow()
    await get_db().roles.bulk_write(
        [
            UpdateOne({"code": code}, {"$set": {f"menu_permissions.{menu_id}": allowed, "updated_at": now}})
            for menu_id, code, allowed in changes
        ]
    )
    return now


@router.get("/permissions", response_model=PermissionMatrix)
@router.get("/roles/permissions/matrix", response_model=PermissionMatrix)
async def get_permissions():
    return await _matrix()


@router.put("/permissions", response_model=PermissionsUpdateResult, dependencies=admin_only)
async def update_permissions(body: PermissionsUpdate):
    """Bulk save from the permissions grid: one entry per menu item, with a flag per role."""
    changes = [(m.menu_id, code, allowed) for m in body.permissions for code, allowed in m.permissions.items()]
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No permissions to update")
    now = await _apply(changes)
    return PermissionsUpdateResult(detail=_UPDATED, updated_count=len(body.permissions), timestamp=now)


@router.put("/roles/permissions/matrix", response_model=MatrixUpdateResult, dependencies=admin_only)
async def update_permission_matrix(body: MatrixUpdate):
    """Bulk save as individual (menu_id, role_code, is_allowed) entries."""
    now = await _apply([(e.menu_id, e.role_code, e.is_allowed) for e in body.matrix])
    return MatrixUpdateResult(detail=_UPDATED, updated_records=len(body.matrix), timestamp=now)


@router.get("/permissions/me", response_model=MyPermissions)
@router.get("/users/me/permissions", response_model=MyPermissions)
async def get_my_permissions(principal: CurrentPrincipal):
    """The menu items the current user may see, from all of their active roles."""
    if principal.is_admin:
        allowed = MENU_IDS
    else:
        allowed = set()
        async for role in get_db().roles.find(
            {"code": {"$in": list(principal.roles)}, "is_active": True}, {"menu_permissions": 1}
        ):
            allowed |= {menu_id for menu_id, ok in role.get("menu_permissions", {}).items() if ok}
    return MyPermissions(
        user_id=str(principal.user_id),
        roles=sorted(principal.roles),
        authorized_menus=[
            AuthorizedMenu(**m.model_dump(exclude={"category"})) for m in MENU_ITEMS if m.menu_id in allowed
        ],
    )
