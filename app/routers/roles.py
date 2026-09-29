from fastapi import APIRouter

from app.models import Role

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("")
async def list_roles() -> list[dict[str, str]]:
    return [{"value": r.value, "label": r.label} for r in Role]
