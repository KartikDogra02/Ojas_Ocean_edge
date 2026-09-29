from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, status

from app.db import get_db
from app.models import ItemIn, ItemOut

router = APIRouter(prefix="/items", tags=["items"])


def _oid(item_id: str) -> ObjectId:
    try:
        return ObjectId(item_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id")


def _out(doc: dict) -> ItemOut:
    return ItemOut(id=str(doc.pop("_id")), **doc)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemIn):
    doc = item.model_dump()
    result = await get_db().items.insert_one(doc)
    return ItemOut(id=str(result.inserted_id), **item.model_dump())


@router.get("", response_model=list[ItemOut])
async def list_items(limit: int = 100):
    return [_out(d) async for d in get_db().items.find().limit(limit)]


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(item_id: str):
    doc = await get_db().items.find_one({"_id": _oid(item_id)})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return _out(doc)


@router.put("/{item_id}", response_model=ItemOut)
async def update_item(item_id: str, item: ItemIn):
    result = await get_db().items.update_one({"_id": _oid(item_id)}, {"$set": item.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return ItemOut(id=item_id, **item.model_dump())


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: str):
    result = await get_db().items.delete_one({"_id": _oid(item_id)})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
