from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.common import StrictModel
from app.models.work_order import Equipment


class SparePart(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1, le=10_000)
    unit_cost: Decimal = Field(ge=0, le=10_000_000, decimal_places=2)  # USD


class FsrCreate(StrictModel):
    """The Digital Field Service Report. Submitting it completes the work order."""

    work_order: str  # id or number, e.g. WO-2026-001
    # Defaults to the work order's scope of work.
    initial_condition: str | None = Field(default=None, max_length=5000)
    root_cause: str = Field(min_length=1, max_length=5000)
    corrective_action: str = Field(min_length=1, max_length=5000)
    spare_parts: list[SparePart] = Field(default_factory=list, max_length=100)
    customer_rep_name: str = Field(min_length=1, max_length=200)
    customer_rep_designation: str | None = Field(default=None, max_length=200)
    customer_satisfaction: int = Field(default=5, ge=1, le=5)
    # The client's drawn signature as a PNG data URL ("data:image/png;base64,...") from the signature pad.
    client_signature: str | None = Field(default=None, max_length=2_000_000)


class FsrWorkOrder(BaseModel):
    id: str
    work_order_number: str
    title: str
    customer: str
    site_address: str | None = None
    equipment: Equipment | None = None


class SparePartOut(BaseModel):
    name: str
    quantity: int
    unit_cost: float
    line_total: float


class ClientSignature(BaseModel):
    size: int
    width: int
    height: int


class FsrSubmitter(BaseModel):
    username: str
    engineer_id: str | None = None
    full_name: str | None = None


class FsrOut(BaseModel):
    id: str
    fsr_number: str
    work_order: FsrWorkOrder
    initial_condition: str | None = None
    root_cause: str
    corrective_action: str
    spare_parts: list[SparePartOut]
    parts_total: float
    currency: str = "USD"
    customer_rep_name: str
    customer_rep_designation: str | None = None
    customer_satisfaction: int
    client_signature: ClientSignature | None = None  # image at GET /fsr/{id}/signature
    submitted_by: FsrSubmitter
    submitted_at: datetime
