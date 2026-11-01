from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.audit import record
from app.auth import AuthenticatedPrincipal
from app.config import settings
from app.db import get_db
from app.models.auth import PasswordChange, Token
from app.models.common import utcnow
from app.routers.common import require_found
from app.security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _attempts_key(login_id: str, request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{login_id}|{ip}"


async def _check_not_locked(key: str) -> None:
    record = await get_db().login_attempts.find_one({"_id": key})
    if record and record["count"] >= settings.login_max_attempts:
        retry_after = int((record["expire_at"] - utcnow()).total_seconds())
        if retry_after > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many failed login attempts; try again later",
                headers={"Retry-After": str(retry_after)},
            )


async def _record_failure(key: str) -> None:
    # Each failure restarts the lockout window; MongoDB deletes the record once it expires.
    expire_at = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
    await get_db().login_attempts.update_one(
        {"_id": key}, {"$inc": {"count": 1}, "$set": {"expire_at": expire_at}}, upsert=True
    )


@router.post("/login", response_model=Token)
async def login(request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """Log in with username (or email) and password. Send the token as `Authorization: Bearer <token>`.

    After LOGIN_MAX_ATTEMPTS failures for the same username from the same address, further attempts get
    429 with a Retry-After header until LOGIN_LOCKOUT_MINUTES have passed since the last failure.
    """
    login_id = form.username.strip().lower()
    key = _attempts_key(login_id, request)
    await _check_not_locked(key)
    field = "email" if "@" in login_id else "username"
    user = await get_db().users.find_one(
        {field: login_id}, {"hashed_password": 1, "is_active": 1, "must_change_password": 1}
    )
    if user is None:
        verify_password(form.password, DUMMY_HASH)
    if user is None or not verify_password(form.password, user["hashed_password"]) or not user.get("is_active"):
        await _record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    await get_db().login_attempts.delete_one({"_id": key})
    token, expires_in = create_access_token(str(user["_id"]))
    return Token(access_token=token, expires_in=expires_in, must_change_password=user.get("must_change_password", True))


@router.post("/change-password", response_model=Token)
async def change_password(body: PasswordChange, principal: AuthenticatedPrincipal):
    """Change your own password. Works with a temporary password; returns a fresh token."""
    db = get_db()
    user = require_found(await db.users.find_one({"_id": principal.user_id}, {"hashed_password": 1}), "User not found")
    if not verify_password(body.current_password.get_secret_value(), user["hashed_password"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    new_password = body.new_password.get_secret_value()
    if new_password == body.current_password.get_secret_value():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must differ from the current one")

    now = utcnow()
    await db.users.update_one(
        {"_id": principal.user_id},
        {
            "$set": {
                "hashed_password": hash_password(new_password),
                "must_change_password": False,
                "password_changed_at": now,
                "updated_at": now,
            }
        },
    )
    await record(principal, "change_password", "user", principal.user_id, principal.username)
    token, expires_in = create_access_token(str(principal.user_id))
    return Token(access_token=token, expires_in=expires_in, must_change_password=False)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: AuthenticatedPrincipal):
    """Log out: the token used for this request stops working immediately."""
    await get_db().revoked_tokens.update_one(
        {"_id": principal.token_id},
        {"$setOnInsert": {"user_id": principal.user_id, "expires_at": principal.token_expires_at}},
        upsert=True,
    )
