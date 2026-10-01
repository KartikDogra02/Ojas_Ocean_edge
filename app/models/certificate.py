from datetime import date, datetime
from enum import StrEnum

from pydantic import ConfigDict, Field

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
    reference_value: float
    measured_value: float
    unit: str | None = Field(default=None, max_length=20)


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
    test_points: list[TestPoint] = []
    issued_by: str
    created_at: datetime
