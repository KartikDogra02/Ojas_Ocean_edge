from datetime import datetime

from fastapi import APIRouter, Depends, Response

from app.auth import require_roles
from app.db import get_db
from app.models.audit import AuditEntry
from app.models.role import Role
from app.routers.common import Limit, Skip, set_total

router = APIRouter(
    prefix="/audit-log",
    tags=["audit-log"],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.OWNER, detail="Only admin and owner can view the audit log"))],
)


@router.get("", response_model=list[AuditEntry])
async def list_audit_entries(
    response: Response,
    entity_type: str | None = None,
    entity: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
):
    """Who changed what, newest first. `entity` matches a record's id or number (e.g. WO-2026-001)."""
    query: dict = {}
    if entity_type:
        query["entity.type"] = entity_type
    if entity:
        query["$or"] = [{"entity.id": entity}, {"entity.number": entity.upper()}]
    if actor:
        query["actor.username"] = actor.lower()
    if action:
        query["action"] = action
    if since or until:
        query["at"] = {k: v for k, v in (("$gte", since), ("$lt", until)) if v}
    await set_total(response, get_db().audit_log, query)
    cursor = get_db().audit_log.find(query).sort("at", -1).skip(skip).limit(limit)
    return [
        AuditEntry.model_validate(
            d | {"id": str(d["_id"]), "actor": d["actor"] | {"user_id": str(d["actor"]["user_id"])}}
        )
        async for d in cursor
    ]
