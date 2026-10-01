from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.auth import Principal, require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.reference_standard import ReferenceStandardCreate, ReferenceStandardOut, ReferenceStandardUpdate
from app.models.role import Role
from app.routers.common import from_doc, to_oid

router = APIRouter(prefix="/reference-standards", tags=["reference-standards"])
Creator = Annotated[Principal, Depends(require_roles(Role.TECHNICAL_TEAM, Role.SERVICE_ENGINEER))]
Editor = Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.TECHNICAL_TEAM))]

_DATE_FIELDS = ("calibration_date", "due_date")
_DUPLICATE_LABELS = {"serial_number": "Serial number", "master_cert_number": "Master cert number"}


def _to_mongo(date_value: date) -> datetime:
    # BSON has no date-only type; store dates as midnight UTC.
    return datetime.combine(date_value, time(), UTC)


def _dates_to_mongo(values: dict) -> dict:
    return {k: _to_mongo(v) if k in _DATE_FIELDS and v is not None else v for k, v in values.items()}


def _out(doc: dict) -> ReferenceStandardOut:
    doc = from_doc(doc)
    for field in _DATE_FIELDS:
        doc[field] = doc[field].date()
    return ReferenceStandardOut(**doc)


def _duplicate(exc: DuplicateKeyError) -> HTTPException:
    field = next(iter((exc.details or {}).get("keyPattern", {})), "")
    return HTTPException(status.HTTP_409_CONFLICT, f"{_DUPLICATE_LABELS.get(field, 'Value')} already in use")


async def _get(standard_id: str) -> dict:
    doc = await get_db().reference_standards.find_one({"_id": to_oid(standard_id)})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference standard not found")
    return doc


@router.post("", response_model=ReferenceStandardOut, status_code=status.HTTP_201_CREATED)
async def create_reference_standard(body: ReferenceStandardCreate, creator: Creator):
    now = utcnow()
    doc = _dates_to_mongo(body.model_dump()) | {"created_by": creator.username, "created_at": now, "updated_at": now}
    try:
        await get_db().reference_standards.insert_one(doc)
    except DuplicateKeyError as exc:
        raise _duplicate(exc)
    return _out(doc)


@router.get("", response_model=list[ReferenceStandardOut])
async def list_reference_standards(
    due_before: date | None = None,
    storage_location_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """Sorted by due date, soonest first. `due_before` finds equipment needing recalibration."""
    query: dict = {}
    if due_before is not None:
        query["due_date"] = {"$lt": _to_mongo(due_before)}
    if storage_location_id is not None:
        query["storage_location_id"] = storage_location_id.upper()
    cursor = get_db().reference_standards.find(query).sort("due_date", 1).skip(skip).limit(limit)
    return [_out(d) async for d in cursor]


@router.get("/{standard_id}", response_model=ReferenceStandardOut)
async def get_reference_standard(standard_id: str):
    return _out(await _get(standard_id))


@router.patch("/{standard_id}", response_model=ReferenceStandardOut)
async def update_reference_standard(standard_id: str, body: ReferenceStandardUpdate, _: Editor):
    existing = await _get(standard_id)
    changes = body.model_dump(exclude_unset=True)
    required = set(ReferenceStandardCreate.model_fields) - {"traceability_agency", "storage_location_id"}
    if any(changes.get(k, "") is None for k in required):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Required fields can't be cleared")
    calibration = changes.get("calibration_date", existing["calibration_date"].date())
    due = changes.get("due_date", existing["due_date"].date())
    if due <= calibration:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "due_date must be after calibration_date")

    changes = _dates_to_mongo(changes) | {"updated_at": utcnow()}
    try:
        doc = await get_db().reference_standards.find_one_and_update(
            {"_id": existing["_id"]}, {"$set": changes}, return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError as exc:
        raise _duplicate(exc)
    return _out(doc)


@router.delete("/{standard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_standard(standard_id: str, _: Editor):
    oid = to_oid(standard_id)
    used_by = await get_db().certificates.count_documents({"reference_standard_ids": oid})
    if used_by:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Reference standard is used by {used_by} certificate(s)")
    result = await get_db().reference_standards.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reference standard not found")
