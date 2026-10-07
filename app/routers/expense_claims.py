import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile
from pymongo import ReturnDocument

from app.auth import CurrentPrincipal, Principal
from app.config import settings
from app.db import get_db
from app.models.common import utcnow
from app.models.expense_claim import (
    ClaimAction,
    ExpenseCategory,
    ExpenseClaimCreate,
    ExpenseClaimOut,
    ExpenseStatus,
    Reimbursement,
    Rejection,
    ReviewDecision,
)
from app.models.role import Role
from app.routers.work_plans import plan_lookup, plan_visibility
from app.services import next_sequence

router = APIRouter(prefix="/expense-claims", tags=["expense-claims"])

# Approvers and HR see every claim; everyone else only their own.
_VIEW_ALL = {Role.ADMIN.value, Role.HR_TEAM.value, Role.TECHNICAL_TEAM.value, Role.OWNER.value}
# The claim status each role acts on.
_ACTS_ON = {
    Role.TECHNICAL_TEAM.value: ExpenseStatus.PENDING,
    Role.OWNER.value: ExpenseStatus.TECHNICAL_APPROVED,
    Role.HR_TEAM.value: ExpenseStatus.OWNER_APPROVED,
}

# Accepted receipt types, recognised by their first bytes rather than the uploaded name or header.
_SIGNATURES = [
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
]


def _receipts() -> AsyncGridFSBucket:
    return AsyncGridFSBucket(get_db(), bucket_name="receipts")


