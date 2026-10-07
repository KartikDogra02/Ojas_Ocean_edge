from datetime import UTC, date, datetime, time
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import Principal, require_roles
from app.db import get_db
from app.models.certificate import CertificateCreate, CertificateOut, InstrumentType, TestPoint, Verdict
from app.models.common import utcnow
from app.models.role import Role
from app.routers.common import from_doc, to_oid
from app.services import next_sequence

router = APIRouter(prefix="/certificates", tags=["certificates"])
Issuer = Annotated[Principal, Depends(require_roles(Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER))]
admin_only = [Depends(require_roles(Role.ADMIN))]


def _to_mongo(value: date) -> datetime:
    return datetime.combine(value, time(), UTC)


def _evaluate(point: TestPoint) -> dict:
    """Deviation (observed - nominal) in exact decimal arithmetic, and pass/fail against the tolerance."""
    deviation = point.observed_value - point.nominal_value
    status_ = None
    if point.tolerance is not None:
        status_ = Verdict.PASS.value if abs(deviation) <= point.tolerance else Verdict.FAIL.value
    return {
        "parameter": point.parameter,
        "nominal_value": float(point.nominal_value),
        "observed_value": float(point.observed_value),
        "deviation": float(deviation),
        "unit": point.unit,
        "tolerance": float(point.tolerance) if point.tolerance is not None else None,
        "status": status_,
    }


def _out(doc: dict) -> CertificateOut:
    doc = from_doc(doc)
    doc["calibration_date"] = doc["calibration_date"].date()
    doc["reference_standards"] = [
        s | {"id": str(s["id"]), "due_date": s["due_date"].date()} for s in doc["reference_standards"]
    ]
    return CertificateOut(**doc)


@router.post("", response_model=CertificateOut, status_code=status.HTTP_201_CREATED)
async def create_certificate(body: CertificateCreate, issuer: Issuer):
    """Issue a certificate. Every reference standard must exist and be in calibration on the calibration date."""
    db = get_db()
    calibration_date = body.calibration_date or utcnow().date()
    ids = list(dict.fromkeys(to_oid(i) for i in body.reference_standard_ids))
    standards = {s["_id"]: s async for s in db.reference_standards.find({"_id": {"$in": ids}})}
    missing = [str(i) for i in ids if i not in standards]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Reference standard(s) not found: {', '.join(missing)}")
    expired = [s["serial_number"] for s in standards.values() if s["due_date"].date() < calibration_date]
    if expired:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Reference standard(s) past their calibration due date: {', '.join(expired)}",
        )

    test_points = [_evaluate(p) for p in body.test_points]
    failed = [p["parameter"] or f"#{i}" for i, p in enumerate(test_points, 1) if p["status"] == Verdict.FAIL]
    if failed and body.result == Verdict.PASS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Result can't be pass: test point(s) out of tolerance: {', '.join(failed)}",
        )

    snapshot_fields = ("name", "make", "model", "serial_number", "master_cert_number", "due_date")
    doc = body.model_dump(exclude={"reference_standard_ids", "calibration_date", "test_points"}) | {
        "test_points": test_points,
        "certificate_number": await next_sequence("certificate", "CAL"),
        "calibration_date": _to_mongo(calibration_date),
        "reference_standard_ids": ids,
        "reference_standards": [{"id": i} | {f: standards[i][f] for f in snapshot_fields} for i in ids],
        "issued_by": issuer.username,
        "created_at": utcnow(),
    }
    await db.certificates.insert_one(doc)
    return _out(doc)


@router.get("", response_model=list[CertificateOut])
async def list_certificates(
    customer: str | None = None,
    serial_number: str | None = None,
    instrument_type: InstrumentType | None = None,
    result: Verdict | None = None,
    reference_standard_id: Annotated[str | None, Query(description="Certificates that used this standard")] = None,
    skip: int = 0,
    limit: int = 100,
):
    query: dict = {}
    if customer is not None:
        query["customer"] = customer
    if serial_number is not None:
        query["serial_number"] = serial_number.upper()
    if instrument_type is not None:
        query["instrument_type"] = instrument_type.value
    if result is not None:
        query["result"] = result.value
    if reference_standard_id is not None:
        query["reference_standard_ids"] = to_oid(reference_standard_id)
    cursor = get_db().certificates.find(query).sort("created_at", -1).skip(skip).limit(limit)
    return [_out(d) async for d in cursor]


@router.get("/{certificate_id_or_number}", response_model=CertificateOut)
async def get_certificate(certificate_id_or_number: str):
    """Look up by id or certificate number (e.g. CAL-2026-001)."""
    key = certificate_id_or_number
    query = {"_id": ObjectId(key)} if ObjectId.is_valid(key) else {"certificate_number": key.upper()}
    doc = await get_db().certificates.find_one(query)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
    return _out(doc)


@router.delete("/{certificate_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_certificate(certificate_id: str):
    result = await get_db().certificates.delete_one({"_id": to_oid(certificate_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found")
