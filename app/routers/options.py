from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.db import get_db
from app.models.certificate import InstrumentType
from app.models.check_in import PlaceType
from app.models.expense_claim import ExpenseCategory
from app.models.planner import DAY_STATUS_STYLE, DayStatus, MonthStatus
from app.models.territory import Territory
from app.models.work_order import ServiceType
from app.models.work_plan import Priority

router = APIRouter(prefix="/options", tags=["options"])


@router.get("")
async def get_options() -> dict[str, Any]:
    """Values and labels for frontend dropdowns. Roles are the currently active ones."""
    roles = get_db().roles.find({"is_active": True}, {"code": 1, "name": 1}).sort("name", 1)
    return {
        "roles": [{"value": r["code"], "label": r["name"]} async for r in roles],
        "territories": [{"value": t.value, "label": t.label} for t in Territory],
        "instrument_types": [{"value": t.value, "label": t.label} for t in InstrumentType],
        "priorities": [{"value": p.value, "label": p.label} for p in Priority],
        "service_types": [{"value": t.value, "label": t.label} for t in ServiceType],
        "check_in_place_types": [{"value": t.value, "label": t.label} for t in PlaceType],
        "planner_day_statuses": [
            {"value": s.value, "label": s.label, "code": DAY_STATUS_STYLE[s][0], "color": DAY_STATUS_STYLE[s][1]}
            for s in DayStatus
        ],
        "planner_month_statuses": [{"value": s.value, "label": s.label} for s in MonthStatus],
        "expense_categories": [{"value": c.value, "label": c.label} for c in ExpenseCategory],
        "mileage_rate_per_km": settings.mileage_rate_per_km,
    }
