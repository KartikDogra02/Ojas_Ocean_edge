import logging

from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.db import get_db
from app.models.role import Role
from app.models.service_engineer import ServiceEngineerProfile
from app.models.user import UserCreate
from app.models.common import utcnow
from app.security import hash_password

logger = logging.getLogger(__name__)


def role_values(roles: list[Role]) -> list[str]:
    return sorted({r.value for r in roles})


async def next_engineer_id() -> str:
    """Allocate the next sequential engineer ID, e.g. ENG-2026-106. Numbering restarts each year."""
    year = utcnow().year
    counter = await get_db().counters.find_one_and_update(
        {"_id": f"engineer_id:{year}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"ENG-{year}-{counter['seq']:03d}"


def duplicate_key_error(exc: DuplicateKeyError) -> HTTPException:
    field = next(iter((exc.details or {}).get("keyPattern", {})), "value")
    labels = {"email": "Email", "username": "Username"}
    return HTTPException(status.HTTP_409_CONFLICT, f"{labels.get(field, field)} already in use")


async def ensure_unique(**fields: str) -> None:
    for field, value in fields.items():
        if await get_db().users.count_documents({field: value}, limit=1):
            raise duplicate_key_error(DuplicateKeyError("", details={"keyPattern": {field: 1}}))


async def insert_user(
    user: UserCreate, *, service_engineer: ServiceEngineerProfile | None = None, temporary_password: bool = True
) -> dict:
    """Insert a user and return the stored document without the password hash.

    Passing a service_engineer profile allocates an engineer ID. Passwords are temporary by default:
    they must be changed at first login before the API can be used.

    Raises HTTPException(409) if the email or username is taken.
    """
    now = utcnow()
    doc = user.model_dump(exclude={"password"}) | {
        "roles": role_values(user.roles),
        "hashed_password": hash_password(user.password.get_secret_value()),
        "must_change_password": temporary_password,
        "created_at": now,
        "updated_at": now,
    }
    if service_engineer is not None:
        # Check for duplicates first so failed inserts don't burn sequential engineer IDs.
        await ensure_unique(email=user.email, username=user.username)
        doc["service_engineer"] = {"engineer_id": await next_engineer_id()} | service_engineer.model_dump()
    try:
        await get_db().users.insert_one(doc)
    except DuplicateKeyError as exc:
        raise duplicate_key_error(exc)
    doc.pop("hashed_password")
    return doc


async def seed_initial_admin() -> None:
    """Create the first admin from INITIAL_ADMIN_* settings if no admin user exists."""
    if await get_db().users.count_documents({"roles": Role.ADMIN.value}, limit=1):
        return
    email, username, password = (
        settings.initial_admin_email,
        settings.initial_admin_username,
        settings.initial_admin_password,
    )
    if not (email and username and password):
        logger.warning("No admin user exists and INITIAL_ADMIN_* is not set; set them and restart, or use `python -m app.cli`.")
        return
    user = UserCreate(email=email, username=username, password=password, roles=[Role.ADMIN])
    try:
        await insert_user(user)
    except HTTPException:
        # Another worker seeded it first, or the email/username is taken by a non-admin.
        logger.warning("Could not seed initial admin %r: email or username already in use.", username)
        return
    logger.warning("Seeded initial admin user %r (must change password on first login).", username)
