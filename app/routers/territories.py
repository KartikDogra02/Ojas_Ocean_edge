from fastapi import APIRouter

from app.models import Territory

router = APIRouter(prefix="/territories", tags=["territories"])


@router.get("")
async def list_territories() -> list[dict[str, str]]:
    return [{"value": t.value, "label": t.label} for t in Territory]
