from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_roles
from app.db import get_db
from app.models.role import Role
from app.models.service_engineer import ServiceEngineerCreate, ServiceEngineerProfile
from app.models.territory import Territory
from app.models.user import ServiceEngineerCreated, UserCreate, UserOut
from app.routers.common import USER_PROJECTION, from_doc, to_oid
from app.security import generate_temporary_password
from app.services import insert_user

router = APIRouter(
    prefix="/service-engineers",
    tags=["service-engineers"],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.HR_TEAM))],
)

_ENGINEER = {"roles": Role.SERVICE_ENGINEER.value}


@router.post(
    "",
    response_model=ServiceEngineerCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.ADMIN))],  # only admins may create users
)
async def provision_service_engineer(body: ServiceEngineerCreate):
    generated = generate_temporary_password() if body.password is None else None
    user = UserCreate(
        email=body.email,
        username=body.username,
        full_name=body.full_name,
        password=generated or body.password,
        roles=[Role.SERVICE_ENGINEER],
    )
    profile = ServiceEngineerProfile(**body.model_dump(include=set(ServiceEngineerProfile.model_fields)))
    doc = from_doc(await insert_user(user, service_engineer=profile))
    return ServiceEngineerCreated(**doc, temporary_password=generated)


@router.get("", response_model=list[UserOut])
async def list_service_engineers(
    territory: Territory | None = None,
    skill: str | None = None,
    active: bool | None = None,
    limit: int = 100,
):
    query: dict = dict(_ENGINEER)
    if territory is not None:
        query["service_engineer.territory"] = territory.value
    if skill is not None:
        query["service_engineer.skills"] = skill
    if active is not None:
        query["is_active"] = active
    cursor = get_db().users.find(query, USER_PROJECTION).sort("service_engineer.engineer_id", 1).limit(limit)
    return [from_doc(d) async for d in cursor]


@router.get("/{engineer_id}", response_model=UserOut)
async def get_service_engineer(engineer_id: str):
    """Look up by engineer ID (e.g. ENG-2026-106) or by user id."""
    query = {"service_engineer.engineer_id": engineer_id.upper()}
    if not engineer_id.upper().startswith("ENG-"):
        query = {"_id": to_oid(engineer_id)}
    doc = await get_db().users.find_one(query | _ENGINEER, USER_PROJECTION)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service engineer not found")
    return from_doc(doc)
