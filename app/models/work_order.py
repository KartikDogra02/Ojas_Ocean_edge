from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict, Field

from app.models.common import LabeledEnum, StrictModel
from app.models.work_plan import AssignedEngineer, Customer, EngineerId, Priority


class ServiceType(LabeledEnum):
    PREVENTIVE_MAINTENANCE = "preventive_maintenance", "Preventive Maintenance"
    BREAKDOWN_REPAIR = "breakdown_repair", "Breakdown Repair"
    CALIBRATION = "calibration", "Calibration & Verification"
    INSTALLATION = "installation", "Installation & Commissioning"
    INSPECTION = "inspection", "Inspection & Survey"
    EMERGENCY_CALLOUT = "emergency_callout", "Emergency Call-out"


class WorkOrderStatus(StrEnum):
    DISPATCHED = "dispatched"


class Equipment(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)


class WorkOrderCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    service_type: ServiceType
    priority: Priority = Priority.MEDIUM
    estimated_duration_days: float | None = Field(default=None, gt=0, le=365)  # e.g. 0.5 for half a day
    # At least one engineer; the lead is the primary contact on the dispatch ticket (defaults to the first).
    assigned_engineer_ids: list[EngineerId] = Field(min_length=1, max_length=50)
    lead_engineer_id: EngineerId | None = None
    customer: Customer
    equipment: Equipment | None = None
    scope_of_work: str | None = Field(default=None, max_length=5000)


class WorkPlanConversion(StrictModel):
    """Extra details needed to turn a work plan into a work order; everything else is copied from the plan."""

    service_type: ServiceType
    lead_engineer_id: EngineerId | None = None
    equipment: Equipment | None = None
    scope_of_work: str | None = Field(default=None, max_length=5000)
    # Optional overrides of the plan's values.
    priority: Priority | None = None
    assigned_engineer_ids: list[EngineerId] | None = Field(default=None, min_length=1, max_length=50)


class WorkOrderUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    service_type: ServiceType | None = None
    priority: Priority | None = None
    # null clears it
    estimated_duration_days: float | None = Field(default=None, gt=0, le=365)  # e.g. 0.5 for half a day
    # Replaces the whole crew (at least one engineer).
    assigned_engineer_ids: list[EngineerId] | None = Field(default=None, min_length=1, max_length=50)
    lead_engineer_id: EngineerId | None = None
    customer: Customer | None = None
    equipment: Equipment | None = None
    scope_of_work: str | None = Field(default=None, max_length=5000)


class WorkPlanRef(StrictModel):
    id: str
    plan_number: str


class WorkOrderOut(StrictModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    work_order_number: str
    title: str
    service_type: ServiceType
    priority: Priority
    status: WorkOrderStatus
    estimated_duration_days: float | None = None
    lead_engineer: AssignedEngineer | None = None
    assigned_engineers: list[AssignedEngineer]
    customer: Customer
    equipment: Equipment | None = None
    scope_of_work: str | None = None
    work_plan: WorkPlanRef | None = None  # set when converted from a work plan
    created_by: str
    created_at: datetime
    updated_at: datetime
