from typing import Annotated

from pydantic import ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator

from app.models.common import StrictModel, Timestamps
from app.models.role import Role
from app.models.service_engineer import (
    ServiceEngineerProfile,
    ServiceEngineerProfileOut,
    ServiceEngineerProfileUpdate,
)

Username = Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[a-z0-9._-]+$")]
Password = Annotated[SecretStr, Field(min_length=8, max_length=128)]


class _UsernameLower(StrictModel):
    @field_validator("username", mode="before", check_fields=False)
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v


class UserBase(_UsernameLower):
    email: EmailStr
    username: Username
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    roles: list[Role] = Field(default_factory=list)


class UserCreate(UserBase):
    password: Password
    service_engineer: ServiceEngineerProfile | None = None

    @model_validator(mode="after")
    def _profile_matches_role(self):
        is_engineer = Role.SERVICE_ENGINEER in self.roles
        if is_engineer and self.service_engineer is None:
            raise ValueError("service_engineer profile is required for the service_engineer role")
        if not is_engineer and self.service_engineer is not None:
            raise ValueError("service_engineer profile is only allowed with the service_engineer role")
        return self


class UserUpdate(_UsernameLower):
    email: EmailStr | None = None
    username: Username | None = None
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    roles: list[Role] | None = None
    password: Password | None = None
    # Admins can force a password change without resetting the password.
    must_change_password: bool | None = None
    service_engineer: ServiceEngineerProfileUpdate | None = None


class UserOut(UserBase, Timestamps):
    # Built from database documents, which carry internal fields (e.g. password_changed_at) we don't expose.
    model_config = ConfigDict(extra="ignore")

    id: str
    must_change_password: bool = True
    service_engineer: ServiceEngineerProfileOut | None = None


class ServiceEngineerCreated(UserOut):
    # Only set when the server generated the password; shown once.
    temporary_password: str | None = None
