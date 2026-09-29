from typing import Annotated

from pydantic import ConfigDict, EmailStr, Field, field_validator

from app.models.common import Password, StrictModel, Username
from app.models.territory import Territory

Phone = Annotated[str, Field(min_length=7, max_length=20, pattern=r"^\+?[0-9 ()\-.]+$")]
Skill = Annotated[str, Field(min_length=1, max_length=100)]


def _split_skills(value: object) -> object:
    # The UI sends skills as a comma-separated string; accept that as well as a list.
    if isinstance(value, str):
        value = value.split(",")
    if isinstance(value, list):
        seen: dict[str, None] = {}
        for s in value:
            if isinstance(s, str) and s.strip():
                seen.setdefault(s.strip(), None)
        return list(seen)
    return value


class EmergencyContact(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=50)
    phone: Phone


class ServiceEngineerProfile(StrictModel):
    designation: str = Field(default="Field Service Engineer", max_length=100)
    phone: Phone | None = None
    territory: Territory | None = None
    skills: list[Skill] = Field(default_factory=list)
    emergency_contact: EmergencyContact | None = None

    _split = field_validator("skills", mode="before")(_split_skills)


class ServiceEngineerProfileUpdate(StrictModel):
    designation: str | None = Field(default=None, max_length=100)
    phone: Phone | None = None
    territory: Territory | None = None
    skills: list[Skill] | None = None
    emergency_contact: EmergencyContact | None = None

    _split = field_validator("skills", mode="before")(_split_skills)


class ServiceEngineerProfileOut(ServiceEngineerProfile):
    model_config = ConfigDict(extra="ignore")

    engineer_id: str


class ServiceEngineerCreate(ServiceEngineerProfile):
    """Payload for the 'Provision New Service Engineer' form."""

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    username: Username
    # Omit to have the server generate a random temporary password (returned once).
    password: Password | None = None
