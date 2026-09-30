from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr


def utcnow() -> datetime:
    return datetime.now(UTC)


class Timestamps(BaseModel):
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LabeledEnum(StrEnum):
    """String enum whose members are declared as (value, display label)."""

    label: str

    def __new__(cls, value: str, label: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


def _lower(v: object) -> object:
    return v.lower() if isinstance(v, str) else v


Username = Annotated[str, BeforeValidator(_lower), Field(min_length=3, max_length=50, pattern=r"^[a-z0-9._-]+$")]
Password = Annotated[SecretStr, Field(min_length=8, max_length=128)]
