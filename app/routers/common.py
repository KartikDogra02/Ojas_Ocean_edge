from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status

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
