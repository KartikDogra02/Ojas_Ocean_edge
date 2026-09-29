from pydantic import SecretStr

from app.models.common import StrictModel
from app.models.user import Password


class Token(StrictModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool


class PasswordChange(StrictModel):
    current_password: SecretStr
    new_password: Password