def _sniff(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((ctype for sig, ctype in _SIGNATURES if data.startswith(sig)), None)


def _safe_filename(name: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", (name or "receipt").rsplit("/", 1)[-1]).strip()
    return cleaned[:100] or "receipt"


def _out(doc: dict) -> ExpenseClaimOut:
    return ExpenseClaimOut(
        **doc
        | {
            "id": str(doc["_id"]),
            "amount": doc["amount_cents"] / 100,
            "claimant": doc["claimant"] | {"user_id": str(doc["claimant"]["user_id"])},
            "work_plan": doc["work_plan"] | {"id": str(doc["work_plan"]["id"])} if doc.get("work_plan") else None,
        }
    )


def _lookup(claim_id_or_number: str) -> dict:
    if ObjectId.is_valid(claim_id_or_number):
        return {"_id": ObjectId(claim_id_or_number)}
    return {"claim_number": claim_id_or_number.upper()}


async def _get(claim_id_or_number: str, principal: Principal) -> dict:
    """Claimants see their own claims; HR and admin see everyone's."""
    query = _lookup(claim_id_or_number)
    if not principal.roles & _VIEW_ALL:
        query["claimant.user_id"] = principal.user_id
    doc = await get_db().expense_claims.find_one(query)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense claim not found")
    return doc


async def _own_pending(claim_id_or_number: str, principal: Principal) -> dict:
    doc = await _get(claim_id_or_number, principal)
    if doc["claimant"]["user_id"] != principal.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the claimant can change this claim")
    if doc["status"] != ExpenseStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Claim has already been {doc['status']}")
    return doc


@router.post("", response_model=ExpenseClaimOut, status_code=status.HTTP_201_CREATED)
async def submit_expense_claim(body: ExpenseClaimCreate, principal: CurrentPrincipal):
    """Submit a claim for yourself. Attach a receipt afterwards with POST /expense-claims/{id}/receipt."""
    db = get_db()
    rate = Decimal(str(settings.mileage_rate_per_km))
    amount = body.amount
    if amount is None:
        amount = (Decimal(str(body.distance_km)) * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if amount <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Distance is too short to claim")

    work_plan = None
    if body.work_plan is not None:
        # You can only tag work plans you can see (service engineers: plans they're assigned to).
        plan = await db.work_plans.find_one(plan_lookup(body.work_plan) | await plan_visibility(principal))
        if plan is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Work plan not found")
        work_plan = {"id": plan["_id"], "plan_number": plan["plan_number"], "title": plan["title"]}

    user = await db.users.find_one({"_id": principal.user_id}, {"username": 1, "full_name": 1})
    now = utcnow()
    doc = {
        "claim_number": await next_sequence("expense_claim", "EXP"),
        "claimant": {"user_id": principal.user_id, "username": user["username"], "full_name": user.get("full_name")},
        "category": body.category.value,
        "amount_cents": int(amount * 100),
        "distance_km": body.distance_km,
        "mileage_rate_per_km": float(rate) if body.distance_km is not None else None,
        "work_plan": work_plan,
        "description": body.description,
        "receipt": None,
        "status": ExpenseStatus.PENDING.value,
        "history": [],
        "created_at": now,
        "updated_at": now,
    }
    await db.expense_claims.insert_one(doc)
    return _out(doc)


@router.get("", response_model=list[ExpenseClaimOut])
async def list_expense_claims(
    principal: CurrentPrincipal,
    status_: Annotated[ExpenseStatus | None, Query(alias="status")] = None,
    category: ExpenseCategory | None = None,
    claimant_id: Annotated[str | None, Query(description="HR/admin: one person's claims")] = None,
    work_plan: Annotated[str | None, Query(description="Work plan number, e.g. WP-2026-001")] = None,
    awaiting_my_action: bool = False,
    skip: int = 0,
    limit: int = 100,
):
    """Admin, HR, technical team and owner see every claim; everyone else sees their own.

    `awaiting_my_action=true` lists the claims waiting for you (others' claims at your stage).
    """
    query: dict = {}
    if not principal.roles & _VIEW_ALL:
        query["claimant.user_id"] = principal.user_id
    elif claimant_id is not None and ObjectId.is_valid(claimant_id):
        query["claimant.user_id"] = ObjectId(claimant_id)
    if status_ is not None:
        query["status"] = status_.value
    if category is not None:
        query["category"] = category.value
    if work_plan is not None:
        query["work_plan.plan_number"] = work_plan.upper()
    if awaiting_my_action:
        statuses = [_ACTS_ON[r].value for r in principal.roles if r in _ACTS_ON]
        if status_ is not None:
            statuses = [s for s in statuses if s == status_.value]
        query["status"] = {"$in": statuses}
        query["claimant.user_id"] = {"$ne": principal.user_id}
        query["history.user_id"] = {"$ne": principal.user_id}
    cursor = get_db().expense_claims.find(query).sort("created_at", -1).skip(skip).limit(limit)
    return [_out(d) async for d in cursor]


@router.get("/{claim_id_or_number}", response_model=ExpenseClaimOut)
async def get_expense_claim(claim_id_or_number: str, principal: CurrentPrincipal):
    return _out(await _get(claim_id_or_number, principal))


@router.delete("/{claim_id_or_number}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_expense_claim(claim_id_or_number: str, principal: CurrentPrincipal):
    """The claimant can withdraw a claim while it's still pending."""
    doc = await _own_pending(claim_id_or_number, principal)
    await get_db().expense_claims.delete_one({"_id": doc["_id"]})
    if doc.get("receipt"):
        await _receipts().delete(doc["receipt"]["file_id"])


# ---- Receipt attachment ----


@router.post("/{claim_id_or_number}/receipt", response_model=ExpenseClaimOut)
async def upload_receipt(claim_id_or_number: str, file: UploadFile, principal: CurrentPrincipal):
    """Attach a PDF or image (JPEG, PNG, WebP) receipt to your pending claim. Replaces any existing receipt."""
    doc = await _own_pending(claim_id_or_number, principal)
    limit = settings.receipt_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Receipt must be {settings.receipt_max_mb} MB or less")
    content_type = _sniff(data)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Receipt must be a PDF, JPEG, PNG or WebP file")

    filename = _safe_filename(file.filename)
    bucket = _receipts()
    file_id = await bucket.upload_from_stream(
        filename, data, metadata={"claim_id": doc["_id"], "content_type": content_type}
    )
    receipt = {"file_id": file_id, "filename": filename, "content_type": content_type, "size": len(data)}
    updated = await get_db().expense_claims.find_one_and_update(
        {"_id": doc["_id"]},
        {"$set": {"receipt": receipt, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if doc.get("receipt"):
        await _receipts().delete(doc["receipt"]["file_id"])
    return _out(updated)


@router.get("/{claim_id_or_number}/receipt")
async def download_receipt(claim_id_or_number: str, principal: CurrentPrincipal):
    doc = await _get(claim_id_or_number, principal)
    receipt = doc.get("receipt")
    if not receipt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No receipt attached")
    try:
        stream = await _receipts().open_download_stream(receipt["file_id"])
    except NoFile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt file is missing")

    async def chunks():
        while chunk := await stream.readchunk():
            yield chunk

    return StreamingResponse(
        chunks(),
        media_type=receipt["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{receipt["filename"]}"',
            "Content-Length": str(receipt["size"]),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---- Approval workflow ----

# Who acts at each stage, and the status their approval moves the claim to.
_APPROVAL_STAGES: dict[ExpenseStatus, tuple[Role, ExpenseStatus]] = {
    ExpenseStatus.PENDING: (Role.TECHNICAL_TEAM, ExpenseStatus.TECHNICAL_APPROVED),
    ExpenseStatus.TECHNICAL_APPROVED: (Role.OWNER, ExpenseStatus.OWNER_APPROVED),
}


async def _act(
    claim_id_or_number: str,
    principal: Principal,
    *,
    required_role: Role | None,
    from_status: ExpenseStatus | None = None,
    action: ClaimAction,
    new_status: ExpenseStatus | None,
    note: str | None = None,
    payment_reference: str | None = None,
) -> dict:
    claim = await get_db().expense_claims.find_one(
        _lookup(claim_id_or_number), {"claimant": 1, "status": 1, "history": 1}
    )
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense claim not found")
    current = ExpenseStatus(claim["status"])
    if from_status is not None and current != from_status:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Claim is {current}; it must be {from_status} to be {action}")
    stage_role = required_role or _APPROVAL_STAGES.get(current, (None,))[0]
    if stage_role is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Claim is {current} and can't be {action}")
    if new_status is None:  # approving: move to the next stage
        new_status = _APPROVAL_STAGES[current][1]
    if stage_role.value not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Claim is {current}: waiting for {stage_role.label}")
    if claim["claimant"]["user_id"] == principal.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't act on your own expense claim")
    if any(e["user_id"] == principal.user_id for e in claim.get("history", [])):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You've already acted on this claim at an earlier stage")

    now = utcnow()
    event = {
        "action": action.value,
        "user_id": principal.user_id,
        "by": principal.username,
        "role": stage_role.value,
        "at": now,
        "note": note,
        "payment_reference": payment_reference,
    }
    # Conditional on the status we checked, so two people acting at once can't both succeed.
    doc = await get_db().expense_claims.find_one_and_update(
        {"_id": claim["_id"], "status": current.value},
        {"$set": {"status": new_status.value, "updated_at": now}, "$push": {"history": event}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Claim was updated by someone else; reload and try again")
    return doc


@router.post("/{claim_id_or_number}/approve", response_model=ExpenseClaimOut)
async def approve_expense_claim(
    claim_id_or_number: str, principal: CurrentPrincipal, body: ReviewDecision | None = None
):
    """Technical team approves a pending claim; the owner then gives final approval."""
    return _out(
        await _act(
            claim_id_or_number,
            principal,
            required_role=None,
            action=ClaimAction.APPROVED,
            new_status=None,
            note=body.note if body else None,
        )
    )


@router.post("/{claim_id_or_number}/reject", response_model=ExpenseClaimOut)
async def reject_expense_claim(claim_id_or_number: str, body: Rejection, principal: CurrentPrincipal):
    """Whoever is due to approve the claim (technical team, then owner) can reject it instead."""
    return _out(
        await _act(
            claim_id_or_number,
            principal,
            required_role=None,
            action=ClaimAction.REJECTED,
            new_status=ExpenseStatus.REJECTED,
            note=body.reason,
        )
    )


@router.post("/{claim_id_or_number}/reimburse", response_model=ExpenseClaimOut)
async def reimburse_expense_claim(
    claim_id_or_number: str, principal: CurrentPrincipal, body: Reimbursement | None = None
):
    """HR marks an owner-approved claim as reimbursed."""
    return _out(
        await _act(
            claim_id_or_number,
            principal,
            required_role=Role.HR_TEAM,
            from_status=ExpenseStatus.OWNER_APPROVED,
            action=ClaimAction.REIMBURSED,
            new_status=ExpenseStatus.REIMBURSED,
            note=body.note if body else None,
            payment_reference=body.payment_reference if body else None,
        )
    )
