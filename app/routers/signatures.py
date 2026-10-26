import struct
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.auth import CurrentPrincipal, Principal
from app.config import settings
from app.db import get_db
from app.models.common import utcnow
from app.models.role import Role
from app.models.service_engineer import SignatureInfo
from app.routers.common import FileLink, file_link
from app.storage import FileNotFound, get_storage

router = APIRouter(tags=["signatures"])

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ENGINEER = {"roles": Role.SERVICE_ENGINEER.value}


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG's header, or None if the bytes aren't a PNG."""
    if len(data) < 24 or not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height) if width and height else None


async def _engineer(engineer_id: str) -> dict:
    user = await get_db().users.find_one(
        {"service_engineer.engineer_id": engineer_id.upper()} | _ENGINEER, {"service_engineer": 1}
    )
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service engineer not found")
    return user


async def _self(principal: Principal) -> dict:
    user = await get_db().users.find_one({"_id": principal.user_id} | _ENGINEER, {"service_engineer": 1})
    if user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only service engineers have a signature")
    return user


def _require(principal: Principal, *roles: Role) -> None:
    if not principal.roles & {r.value for r in roles}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")


async def _save(user: dict, file: UploadFile) -> SignatureInfo:
    limit = settings.signature_max_kb * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"Signature must be {settings.signature_max_kb} KB or less"
        )
    dimensions = png_dimensions(data)
    if dimensions is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Signature must be a PNG image (JPG isn't accepted)"
        )

    engineer_id = user["service_engineer"]["engineer_id"]
    key = f"signatures/{engineer_id}/{uuid4().hex}.png"
    await get_storage().put(key, data, "image/png")
    info = SignatureInfo(size=len(data), width=dimensions[0], height=dimensions[1], uploaded_at=utcnow())
    await get_db().users.update_one(
        {"_id": user["_id"]},
        {"$set": {"service_engineer.signature": info.model_dump() | {"key": key}, "updated_at": utcnow()}},
    )
    old = user["service_engineer"].get("signature")
    if old and old.get("key"):
        await get_storage().delete(old["key"])
    return info


async def _delete(user: dict) -> None:
    old = user["service_engineer"].get("signature")
    if not old:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No signature uploaded")
    await get_db().users.update_one(
        {"_id": user["_id"]}, {"$unset": {"service_engineer.signature": ""}, "$set": {"updated_at": utcnow()}}
    )
    if old.get("key"):
        await get_storage().delete(old["key"])


def _signature_of(user: dict) -> dict:
    signature = user["service_engineer"].get("signature")
    if not signature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No signature uploaded")
    if "key" not in signature:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Signature file hasn't been migrated (run python -m app.migrate_files)"
        )
    return signature


def _link(user: dict) -> FileLink:
    filename = f"{user['service_engineer']['engineer_id']}-signature.png"
    return file_link(_signature_of(user)["key"], filename, "image/png")


async def _image(user: dict) -> Response:
    try:
        data = await get_storage().get(_signature_of(user)["key"])
    except FileNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Signature file is missing")
    return Response(
        data,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


# ---- Admin / HR, by engineer ID ----


@router.put("/service-engineers/{engineer_id}/signature", response_model=SignatureInfo)
async def upload_engineer_signature(engineer_id: str, file: UploadFile, principal: CurrentPrincipal):
    """Admin: upload or replace an engineer's signature (PNG only)."""
    _require(principal, Role.ADMIN)
    return await _save(await _engineer(engineer_id), file)


@router.get("/service-engineers/{engineer_id}/signature", response_class=Response)
async def get_engineer_signature(engineer_id: str, principal: CurrentPrincipal):
    """Admin and HR: the engineer's signature image."""
    _require(principal, Role.ADMIN, Role.HR_TEAM)
    return await _image(await _engineer(engineer_id))


@router.get("/service-engineers/{engineer_id}/signature/link", response_model=FileLink)
async def engineer_signature_link(engineer_id: str, principal: CurrentPrincipal):
    """Admin and HR: a short-lived direct URL to the signature (R2 only), e.g. for an <img> tag."""
    _require(principal, Role.ADMIN, Role.HR_TEAM)
    return _link(await _engineer(engineer_id))


@router.delete("/service-engineers/{engineer_id}/signature", status_code=status.HTTP_204_NO_CONTENT)
async def delete_engineer_signature(engineer_id: str, principal: CurrentPrincipal):
    _require(principal, Role.ADMIN)
    await _delete(await _engineer(engineer_id))


# ---- The engineer's own signature ----


@router.put("/users/me/signature", response_model=SignatureInfo)
async def upload_my_signature(file: UploadFile, principal: CurrentPrincipal):
    """Service engineers: upload or replace your own signature (PNG only)."""
    return await _save(await _self(principal), file)


@router.get("/users/me/signature", response_class=Response)
async def get_my_signature(principal: CurrentPrincipal):
    return await _image(await _self(principal))


@router.get("/users/me/signature/link", response_model=FileLink)
async def my_signature_link(principal: CurrentPrincipal):
    return _link(await _self(principal))


@router.delete("/users/me/signature", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_signature(principal: CurrentPrincipal):
    await _delete(await _self(principal))
