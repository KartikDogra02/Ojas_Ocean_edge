from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditActor(BaseModel):
    user_id: str
    username: str
    roles: list[str]


class AuditEntity(BaseModel):
    type: str
    id: str | None = None
    number: str | None = None


class AuditEntry(BaseModel):
    id: str
    at: datetime
    actor: AuditActor
    action: str
    entity: AuditEntity
    changes: dict[str, list[Any]] | None = None  # {field: [before, after]}
    details: dict[str, Any] | None = None
    request_id: str | None = None
