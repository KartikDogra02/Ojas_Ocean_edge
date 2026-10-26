from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import DeleteOne, UpdateOne

from app.auth import CurrentPrincipal, Principal, require_roles
from app.config import settings
from app.db import get_db
from app.models.common import utcnow
from app.models.planner import (
    AVAILABLE_DAY_STATUSES,
    DayCell,
    DayEntriesUpdate,
    DayPlanner,
    DayStatus,
    EngineerAvailability,
    EngineerPlannerUpdate,
    EntriesSaved,
    MonthCell,
    MonthEntriesUpdate,
    MonthlyEngineer,
    MonthlyPlanner,
    MonthStatus,
    PlannerEngineer,
    PlannerWorkOrder,
)
from app.models.role import Role

router = APIRouter(prefix="/planner", tags=["planner"])
Editor = Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.HR_TEAM, Role.TECHNICAL_TEAM))]

# Everyone else (service engineers) only sees their own row.
_VIEW_ALL = {Role.ADMIN.value, Role.HR_TEAM.value, Role.TECHNICAL_TEAM.value, Role.OWNER.value}
_ENGINEER = {"roles": Role.SERVICE_ENGINEER.value, "is_active": True}


def _today() -> date:
    return datetime.now(ZoneInfo(settings.planner_timezone)).date()


def _window() -> tuple[date, date]:
    """The editable range: today plus the next PLANNER_DAYS - 1 days. Earlier days aren't kept."""
    today = _today()
    return today, today + timedelta(days=settings.planner_days - 1)


def _dt(day: date) -> datetime:
    # BSON has no date-only type; store calendar days as midnight UTC.
    return datetime.combine(day, time(), UTC)


async def _engineers(principal: Principal, engineer_id: str | None = None) -> list[dict]:
    query = dict(_ENGINEER)
    if not principal.roles & _VIEW_ALL:
        if Role.SERVICE_ENGINEER.value not in principal.roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        query["_id"] = principal.user_id
    if engineer_id is not None:
        query["service_engineer.engineer_id"] = engineer_id.upper()
    projection = {"full_name": 1, "service_engineer": 1}
    return [u async for u in get_db().users.find(query, projection).sort("service_engineer.engineer_id", 1)]


async def _missing_engineers(engineer_ids: set[str]) -> list[str]:
    found = await get_db().users.distinct(
        "service_engineer.engineer_id", {"service_engineer.engineer_id": {"$in": list(engineer_ids)}} | _ENGINEER
    )
    return sorted(engineer_ids - set(found))


async def _work_orders(ids: set[ObjectId]) -> dict[ObjectId, PlannerWorkOrder]:
    cursor = get_db().work_orders.find(
        {"_id": {"$in": list(ids)}}, {"work_order_number": 1, "title": 1, "customer.company": 1}
    )
    return {
        w["_id"]: PlannerWorkOrder(
            id=str(w["_id"]),
            work_order_number=w["work_order_number"],
            title=w["title"],
            customer=w.get("customer", {}).get("company"),
        )
        async for w in cursor
    }


