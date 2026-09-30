from fastapi import APIRouter

from app.db import get_db
from app.models.certificate import InstrumentType
from app.models.territory import Territory

router = APIRouter(prefix="/options", tags=["options"])


@router.get("")
async def get_options() -> dict[str, list[dict[str, str]]]:
    """Values and labels for frontend dropdowns. Roles are the currently active ones."""
    roles = get_db().roles.find({"is_active": True}, {"code": 1, "name": 1}).sort("name", 1)
    return {
        "roles": [{"value": r["code"], "label": r["name"]} async for r in roles],
        "territories": [{"value": t.value, "label": t.label} for t in Territory],
        "instrument_types": [{"value": t.value, "label": t.label} for t in InstrumentType],
    }
