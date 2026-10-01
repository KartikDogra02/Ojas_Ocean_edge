from datetime import date
from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from app.models.common import StrictModel, Timestamps


def _upper(v: object) -> object:
    return v.upper() if isinstance(v, str) else v


# Codes like "FLK-754-009183", "NIST-STD-2026-131", "LAB-SAFE-02".
Code = Annotated[str, BeforeValidator(_upper), Field(min_length=1, max_length=50, pattern=r"^[A-Z0-9][A-Z0-9._/-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=200)]


class ReferenceStandardCreate(StrictModel):
    name: Text
    make: Text
    model: Text
    serial_number: Code
    master_cert_number: Code
    calibration_date: date
    due_date: date
    traceability_agency: str | None = Field(default=None, max_length=200)
    storage_location_id: Code | None = None

    @model_validator(mode="after")
    def _due_after_calibration(self):
        if self.due_date <= self.calibration_date:
            raise ValueError("due_date must be after calibration_date")
        return self


class ReferenceStandardUpdate(StrictModel):
    name: Text | None = None
    make: Text | None = None
    model: Text | None = None
    serial_number: Code | None = None
    master_cert_number: Code | None = None
    calibration_date: date | None = None
    due_date: date | None = None
    traceability_agency: str | None = Field(default=None, max_length=200)
    storage_location_id: Code | None = None


class ReferenceStandardOut(ReferenceStandardCreate, Timestamps):
    model_config = ConfigDict(extra="ignore")

    id: str
    created_by: str | None = None