async def _day_planner(principal: Principal, start: date, days: int, engineer_id: str | None = None) -> DayPlanner:
    db = get_db()
    engineers = await _engineers(principal, engineer_id)
    ids = [u["service_engineer"]["engineer_id"] for u in engineers]
    dates = [start + timedelta(days=i) for i in range(days)]

    entries = {
        (e["engineer_id"], e["date"].date()): e
        async for e in db.planner_days.find(
            {"engineer_id": {"$in": ids}, "date": {"$gte": _dt(dates[0]), "$lte": _dt(dates[-1])}}
        )
    }
    months_off = {
        (m["engineer_id"], m["year"], m["month"])
        async for m in db.planner_months.find(
            {
                "engineer_id": {"$in": ids},
                "year": {"$in": list({d.year for d in dates})},
                "status": MonthStatus.OFF.value,
            }
        )
    }
    work_orders = await _work_orders({e["work_order"]["id"] for e in entries.values() if e.get("work_order")})

    totals = {d: {s: 0 for s in DayStatus} for d in dates}
    rows = []
    for user in engineers:
        profile = user["service_engineer"]
        eid = profile["engineer_id"]
        cells: dict[date, DayCell] = {}
        on_orders: dict[str, PlannerWorkOrder] = {}
        for d in dates:
            entry = entries.get((eid, d))
            day_status = DayStatus(entry["status"]) if entry else None
            work_order = work_orders.get(entry["work_order"]["id"]) if entry and entry.get("work_order") else None
            if day_status:
                totals[d][day_status] += 1
            if work_order:
                on_orders.setdefault(work_order.id, work_order)
            cells[d] = DayCell(
                status=day_status,
                note=entry.get("note") if entry else None,
                work_order=work_order,
                available=(day_status is None or day_status in AVAILABLE_DAY_STATUSES)
                and (eid, d.year, d.month) not in months_off,
            )
        rows.append(
            PlannerEngineer(
                engineer_id=eid,
                user_id=str(user["_id"]),
                full_name=user.get("full_name"),
                skills=profile.get("skills", []),
                territory=profile.get("territory"),
                current_country=profile.get("current_country"),
                planner_comment=profile.get("planner_comment"),
                days=cells,
                work_orders=list(on_orders.values()),
            )
        )
    return DayPlanner(today=_today(), start=dates[0], end=dates[-1], dates=dates, engineers=rows, totals=totals)


# ---- Daily planner (14 days) ----


@router.get("/daily", response_model=DayPlanner)
async def daily_planner(principal: CurrentPrincipal, engineer_id: str | None = None):
    """Today and the next 13 days: each engineer's status, note and work order per day, plus daily totals."""
    start, _ = _window()
    return await _day_planner(principal, start, settings.planner_days, engineer_id)


@router.put("/daily", response_model=EntriesSaved)
async def save_daily_entries(body: DayEntriesUpdate, editor: Editor):
    """Set or clear planner days in bulk. All entries are checked before any are saved."""
    db = get_db()
    start, end = _window()
    errors: list[str] = []

    outside = sorted({e.date.isoformat() for e in body.entries if not start <= e.date <= end})
    if outside:
        errors.append(f"Dates must be between {start} and {end}: {', '.join(outside)}")
    if missing := await _missing_engineers({e.engineer_id for e in body.entries}):
        errors.append(f"Unknown or inactive service engineer(s): {', '.join(missing)}")

    orders: dict[str, dict] = {}
    for ref in {e.work_order for e in body.entries if e.work_order}:
        query = {"_id": ObjectId(ref)} if ObjectId.is_valid(ref) else {"work_order_number": ref.upper()}
        order = await db.work_orders.find_one(query, {"work_order_number": 1, "assigned_engineer_ids": 1})
        if order is None:
            errors.append(f"Work order not found: {ref}")
        else:
            orders[ref] = order
    for e in body.entries:
        if e.status is None and (e.note or e.work_order):
            errors.append(f"{e.engineer_id} {e.date}: a note or work order needs a status")
        order = orders.get(e.work_order) if e.work_order else None
        if order and e.engineer_id not in order["assigned_engineer_ids"]:
            errors.append(f"{e.engineer_id} isn't on the crew of {order['work_order_number']}")
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, errors)

    now = utcnow()
    ops = []
    for e in body.entries:
        key = {"engineer_id": e.engineer_id, "date": _dt(e.date)}
        if e.status is None:
            ops.append(DeleteOne(key))
            continue
        order = orders.get(e.work_order) if e.work_order else None
        fields = {
            "status": e.status.value,
            "note": e.note,
            "work_order": {"id": order["_id"], "work_order_number": order["work_order_number"]} if order else None,
            # Past days aren't needed: MongoDB deletes each entry the day after its date.
            "expire_at": _dt(e.date + timedelta(days=1)),
            "updated_by": editor.username,
            "updated_at": now,
        }
        ops.append(UpdateOne(key, {"$set": fields}, upsert=True))
    await db.planner_days.bulk_write(ops)
    cleared = sum(e.status is None for e in body.entries)
    return EntriesSaved(saved=len(body.entries) - cleared, cleared=cleared)


