from fastapi import APIRouter

from app.models.common import LabeledEnum
from app.models.role import Role
from app.models.territory import Territory

router = APIRouter(prefix="/options", tags=["options"])


def _choices(enum: type[LabeledEnum]) -> list[dict[str, str]]:
    return [{"value": m.value, "label": m.label} for m in enum]


@router.get("")
async def get_options() -> dict[str, list[dict[str, str]]]:
    """Values and labels for frontend dropdowns."""
    return {"roles": _choices(Role), "territories": _choices(Territory)}
