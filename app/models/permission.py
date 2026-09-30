from datetime import datetime

from pydantic import BaseModel, Field

from app.models.common import StrictModel
from app.models.role import Role, RoleCode


class MenuItem(BaseModel):
    menu_id: str
    menu_title: str
    category: str
    icon: str
    route: str


# The application's menu. Which roles see each item is stored per role (roles.menu_permissions).
MENU_ITEMS: list[MenuItem] = [
    MenuItem(menu_id=menu_id, menu_title=title, category=category, icon=icon, route=route)
    for menu_id, title, category, icon, route in [
        ("menu-dashboard", "Dashboard", "Core Operations", "dashboard", "/portal/dashboard"),
        ("menu-users", "User Management", "Administration", "manage_accounts", "/portal/users"),
        ("menu-roles", "Roles & Permissions", "Administration", "admin_panel_settings", "/portal/roles"),
        ("menu-service-engineers", "Service Engineers", "Workforce", "engineering", "/portal/service-engineers"),
        ("menu-subsea", "Subsea Navigation", "Marine Operations", "radar", "/portal/subsea"),
        (
            "menu-reference-standards",
            "Reference Standards",
            "Calibration",
            "straighten",
            "/portal/reference-standards",
        ),
        ("menu-certificates", "Calibration Certificates", "Calibration", "workspace_premium", "/portal/certificates"),
    ]
]
MENU_IDS = {m.menu_id for m in MENU_ITEMS}

# Initial access for system roles when they are first seeded. Admin always sees everything.
_DEFAULT_ACCESS: dict[str, set[str]] = {
    "menu-dashboard": {Role.HR_TEAM, Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER},
    "menu-users": {Role.HR_TEAM},
    "menu-roles": {Role.HR_TEAM},
    "menu-service-engineers": {Role.HR_TEAM},
    "menu-subsea": {Role.TECHNICAL_TEAM},
    "menu-reference-standards": {Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER},
    "menu-certificates": {Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER},
}


def default_menu_permissions(role_code: str) -> dict[str, bool]:
    """Starting menu access for a new role; custom roles only get the dashboard."""
    if role_code in Role:
        return {menu_id: role_code in roles for menu_id, roles in _DEFAULT_ACCESS.items()}
    return {"menu-dashboard": True}


class MenuItemPermissions(MenuItem):
    permissions: dict[str, bool]


class PermissionMatrix(BaseModel):
    menu_items: list[MenuItemPermissions]


class MatrixEntry(StrictModel):
    menu_id: str
    role_code: RoleCode
    is_allowed: bool


class MatrixUpdate(StrictModel):
    matrix: list[MatrixEntry] = Field(min_length=1)


class MatrixUpdateResult(BaseModel):
    detail: str
    updated_records: int
    timestamp: datetime
