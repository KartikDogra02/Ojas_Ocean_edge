from datetime import UTC, date, datetime, time
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.models.role import Role
from app.storage import get_storage

# Never return the password hash.
USER_PROJECTION = {"hashed_password": 0}


def to_oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id") from None


# Service engineer accounts; the active ones are those who can be assigned and planned.
ENGINEER_FILTER: dict[str, Any] = {"roles": Role.SERVICE_ENGINEER.value}
ACTIVE_ENGINEER_FILTER: dict[str, Any] = ENGINEER_FILTER | {"is_active": True}


def id_or_number_query(value: str, number_field: str) -> dict:
    """Find a record by its id or its number (e.g. WO-2026-001, matched case-insensitively)."""
    if ObjectId.is_valid(value):
        return {"_id": ObjectId(value)}
    return {number_field: value.upper()}


def to_mongo_date(day: date) -> datetime:
    """BSON has no date-only type: calendar days are stored as midnight UTC."""
    return datetime.combine(day, time(), UTC)


def require_found(doc: dict | None, detail: str = "Not found") -> dict:
    """The document, or a 404 if a lookup or update matched nothing (e.g. it was deleted meanwhile)."""
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return doc


def from_doc(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class FileLink(BaseModel):
    url: str
    expires_in: int


def file_link(key: str, filename: str, content_type: str) -> FileLink:
    url = get_storage().link(key, filename, content_type)
    if url is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Direct file links need STORAGE_BACKEND=r2")
    return FileLink(url=url, expires_in=settings.file_link_expiry_seconds)
