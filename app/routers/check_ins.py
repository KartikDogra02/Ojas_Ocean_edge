from fastapi import APIRouter, HTTPException, status

from app.auth import CurrentPrincipal
from app.db import get_db
from app.models.check_in import CheckInCreate, CheckInOut, PlaceType
from app.models.common import utcnow
from app.models.role import Role
from app.routers.work_plans import own_engineer_id

router = APIRouter(prefix="/check-ins", tags=["check-ins"])

# Admin, HR, technical team and owner see everyone's check-ins; service engineers only their own.
_VIEW_ALL = {Role.ADMIN.value, Role.HR_TEAM.value, Role.TECHNICAL_TEAM.value, Role.OWNER.value}


def _out(doc: dict) -> CheckInOut:
    return CheckInOut(**doc | {"id": str(doc["_id"])})


async def _scope(principal: CurrentPrincipal, engineer_id: str | None) -> dict:
    if principal.roles & _VIEW_ALL:
        return {"engineer_id": engineer_id.upper()} if engineer_id else {}
    own = await own_engineer_id(principal)
    if own is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
    return {"engineer_id": own}


@router.post("", response_model=CheckInOut, status_code=status.HTTP_201_CREATED)
async def check_in(body: CheckInCreate, principal: CurrentPrincipal):
    """Service engineers record where they've just arrived: a workshop, hotel, vessel, airport…"""
    engineer_id = await own_engineer_id(principal)
    if engineer_id is None or Role.SERVICE_ENGINEER.value not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only service engineers check in")
    user = await get_db().users.find_one({"_id": principal.user_id}, {"full_name": 1})
    doc = body.model_dump(mode="json") | {
        "engineer_id": engineer_id,
        "full_name": user.get("full_name"),
        "checked_in_at": utcnow(),
    }
    await get_db().check_ins.insert_one(doc)
    return _out(doc)


@router.get("", response_model=list[CheckInOut])
async def list_check_ins(
    principal: CurrentPrincipal,
    engineer_id: str | None = None,
    place_type: PlaceType | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """Check-in history, newest first."""
    query = await _scope(principal, engineer_id)
    if place_type is not None:
        query["place_type"] = place_type.value
    cursor = get_db().check_ins.find(query).sort("checked_in_at", -1).skip(skip).limit(limit)
    return [_out(d) async for d in cursor]


@router.get("/latest", response_model=list[CheckInOut])
async def latest_check_ins(principal: CurrentPrincipal, engineer_id: str | None = None):
    """Each engineer's most recent check-in: where they are now."""
    pipeline = [
        {"$match": await _scope(principal, engineer_id)},
        {"$sort": {"checked_in_at": -1}},
        {"$group": {"_id": "$engineer_id", "latest": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$latest"}},
        {"$sort": {"engineer_id": 1}},
    ]
    return [_out(d) async for d in await get_db().check_ins.aggregate(pipeline)]
