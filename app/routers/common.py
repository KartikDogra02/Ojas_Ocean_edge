from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.storage import get_storage

# Never return the password hash.
USER_PROJECTION = {"hashed_password": 0}


def to_oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id")


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
