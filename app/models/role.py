from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    HR_TEAM = "hr_team"
    TECHNICAL_TEAM = "technical_team"
    SERVICE_ENGINEER = "service_engineer"

    @property
    def label(self) -> str:
        return ROLE_LABELS[self]


ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Admin",
    Role.HR_TEAM: "HR Team",
    Role.TECHNICAL_TEAM: "Technical Team",
    Role.SERVICE_ENGINEER: "Service Engineer",
}
