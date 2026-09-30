from typing import Annotated

from pydantic import BeforeValidator, Field

from app.models.common import LabeledEnum, lowercase

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
