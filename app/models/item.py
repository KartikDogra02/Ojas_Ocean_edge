from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    name: str
    description: str | None = None
    price: float = Field(ge=0)


class ItemOut(ItemIn):
    id: str
