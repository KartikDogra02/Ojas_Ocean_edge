from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, Field

from app.models.common import LabeledEnum, StrictModel, Timestamps, lowercase

RoleCode = Annotated[str, BeforeValidator(lowercase), Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")]


class Role(LabeledEnum):
    """Built-in system roles. Always present in the roles collection; they gate API access and can't be deleted."""

    ADMIN = "admin", "Admin"
    HR_TEAM = "hr_team", "HR Team"
    TECHNICAL_TEAM = "technical_team", "Technical Team"
    SERVICE_ENGINEER = "service_engineer", "Service Engineer"


SYSTEM_ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.ADMIN: "Full unrestricted access to all maritime operations and system administration",
    Role.HR_TEAM: "Personnel records, onboarding and service engineer workforce management",
    Role.TECHNICAL_TEAM: "Marine telemetry, subsea sensors diagnostics, and offshore asset monitoring",
    Role.SERVICE_ENGINEER: "Field service, maintenance and offshore job dispatches",
}


class RoleCreate(StrictModel):
    code: RoleCode
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class RoleUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class RoleOut(Timestamps):
    # Built from role documents; ignore any internal fields.
    model_config = ConfigDict(extra="ignore")

    id: str
    code: str
    name: str
    description: str | None = None
    is_system: bool
    is_active: bool
    user_count: int = 0
