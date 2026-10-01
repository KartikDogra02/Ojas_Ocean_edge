from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, EmailStr, Field

from app.models.common import LabeledEnum, StrictModel
from app.models.service_engineer import Phone
from app.models.territory import Territory


class Priority(LabeledEnum):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class WorkPlanStatus(StrEnum):
    DRAFT = "draft"  # no engineers assigned yet
    ASSIGNED = "assigned"


def _upper(v: object) -> object:
    return v.upper() if isinstance(v, str) else v


EngineerId = Annotated[str, BeforeValidator(_upper), Field(pattern=r"^ENG-\d{4}-\d{3,}$")]


class Customer(StrictModel):
    company: str = Field(min_length=1, max_length=200)
    contact_person: str | None = Field(default=None, max_length=200)
    contact_phone: Phone | None = None
    contact_email: EmailStr | None = None
    site_address: str | None = Field(default=None, max_length=500)


class WorkPlanCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    priority: Priority = Priority.MEDIUM
    customer: Customer
    # Engineer IDs such as ENG-2026-101. Leave empty to save as a draft and assign later.
    assigned_engineer_ids: list[EngineerId] = Field(default_factory=list, max_length=50)


class WorkPlanUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    priority: Priority | None = None
    customer: Customer | None = None
    # Replaces the whole crew; [] unassigns everyone.
    assigned_engineer_ids: list[EngineerId] | None = Field(default=None, max_length=50)


class AssignedEngineer(StrictModel):
    engineer_id: str
    user_id: str
    full_name: str | None = None
    territory: Territory | None = None
    is_active: bool


class WorkPlanOut(StrictModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    plan_number: str
    title: str
    priority: Priority
    status: WorkPlanStatus
    customer: Customer
    assigned_engineers: list[AssignedEngineer]
    created_by: str
    created_at: datetime
    updated_at: datetime
