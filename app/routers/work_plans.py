from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import ReturnDocument

from app.auth import CurrentPrincipal, Principal, require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.role import Role
from app.models.work_plan import (
    AssignedEngineer,
    Priority,
    WorkPlanCreate,
    WorkPlanOut,
    WorkPlanStatus,
    WorkPlanUpdate,
)
from app.services import next_sequence

router = APIRouter(prefix="/work-plans", tags=["work-plans"])
Planner = Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.TECHNICAL_TEAM))]

_VIEW_ALL = {Role.ADMIN.value, Role.HR_TEAM.value, Role.TECHNICAL_TEAM.value}


async def _validate_engineers(engineer_ids: list[str]) -> list[str]:
    """De-duplicate and check every ID belongs to an active service engineer."""
    ids = list(dict.fromkeys(engineer_ids))
    if not ids:
        return ids
    found = await get_db().users.distinct(
        "service_engineer.engineer_id",
        {"service_engineer.engineer_id": {"$in": ids}, "roles": Role.SERVICE_ENGINEER.value, "is_active": True},
    )
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown or inactive service engineer(s): {', '.join(missing)}"
        )
    return ids


async def _engineers_by_id(engineer_ids: set[str]) -> dict[str, AssignedEngineer]:
    cursor = get_db().users.find(
        {"service_engineer.engineer_id": {"$in": list(engineer_ids)}},
        {"full_name": 1, "is_active": 1, "service_engineer.engineer_id": 1, "service_engineer.territory": 1},
    )
    return {
        u["service_engineer"]["engineer_id"]: AssignedEngineer(
            engineer_id=u["service_engineer"]["engineer_id"],
            user_id=str(u["_id"]),
            full_name=u.get("full_name"),
            territory=u["service_engineer"].get("territory"),
            is_active=u.get("is_active", False),
        )
        async for u in cursor
    }


async def _out(docs: list[dict]) -> list[WorkPlanOut]:
    """Attach current engineer details (name, territory) to each plan."""
    engineers = await _engineers_by_id({e for d in docs for e in d["assigned_engineer_ids"]})
    return [
        WorkPlanOut(
            **d,
            id=str(d["_id"]),
            status=WorkPlanStatus.ASSIGNED if d["assigned_engineer_ids"] else WorkPlanStatus.DRAFT,
            assigned_engineers=[engineers[e] for e in d["assigned_engineer_ids"] if e in engineers],
        )
        for d in docs
    ]


async def _own_engineer_id(principal: Principal) -> str | None:
    user = await get_db().users.find_one({"_id": principal.user_id}, {"service_engineer.engineer_id": 1})
    return (user or {}).get("service_engineer", {}).get("engineer_id")


async def _visibility(principal: Principal) -> dict:
    """Admin, HR and technical team see every plan; service engineers only plans they're assigned to."""
    if principal.roles & _VIEW_ALL:
        return {}
    if Role.SERVICE_ENGINEER.value in principal.roles:
        return {"assigned_engineer_ids": await _own_engineer_id(principal)}
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")


def _lookup(plan_id_or_number: str) -> dict:
    if ObjectId.is_valid(plan_id_or_number):
        return {"_id": ObjectId(plan_id_or_number)}
    return {"plan_number": plan_id_or_number.upper()}


async def _get(plan_id_or_number: str, extra: dict | None = None) -> dict:
    doc = await get_db().work_plans.find_one(_lookup(plan_id_or_number) | (extra or {}))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work plan not found")
    return doc


@router.post("", response_model=WorkPlanOut, status_code=status.HTTP_201_CREATED)
async def create_work_plan(body: WorkPlanCreate, planner: Planner):
    engineer_ids = await _validate_engineers(body.assigned_engineer_ids)
    now = utcnow()
    doc = body.model_dump(mode="json") | {
        "assigned_engineer_ids": engineer_ids,
        "plan_number": await next_sequence("work_plan", "WP"),
        "created_by": planner.username,
        "created_at": now,
        "updated_at": now,
    }
    await get_db().work_plans.insert_one(doc)
    return (await _out([doc]))[0]


@router.get("", response_model=list[WorkPlanOut])
async def list_work_plans(
    principal: CurrentPrincipal,
    priority: Priority | None = None,
    status_: Annotated[WorkPlanStatus | None, Query(alias="status")] = None,
    engineer_id: str | None = None,
    customer: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    query = await _visibility(principal)
    if priority is not None:
        query["priority"] = priority.value
    if status_ is not None:
        query["assigned_engineer_ids.0"] = {"$exists": status_ is WorkPlanStatus.ASSIGNED}
    if engineer_id is not None:
        query.setdefault("assigned_engineer_ids", engineer_id.upper())
        if query["assigned_engineer_ids"] != engineer_id.upper():
            return []  # an engineer asking about someone else's plans
    if customer is not None:
        query["customer.company"] = customer
    cursor = get_db().work_plans.find(query).sort("created_at", -1).skip(skip).limit(limit)
    return await _out([d async for d in cursor])


@router.get("/{plan_id_or_number}", response_model=WorkPlanOut)
async def get_work_plan(plan_id_or_number: str, principal: CurrentPrincipal):
    """Look up by id or plan number (e.g. WP-2026-001)."""
    return (await _out([await _get(plan_id_or_number, await _visibility(principal))]))[0]


@router.patch("/{plan_id_or_number}", response_model=WorkPlanOut)
async def update_work_plan(plan_id_or_number: str, body: WorkPlanUpdate, _: Planner):
    plan = await _get(plan_id_or_number)
    changes = body.model_dump(mode="json", exclude_unset=True)
    for field in ("title", "priority", "customer", "assigned_engineer_ids"):
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} can't be cleared")
    if "assigned_engineer_ids" in changes:
        changes["assigned_engineer_ids"] = await _validate_engineers(changes["assigned_engineer_ids"])
    changes["updated_at"] = utcnow()
    doc = await get_db().work_plans.find_one_and_update(
        {"_id": plan["_id"]}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    return (await _out([doc]))[0]


@router.delete("/{plan_id_or_number}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_plan(plan_id_or_number: str, _: Planner):
    plan = await _get(plan_id_or_number)
    await get_db().work_plans.delete_one({"_id": plan["_id"]})
