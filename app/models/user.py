from pydantic import ConfigDict, EmailStr, Field

from app.models.common import Password, StrictModel, Timestamps, Username
from app.models.role import RoleCode
from app.models.service_engineer import ServiceEngineerProfileOut, ServiceEngineerProfileUpdate


class UserBase(StrictModel):
    email: EmailStr
    username: Username
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    roles: list[RoleCode] = Field(default_factory=list)


class UserCreate(UserBase):
    password: Password


class UserUpdate(StrictModel):
    email: EmailStr | None = None
    username: Username | None = None
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    roles: list[RoleCode] | None = None
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
