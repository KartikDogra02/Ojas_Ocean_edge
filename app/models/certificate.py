from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import LabeledEnum, StrictModel
from app.models.reference_standard import Code, Text


class InstrumentType(LabeledEnum):
    FIXED_GAS = "fixed_gas", "Fixed Gas"
    PORTABLE_GAS = "portable_gas", "Portable Gas"
    UTI_DETECTOR = "uti_detector", "UTI Detector"
    TEMP_PRESSURE = "temp_pressure", "Temp & Pressure"
    VOLT_AMMETER = "volt_ammeter", "Volt & Ammeter"
    PROCESS_CALIBRATOR = "process_calibrator", "Process Calibrator"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class TestPoint(StrictModel):
    """One row of the calibration measurements table. Deviation and status are calculated by the server."""

    parameter: str | None = Field(default=None, max_length=100)  # e.g. "Setpoint 100 bar"
    nominal_value: Decimal
    observed_value: Decimal
    unit: str | None = Field(default=None, max_length=20)
    # Allowed deviation either side of nominal (e.g. 0.05 for ±0.05). Without it the row has no pass/fail status.
    tolerance: Decimal | None = Field(default=None, ge=0)


class TestPointResult(BaseModel):
    parameter: str | None = None
    nominal_value: float
    observed_value: float
    deviation: float  # observed - nominal
    unit: str | None = None
    tolerance: float | None = None
    status: Verdict | None = None  # pass when |deviation| <= tolerance


class CertificateCreate(StrictModel):
    instrument_type: InstrumentType
    customer: Text
    serial_number: Code
    model: str | None = Field(default=None, max_length=200)
    result: Verdict
    reference_standard_ids: list[str] = Field(min_length=1, max_length=20)
    # Defaults to today.
    calibration_date: date | None = None
    test_points: list[TestPoint] = Field(default_factory=list, max_length=50)


class ReferenceStandardSnapshot(StrictModel):
    """The standard's details as they were when the certificate was issued."""

    id: str
    name: str
    make: str
    model: str
    serial_number: str
    master_cert_number: str
    due_date: date


class CertificateOut(StrictModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    certificate_number: str
    instrument_type: InstrumentType
    customer: str
    serial_number: str
    model: str | None = None
    result: Verdict
    calibration_date: date
    reference_standards: list[ReferenceStandardSnapshot]
    test_points: list[TestPointResult] = []
    issued_by: str
    created_at: datetime
