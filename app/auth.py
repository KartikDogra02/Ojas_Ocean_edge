from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.db import get_db
from app.models.role import Role
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: ObjectId
    username: str
    roles: frozenset[str]  # role codes, including custom roles
    must_change_password: bool
    token_id: str
    token_expires_at: datetime

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN.value in self.roles


def _unauthorized(detail: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


async def get_authenticated_principal(token: Annotated[str | None, Depends(oauth2_scheme)]) -> Principal:
    """Any logged-in user, including one who still has to change a temporary password."""
    if not token:
        raise _unauthorized("Not authenticated")
    try:
        claims = decode_access_token(token)
        user_id = ObjectId(claims["sub"])
    except (jwt.InvalidTokenError, InvalidId):
        raise _unauthorized()

    user = await get_db().users.find_one(
        {"_id": user_id},
        {
            "username": 1,
            "roles": 1,
            "is_active": 1,
            "must_change_password": 1,
            "password_changed_at": 1,
        },
    )
    if user is None or not user.get("is_active", False):
        raise _unauthorized()
    # Tokens issued before the last password change are no longer valid.
    changed_at = user.get("password_changed_at")
    if changed_at is not None and claims["iat"] < changed_at.timestamp():
        raise _unauthorized()
    if await get_db().revoked_tokens.count_documents({"_id": claims["jti"]}, limit=1):
        raise _unauthorized()

    return Principal(
        user_id=user["_id"],
        username=user["username"],
        roles=frozenset(user.get("roles", [])),
        must_change_password=user.get("must_change_password", True),
        token_id=claims["jti"],
        token_expires_at=datetime.fromtimestamp(claims["exp"], UTC),
    )


AuthenticatedPrincipal = Annotated[Principal, Depends(get_authenticated_principal)]


async def get_principal(principal: AuthenticatedPrincipal) -> Principal:
    """A logged-in user who is allowed to use the API (no pending password change)."""
    if principal.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password change required")
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_roles(*allowed: Role):
    """Dependency that allows the request only if the caller has at least one of `allowed` roles."""
    codes = {r.value for r in allowed}

    async def checker(principal: CurrentPrincipal) -> Principal:
        if not principal.roles.intersection(codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return principal

    return checker
