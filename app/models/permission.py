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
        ("menu-vessel-ais", "Vessel & AIS Tracking", "Marine Operations", "directions_boat", "/portal/vessels"),
        ("menu-rig-telemetry", "Offshore Rig Telemetry", "Marine Operations", "sensors", "/portal/telemetry"),
        ("menu-subsea", "Subsea Navigation", "Marine Operations", "radar", "/portal/subsea"),
        ("menu-logistics", "Fleet Field Logistics", "Field Coordination", "local_shipping", "/portal/logistics"),
        ("menu-reports", "Operational Reports", "Field Coordination", "assessment", "/portal/reports"),
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
    "menu-vessel-ais": {Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER},
    "menu-rig-telemetry": {Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER},
    "menu-subsea": {Role.TECHNICAL_TEAM},
    "menu-logistics": {Role.HR_TEAM, Role.SERVICE_ENGINEER},
    "menu-reports": {Role.HR_TEAM, Role.TECHNICAL_TEAM},
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


class RoleSummary(BaseModel):
    code: str
    name: str


class PermissionMatrix(BaseModel):
    roles: list[RoleSummary]
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


# ---- /permissions (bulk save by menu item, and the current user's menus) ----


class MenuPermissions(StrictModel):
    menu_id: str
    permissions: dict[RoleCode, bool]


class PermissionsUpdate(StrictModel):
    permissions: list[MenuPermissions] = Field(min_length=1)


class PermissionsUpdateResult(BaseModel):
    detail: str
    updated_count: int
    timestamp: datetime


class AuthorizedMenu(BaseModel):
    menu_id: str
    menu_title: str
    icon: str
    route: str


class MyPermissions(BaseModel):
    user_id: str
    roles: list[str]
    authorized_menus: list[AuthorizedMenu]
