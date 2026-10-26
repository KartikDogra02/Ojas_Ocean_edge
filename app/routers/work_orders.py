from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import ReturnDocument

from app.auth import CurrentPrincipal, Principal, require_roles
from app.db import get_db
from app.models.common import utcnow
from app.models.role import Role
from app.models.work_order import (
    ServiceType,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderStatus,
    WorkOrderUpdate,
    WorkPlanConversion,
)
from app.models.work_plan import Priority
from app.routers.work_plans import engineers_by_id, own_engineer_id, plan_lookup, plan_visibility, validate_engineers
from app.services import next_sequence

router = APIRouter(tags=["work-orders"])
# Only the technical team creates work orders, directly or by converting a work plan.
Dispatcher = Annotated[
    Principal, Depends(require_roles(Role.TECHNICAL_TEAM, detail="Only the technical team can dispatch work orders"))
]
Editor = Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.TECHNICAL_TEAM))]


def _lead(engineer_ids: list[str], lead: str | None) -> str:
    if lead is None:
        return engineer_ids[0]
    if lead not in engineer_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "lead_engineer_id must be one of the assigned engineers"
        )
    return lead


async def _out(docs: list[dict]) -> list[WorkOrderOut]:
    engineers = await engineers_by_id({e for d in docs for e in d["assigned_engineer_ids"]})
    return [
        WorkOrderOut(
            **d
            | {
                "id": str(d["_id"]),
                "lead_engineer": engineers.get(d["lead_engineer_id"]),
                "assigned_engineers": [engineers[e] for e in d["assigned_engineer_ids"] if e in engineers],
                "work_plan": d["work_plan"] | {"id": str(d["work_plan"]["id"])} if d.get("work_plan") else None,
                "field_service_report": d["field_service_report"] | {"id": str(d["field_service_report"]["id"])}
                if d.get("field_service_report")
                else None,
            }
        )
        for d in docs
    ]


def _lookup(id_or_number: str) -> dict:
    if ObjectId.is_valid(id_or_number):
        return {"_id": ObjectId(id_or_number)}
    return {"work_order_number": id_or_number.upper()}


async def _get(id_or_number: str, extra: dict | None = None) -> dict:
    doc = await get_db().work_orders.find_one(_lookup(id_or_number) | (extra or {}))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    return doc


async def _insert(fields: dict, creator: Principal, work_order_id: ObjectId | None = None) -> dict:
    now = utcnow()
    doc = fields | {
        "_id": work_order_id or ObjectId(),
        "work_order_number": fields.get("work_order_number") or await next_sequence("work_order", "WO"),
        "status": WorkOrderStatus.DISPATCHED.value,
        "created_by": creator.username,
        "created_at": now,
        "updated_at": now,
    }
    await get_db().work_orders.insert_one(doc)
    return doc


