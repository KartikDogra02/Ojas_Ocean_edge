from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import SecretStr

from app.audit import record
from app.auth import CurrentPrincipal, require_roles
from app.db import get_db
from app.models.role import Role
from app.models.service_engineer import ServiceEngineerCreate, ServiceEngineerProfile
from app.models.territory import Territory
from app.models.user import ServiceEngineerCreated, UserCreate, UserOut
from app.routers.common import ENGINEER_FILTER, USER_PROJECTION, Limit, Skip, from_doc, set_total, to_oid
from app.security import generate_temporary_password
from app.services import insert_user

router = APIRouter(
    prefix="/service-engineers",
    tags=["service-engineers"],
    dependencies=[Depends(require_roles(Role.ADMIN, Role.HR_TEAM))],
)


@router.post(
    "",
    response_model=ServiceEngineerCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.ADMIN))],  # only admins may create users
)
async def provision_service_engineer(body: ServiceEngineerCreate, actor: CurrentPrincipal):
    # Without a password from the form, generate a temporary one and return it once.
    generated = None if body.password else generate_temporary_password()
    password = body.password or SecretStr(generated or "")
    user = UserCreate(
        email=body.email,
        username=body.username,
        full_name=body.full_name,
        password=password,
        roles=[Role.SERVICE_ENGINEER],
    )
    profile = ServiceEngineerProfile(**body.model_dump(include=set(ServiceEngineerProfile.model_fields)))
    doc = from_doc(await insert_user(user, service_engineer=profile))
    engineer_id = doc["service_engineer"]["engineer_id"]
    await record(actor, "create", "service_engineer", doc["id"], engineer_id, details={"username": doc["username"]})
    return ServiceEngineerCreated(**doc, temporary_password=generated)


@router.get("", response_model=list[UserOut])
async def list_service_engineers(
    response: Response,
    territory: Territory | None = None,
    skill: str | None = None,
    active: bool | None = None,
    skip: Skip = 0,
    limit: Limit = 100,
):
    query: dict = dict(ENGINEER_FILTER)
    if territory is not None:
        query["service_engineer.territory"] = territory.value
    if skill is not None:
        query["service_engineer.skills"] = skill
    if active is not None:
        query["is_active"] = active
    await set_total(response, get_db().users, query)
    cursor = get_db().users.find(query, USER_PROJECTION).sort("service_engineer.engineer_id", 1).skip(skip).limit(limit)
    return [from_doc(d) async for d in cursor]


@router.get("/{engineer_id}", response_model=UserOut)
async def get_service_engineer(engineer_id: str):
    """Look up by engineer ID (e.g. ENG-2026-106) or by user id."""
    query = {"service_engineer.engineer_id": engineer_id.upper()}
    if not engineer_id.upper().startswith("ENG-"):
        query = {"_id": to_oid(engineer_id)}
    doc = await get_db().users.find_one(query | ENGINEER_FILTER, USER_PROJECTION)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service engineer not found")
    return from_doc(doc)
