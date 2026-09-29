from app.models.common import LabeledEnum


class Role(LabeledEnum):
    ADMIN = "admin", "Admin"
    HR_TEAM = "hr_team", "HR Team"
    TECHNICAL_TEAM = "technical_team", "Technical Team"
    SERVICE_ENGINEER = "service_engineer", "Service Engineer"
