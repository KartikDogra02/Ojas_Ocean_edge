import base64
import binascii
from decimal import Decimal

from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from app.auth import CurrentPrincipal
from app.config import settings
from app.db import get_db
from app.models.common import utcnow
from app.models.fsr import FsrCreate, FsrOut
from app.models.work_order import WorkOrderStatus
from app.routers.common import FileLink, file_link
from app.routers.signatures import png_dimensions
from app.routers.work_plans import own_engineer_id, plan_visibility
from app.services import next_sequence
from app.storage import FileNotFound, get_storage

router = APIRouter(prefix="/fsr", tags=["field-service-reports"])

_OPEN = [WorkOrderStatus.DISPATCHED.value, WorkOrderStatus.IN_PROGRESS.value]


def _decode_signature(data_url: str) -> tuple[bytes, int, int]:
    """Decode the signature pad's PNG data URL; raise 422 if it isn't a valid PNG within the size limit."""
    payload = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "client_signature isn't valid base64")
    if len(data) > settings.signature_max_kb * 1024:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"client_signature must be {settings.signature_max_kb} KB or less"
        )
    dimensions = png_dimensions(data)
    if dimensions is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "client_signature must be a PNG image")
    return data, *dimensions


def _out(doc: dict) -> FsrOut:
    parts = [
        p | {"unit_cost": p["unit_cost_cents"] / 100, "line_total": p["quantity"] * p["unit_cost_cents"] / 100}
        for p in doc["spare_parts"]
    ]
    return FsrOut(
        **doc
        | {
            "id": str(doc["_id"]),
            "work_order": doc["work_order"] | {"id": str(doc["work_order"]["id"])},
            "spare_parts": parts,
            "parts_total": doc["parts_total_cents"] / 100,
        }
    )


def _lookup(id_or_number: str) -> dict:
    if ObjectId.is_valid(id_or_number):
        return {"_id": ObjectId(id_or_number)}
    return {"fsr_number": id_or_number.upper()}


async def _get(id_or_number: str, principal: CurrentPrincipal) -> dict:
    """Admin, HR and technical team see every FSR; service engineers only those for work orders they were on."""
    doc = await get_db().field_service_reports.find_one(_lookup(id_or_number) | await plan_visibility(principal))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field service report not found")
    return doc


@router.post("", response_model=FsrOut, status_code=status.HTTP_201_CREATED)
async def submit_fsr(body: FsrCreate, principal: CurrentPrincipal):
    """Submit the FSR for a work order you're on. This signs it off and completes the work order."""
    db = get_db()
    ref = body.work_order
    order = await db.work_orders.find_one(
        {"_id": ObjectId(ref)} if ObjectId.is_valid(ref) else {"work_order_number": ref.upper()}
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    engineer_id = await own_engineer_id(principal)
    if engineer_id not in order["assigned_engineer_ids"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only engineers on this work order's crew can submit its FSR")
    if order.get("field_service_report"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Work order already has FSR {order['field_service_report']['fsr_number']}"
        )
    if order["status"] not in _OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Work order is {order['status']}")
    signature = _decode_signature(body.client_signature) if body.client_signature else None

    fsr_id, fsr_number, now = ObjectId(), await next_sequence("fsr", "FSR"), utcnow()
    # Close the work order first, conditionally, so two engineers submitting at once can't both succeed.
    claimed = await db.work_orders.find_one_and_update(
        {"_id": order["_id"], "status": {"$in": _OPEN}, "field_service_report": None},
        {
            "$set": {
                "status": WorkOrderStatus.COMPLETED.value,
                "completed_at": now,
                "updated_at": now,
                "field_service_report": {"id": fsr_id, "fsr_number": fsr_number},
            }
        },
    )
    if claimed is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Work order was completed by someone else just now")

    signature_doc = None
    try:
        if signature:
            data, width, height = signature
            key = f"fsr/{fsr_number}/client-signature.png"
            await get_storage().put(key, data, "image/png")
            signature_doc = {"key": key, "size": len(data), "width": width, "height": height}
        parts = [
            {"name": p.name, "quantity": p.quantity, "unit_cost_cents": int(p.unit_cost * 100)}
            for p in body.spare_parts
        ]
        user = await db.users.find_one({"_id": principal.user_id}, {"username": 1, "full_name": 1})
        doc = {
            "_id": fsr_id,
            "fsr_number": fsr_number,
            "work_order": {
                "id": order["_id"],
                "work_order_number": order["work_order_number"],
                "title": order["title"],
                "customer": order["customer"]["company"],
                "site_address": order["customer"].get("site_address"),
                "equipment": order.get("equipment"),
            },
            # Same field as work orders, so the crew keeps access to the report.
            "assigned_engineer_ids": order["assigned_engineer_ids"],
            "initial_condition": body.initial_condition or order.get("scope_of_work"),
            "root_cause": body.root_cause,
            "corrective_action": body.corrective_action,
            "spare_parts": parts,
            "parts_total_cents": sum(p.quantity * int(p.unit_cost * 100) for p in body.spare_parts),
            "customer_rep_name": body.customer_rep_name,
            "customer_rep_designation": body.customer_rep_designation,
            "customer_satisfaction": body.customer_satisfaction,
            "client_signature": signature_doc,
            "submitted_by": {
                "user_id": principal.user_id,
                "username": user["username"],
                "engineer_id": engineer_id,
                "full_name": user.get("full_name"),
            },
            "submitted_at": now,
        }
        await db.field_service_reports.insert_one(doc)
    except Exception:
        if signature_doc:
            await get_storage().delete(signature_doc["key"])
        # Reopen the work order so the report can be submitted again.
        await db.work_orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"status": order["status"], "field_service_report": None}, "$unset": {"completed_at": ""}},
        )
        raise
    return _out(doc)


@router.get("", response_model=list[FsrOut])
async def list_fsrs(
    principal: CurrentPrincipal,
    work_order: str | None = None,
    customer: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    query = await plan_visibility(principal)
    if work_order is not None:
        query["work_order.work_order_number"] = work_order.upper()
    if customer is not None:
        query["work_order.customer"] = customer
    cursor = get_db().field_service_reports.find(query).sort("submitted_at", -1).skip(skip).limit(limit)
    return [_out(d) async for d in cursor]


@router.get("/{id_or_number}", response_model=FsrOut)
async def get_fsr(id_or_number: str, principal: CurrentPrincipal):
    """Look up by id or FSR number (e.g. FSR-2026-001)."""
    return _out(await _get(id_or_number, principal))


def _signature(doc: dict) -> dict:
    if not doc.get("client_signature"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This FSR has no client signature")
    return doc["client_signature"]


@router.get("/{id_or_number}/signature", response_class=Response)
async def get_fsr_signature(id_or_number: str, principal: CurrentPrincipal):
    """The client's signature as a PNG."""
    try:
        data = await get_storage().get(_signature(await _get(id_or_number, principal))["key"])
    except FileNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signature file is missing")
    return Response(data, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{id_or_number}/signature/link", response_model=FileLink)
async def fsr_signature_link(id_or_number: str, principal: CurrentPrincipal):
    doc = await _get(id_or_number, principal)
    return file_link(_signature(doc)["key"], f"{doc['fsr_number']}-client-signature.png", "image/png")