@router.post("/work-orders", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
async def create_work_order(body: WorkOrderCreate, dispatcher: Dispatcher):
    """Create and dispatch a work order directly."""
    engineer_ids = await validate_engineers(body.assigned_engineer_ids)
    fields = body.model_dump(mode="json") | {
        "assigned_engineer_ids": engineer_ids,
        "lead_engineer_id": _lead(engineer_ids, body.lead_engineer_id),
        "work_plan": None,
    }
    return (await _out([await _insert(fields, dispatcher)]))[0]


@router.post(
    "/work-plans/{plan_id_or_number}/convert",
    response_model=WorkOrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def convert_work_plan(plan_id_or_number: str, body: WorkPlanConversion, dispatcher: Dispatcher):
    """Turn a work plan into a dispatched work order. The plan is then marked converted and locked."""
    db = get_db()
    plan = await db.work_plans.find_one(plan_lookup(plan_id_or_number))
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work plan not found")
    if plan.get("work_order"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Work plan was already converted to {plan['work_order']['work_order_number']}"
        )
    engineer_ids = await validate_engineers(body.assigned_engineer_ids or plan["assigned_engineer_ids"])
    if not engineer_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Assign at least one engineer to the plan (or in this request) first"
        )
    fields = {
        "title": plan["title"],
        "service_type": body.service_type.value,
        "priority": (body.priority or Priority(plan["priority"])).value,
        "estimated_duration_days": plan.get("estimated_duration_days"),
        "assigned_engineer_ids": engineer_ids,
        "lead_engineer_id": _lead(engineer_ids, body.lead_engineer_id),
        "customer": plan["customer"],
        "equipment": body.equipment.model_dump(mode="json") if body.equipment else None,
        "scope_of_work": body.scope_of_work,
        "work_plan": {"id": plan["_id"], "plan_number": plan["plan_number"]},
        "work_order_number": await next_sequence("work_order", "WO"),
    }
    work_order_id = ObjectId()
    # Claim the plan first, so two people converting it at once can't both create a work order.
    claimed = await db.work_plans.find_one_and_update(
        {"_id": plan["_id"], "work_order": {"$exists": False}},
        {
            "$set": {
                "work_order": {"id": work_order_id, "work_order_number": fields["work_order_number"]},
                "updated_at": utcnow(),
            }
        },
    )
    if claimed is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Work plan was converted by someone else just now")
    try:
        doc = await _insert(fields, dispatcher, work_order_id)
    except Exception:
        await db.work_plans.update_one({"_id": plan["_id"]}, {"$unset": {"work_order": ""}})
        raise
    return (await _out([doc]))[0]


@router.post("/work-orders/{id_or_number}/start", response_model=WorkOrderOut)
async def start_work_order(id_or_number: str, principal: CurrentPrincipal):
    """Mark a dispatched work order as in progress. Any engineer on its crew, or the technical team, can start it."""
    order = await _get(id_or_number)
    on_crew = await own_engineer_id(principal) in order["assigned_engineer_ids"]
    if not on_crew and Role.TECHNICAL_TEAM.value not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the crew or the technical team can start this work order")
    doc = await get_db().work_orders.find_one_and_update(
        {"_id": order["_id"], "status": WorkOrderStatus.DISPATCHED.value},
        {"$set": {"status": WorkOrderStatus.IN_PROGRESS.value, "started_at": utcnow(), "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Work order is already {order['status']}")
    return (await _out([doc]))[0]


@router.get("/work-orders", response_model=list[WorkOrderOut])
async def list_work_orders(
    principal: CurrentPrincipal,
    priority: Priority | None = None,
    service_type: ServiceType | None = None,
    status_: Annotated[WorkOrderStatus | None, Query(alias="status")] = None,
    engineer_id: str | None = None,
    customer: str | None = None,
    work_plan: Annotated[str | None, Query(description="Work plan number, e.g. WP-2026-001")] = None,
    skip: int = 0,
    limit: int = 100,
):
    """Admin, HR and technical team see every work order; service engineers only those they're assigned to."""
    query = await plan_visibility(principal)
    if priority is not None:
        query["priority"] = priority.value
    if service_type is not None:
        query["service_type"] = service_type.value
    if status_ is not None:
        query["status"] = status_.value
    if engineer_id is not None:
        query.setdefault("assigned_engineer_ids", engineer_id.upper())
        if query["assigned_engineer_ids"] != engineer_id.upper():
            return []  # an engineer asking about someone else's work orders
    if customer is not None:
        query["customer.company"] = customer
    if work_plan is not None:
        query["work_plan.plan_number"] = work_plan.upper()
    cursor = get_db().work_orders.find(query).sort("created_at", -1).skip(skip).limit(limit)
    return await _out([d async for d in cursor])


@router.get("/work-orders/{id_or_number}", response_model=WorkOrderOut)
async def get_work_order(id_or_number: str, principal: CurrentPrincipal):
    """Look up by id or work order number (e.g. WO-2026-001)."""
    return (await _out([await _get(id_or_number, await plan_visibility(principal))]))[0]


@router.patch("/work-orders/{id_or_number}", response_model=WorkOrderOut)
async def update_work_order(id_or_number: str, body: WorkOrderUpdate, _: Editor):
    order = await _get(id_or_number)
    changes = body.model_dump(mode="json", exclude_unset=True)
    for field in ("title", "service_type", "priority", "customer", "assigned_engineer_ids", "lead_engineer_id"):
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{field} can't be cleared")
    engineer_ids = order["assigned_engineer_ids"]
    if "assigned_engineer_ids" in changes:
        engineer_ids = changes["assigned_engineer_ids"] = await validate_engineers(changes["assigned_engineer_ids"])
    lead = changes.get("lead_engineer_id", order["lead_engineer_id"])
    # Keep the lead valid: if the new crew drops the current lead, the first engineer takes over.
    if "lead_engineer_id" in changes:
        changes["lead_engineer_id"] = _lead(engineer_ids, lead)
    elif lead not in engineer_ids:
        changes["lead_engineer_id"] = engineer_ids[0]
    changes["updated_at"] = utcnow()
    doc = await get_db().work_orders.find_one_and_update(
        {"_id": order["_id"]}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    return (await _out([doc]))[0]


@router.delete("/work-orders/{id_or_number}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_order(id_or_number: str, _: Editor):
    """Delete a work order. If it came from a work plan, the plan is unlocked again."""
    order = await _get(id_or_number)
    await get_db().work_orders.delete_one({"_id": order["_id"]})
    if order.get("work_plan"):
        await get_db().work_plans.update_one(
            {"_id": order["work_plan"]["id"]}, {"$unset": {"work_order": ""}, "$set": {"updated_at": utcnow()}}
        )
