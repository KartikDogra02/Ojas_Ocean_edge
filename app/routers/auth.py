from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import AuthenticatedPrincipal
from app.db import get_db
from app.models import PasswordChange, Token
from app.models.common import utcnow
from app.security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """Log in with username (or email) and password. Send the token as `Authorization: Bearer <token>`."""
    login_id = form.username.strip().lower()
    field = "email" if "@" in login_id else "username"
    user = await get_db().users.find_one(
        {field: login_id}, {"hashed_password": 1, "is_active": 1, "must_change_password": 1}
    )
    if user is None:
        verify_password(form.password, DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    if not verify_password(form.password, user["hashed_password"]) or not user.get("is_active", False):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    token, expires_in = create_access_token(str(user["_id"]))
    return Token(
        access_token=token, expires_in=expires_in, must_change_password=user.get("must_change_password", False)
    )


@router.post("/change-password", response_model=Token)
async def change_password(body: PasswordChange, principal: AuthenticatedPrincipal):
    """Change your own password. Works with a temporary password; returns a fresh token."""
    db = get_db()
    user = await db.users.find_one({"_id": principal.user_id}, {"hashed_password": 1})
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
    token, expires_in = create_access_token(str(principal.user_id))
    return Token(access_token=token, expires_in=expires_in, must_change_password=False)
