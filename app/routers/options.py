from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.db import get_db
from app.models.certificate import InstrumentType
from app.models.expense_claim import ExpenseCategory
from app.models.territory import Territory
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
        "expense_categories": [{"value": c.value, "label": c.label} for c in ExpenseCategory],
        "mileage_rate_per_km": settings.mileage_rate_per_km,
    }