@router.get("/availability", response_model=list[EngineerAvailability])
async def availability(principal: CurrentPrincipal, engineer_id: str | None = None):
    """Which of the next 14 days each engineer is free for new work."""
    start, _ = _window()
    planner = await _day_planner(principal, start, settings.planner_days, engineer_id)
    return [
        EngineerAvailability(
            engineer_id=e.engineer_id,
            full_name=e.full_name,
            available_dates=[d for d, cell in e.days.items() if cell.available],
        )
        for e in planner.engineers
    ]


@router.patch("/engineers/{engineer_id}", response_model=PlannerEngineer)
async def update_engineer_planner_details(engineer_id: str, body: EngineerPlannerUpdate, editor: Editor):
    """The engineer's current country and planner comment (the left-hand column)."""
    changes = {f"service_engineer.{k}": v for k, v in body.model_dump(exclude_unset=True).items()}
    if changes:
        result = await get_db().users.update_one(
            {"service_engineer.engineer_id": engineer_id.upper()} | _ENGINEER,
            {"$set": changes | {"updated_at": utcnow()}},
        )
        if result.matched_count == 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Service engineer not found")
    start, _ = _window()
    planner = await _day_planner(editor, start, 1, engineer_id)
    if not planner.engineers:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service engineer not found")
    return planner.engineers[0]


# ---- Weekly planner ----


@router.get("/weekly", response_model=DayPlanner)
async def weekly_planner(
    principal: CurrentPrincipal,
    start: Annotated[date | None, Query(description="First day of the week; defaults to this week's Monday")] = None,
    engineer_id: str | None = None,
):
    """Seven days per engineer, with the work order they're on each day and the week's work orders.

    Days before today are empty because past planner days aren't kept.
    """
    if start is None:
        today = _today()
        start = today - timedelta(days=today.weekday())
    return await _day_planner(principal, start, 7, engineer_id)


# ---- Monthly planner (whole year) ----


@router.get("/monthly", response_model=MonthlyPlanner)
async def monthly_planner(principal: CurrentPrincipal, year: int | None = None, engineer_id: str | None = None):
    """Each engineer's twelve months for a year: month off, on call, or nothing set."""
    year = year or _today().year
    engineers = await _engineers(principal, engineer_id)
    ids = [u["service_engineer"]["engineer_id"] for u in engineers]
    entries = {
        (m["engineer_id"], m["month"]): m
        async for m in get_db().planner_months.find({"engineer_id": {"$in": ids}, "year": year})
    }
    totals = {month: {s: 0 for s in MonthStatus} for month in range(1, 13)}
    rows = []
    for user in engineers:
        eid = user["service_engineer"]["engineer_id"]
        months = {}
        for month in range(1, 13):
            entry = entries.get((eid, month))
            month_status = MonthStatus(entry["status"]) if entry else None
            if month_status:
                totals[month][month_status] += 1
            months[month] = MonthCell(status=month_status, note=entry.get("note") if entry else None)
        rows.append(
            MonthlyEngineer(engineer_id=eid, user_id=str(user["_id"]), full_name=user.get("full_name"), months=months)
        )
    return MonthlyPlanner(year=year, engineers=rows, totals=totals)


@router.put("/monthly", response_model=EntriesSaved)
async def save_monthly_entries(body: MonthEntriesUpdate, editor: Editor):
    """Set or clear months in bulk (current year onwards). All entries are checked before any are saved."""
    db = get_db()
    this_year = _today().year
    errors: list[str] = []
    past = sorted({e.year for e in body.entries if e.year < this_year})
    if past:
        errors.append(f"Past years can't be changed: {', '.join(map(str, past))}")
    if missing := await _missing_engineers({e.engineer_id for e in body.entries}):
        errors.append(f"Unknown or inactive service engineer(s): {', '.join(missing)}")
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, errors)

    now = utcnow()
    ops = []
    for e in body.entries:
        key = {"engineer_id": e.engineer_id, "year": e.year, "month": e.month}
        if e.status is None:
            ops.append(DeleteOne(key))
        else:
            fields = {"status": e.status.value, "note": e.note, "updated_by": editor.username, "updated_at": now}
            ops.append(UpdateOne(key, {"$set": fields}, upsert=True))
    await db.planner_months.bulk_write(ops)
    cleared = sum(e.status is None for e in body.entries)
    return EntriesSaved(saved=len(body.entries) - cleared, cleared=cleared)
