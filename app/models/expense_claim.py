from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.common import LabeledEnum, StrictModel


class ExpenseCategory(LabeledEnum):
    TRAVEL_FUEL = "travel_fuel", "Travel & Fuel"
    HOTEL_LODGING = "hotel_lodging", "Hotel / Lodging"
    FIELD_MEALS = "field_meals", "Field Meals"
    TOOLS_EQUIPMENT = "tools_equipment", "Tools & Equipment"
    EMERGENCY_SPARE = "emergency_spare", "Emergency Spare Purchase"
    TOLLS_PARKING = "tolls_parking", "Tolls & Parking"
    OTHER = "other", "Other Operational"


class ExpenseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExpenseClaimCreate(StrictModel):
    category: ExpenseCategory
    # USD. May be left out for Travel & Fuel when distance_km is given; it's then calculated at the mileage rate.
    amount: Decimal | None = Field(default=None, gt=0, le=1_000_000, decimal_places=2)
    distance_km: float | None = Field(default=None, gt=0, le=100_000)
    # Work plan id or number (e.g. WP-2026-001). Leave out for a general, non-work-order expense.
    work_plan: str | None = None
    description: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _amount_or_distance(self):
        if self.distance_km is not None and self.category is not ExpenseCategory.TRAVEL_FUEL:
            raise ValueError("distance_km is only allowed for the travel_fuel category")
        if self.amount is None and self.distance_km is None:
            raise ValueError("amount is required (or distance_km for travel_fuel)")
        return self


class ReviewDecision(StrictModel):
    note: str | None = Field(default=None, max_length=1000)


class Rejection(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)


class Claimant(BaseModel):
    user_id: str
    username: str
    full_name: str | None = None


class TaggedWorkPlan(BaseModel):
    id: str
    plan_number: str
    title: str


class Receipt(BaseModel):
    filename: str
    content_type: str
    size: int


class Review(BaseModel):
    reviewed_by: str
    reviewed_at: datetime
    note: str | None = None


class ExpenseClaimOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    claim_number: str
    claimant: Claimant
    category: ExpenseCategory
    amount: float
    currency: str = "USD"
    distance_km: float | None = None
    mileage_rate_per_km: float | None = None
    work_plan: TaggedWorkPlan | None = None
    description: str
    receipt: Receipt | None = None
    status: ExpenseStatus
    review: Review | None = None
    created_at: datetime
    updated_at: datetime
