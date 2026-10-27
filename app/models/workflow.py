from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from app.models.work_order import Equipment, ServiceType, WorkOrderStatus
from app.models.work_plan import AssignedEngineer, Priority, WorkPlanStatus


class PipelineStage(StrEnum):
    STAGED = "staged"  # work plan not yet converted
    DISPATCHED = "dispatched"  # work order dispatched
    IN_PROGRESS = "in_progress"  # crew working on it
    REPORTED = "reported"  # FSR submitted, no ISO certificate yet
    CERTIFIED = "certified"  # ISO certificate issued


class ChainPlan(BaseModel):
    id: str
    plan_number: str
    status: WorkPlanStatus
    estimated_duration_days: float | None = None
    created_at: datetime


class ChainWorkOrder(BaseModel):
    id: str
    work_order_number: str
    status: WorkOrderStatus
    service_type: ServiceType
    site_address: str | None = None
    created_at: datetime


class ChainCrew(BaseModel):
    lead_engineer_id: str | None = None
    engineers: list[AssignedEngineer]


class ChainFsr(BaseModel):
    id: str
    fsr_number: str
    customer_rep_name: str
    customer_satisfaction: int
    spare_parts_count: int
    parts_total: float
    submitted_at: datetime


class ChainCertificate(BaseModel):
    id: str
    certificate_number: str
    result: str
    calibration_date: date


class ChainExpenses(BaseModel):
    count: int = 0
    total: float = 0.0  # USD, all non-rejected claims


class WorkflowChain(BaseModel):
    title: str
    priority: Priority
    customer: str
    service_type: ServiceType | None = None
    equipment: Equipment | None = None
    stage: PipelineStage
    completion: int  # percent of the 5 steps done: plan, work order, crew, FSR, ISO certificate
    plan: ChainPlan | None = None  # None for work orders created directly
    work_order: ChainWorkOrder | None = None
    crew: ChainCrew
    fsr: ChainFsr | None = None
    certificates: list[ChainCertificate] = []
    expenses: ChainExpenses


class WorkflowSummary(BaseModel):
    total_chains: int
    staged_plans: int  # awaiting conversion
    work_orders_dispatched: int
    field_ops_in_progress: int
    reported: int  # FSR in, awaiting ISO certificate
    iso_certified: int


class Workflow(BaseModel):
    summary: WorkflowSummary
    chains: list[WorkflowChain]
