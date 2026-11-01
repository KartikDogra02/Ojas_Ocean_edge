"""Audit log: who changed what, and when. Written by every endpoint that changes data."""

from typing import Any

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession

from app.auth import Principal
from app.db import get_db
from app.models.common import utcnow
from app.request_context import current_request

# Never stored in the audit log, even if they appear in a change.
_SECRET_FIELDS = {"password", "hashed_password", "current_password", "new_password", "client_signature", "key_hash"}
# Bookkeeping fields that change on every write and aren't worth recording.
_IGNORED_FIELDS = {"updated_at", "password_changed_at"}


def _value_at(doc: dict, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)  # type: ignore[assignment]
    return doc


def changes(before: dict, updates: dict) -> dict[str, list[Any]]:
    """{field: [before, after]} for every field an update changed. `updates` is a $set document, so dotted
    paths like "service_engineer.territory" are compared with the nested value. Secret fields are left out."""
    result = {}
    for path, value in updates.items():
        leaf = path.rsplit(".", 1)[-1]
        if leaf in _SECRET_FIELDS or path in _IGNORED_FIELDS:
            continue
        old = _value_at(before, path)
        if old != value:
            result[path] = [old, value]
    return result


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _SECRET_FIELDS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    return value


async def record(
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    number: str | None = None,
    *,
    changed: dict[str, list[Any]] | None = None,
    details: dict[str, Any] | None = None,
    session: AsyncClientSession | None = None,
) -> None:
    """Add an audit entry, e.g. record(admin, "update", "user", user_id, changed=changes(before, after)).

    Pass the `session` of a transaction to save the entry only if the change itself is committed.
    """
    request = current_request()
    await get_db().audit_log.insert_one(
        {
            "at": utcnow(),
            "actor": {
                "user_id": principal.user_id,
                "username": principal.username,
                "roles": sorted(principal.roles),
            },
            "action": action,
            "entity": {"type": entity_type, "id": str(entity_id) if entity_id is not None else None, "number": number},
            "changes": _clean(changed) if changed else None,
            "details": _clean(details) if details else None,
            "request_id": request.request_id if request else None,
        },
        session=session,
    )
