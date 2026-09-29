import secrets
import string
from datetime import timedelta

import jwt
from pwdlib import PasswordHash

from app.config import settings
from app.models.common import utcnow

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _hasher.verify(password, hashed)


# Used to spend the same time on unknown usernames as on wrong passwords.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def generate_temporary_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def create_access_token(user_id: str) -> tuple[str, int]:
    """Return (token, lifetime in seconds)."""
    now = utcnow()
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "iat": int(now.timestamp()), "exp": now + lifetime}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError if the token is invalid or expired."""
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "iat", "exp"]}
    )
