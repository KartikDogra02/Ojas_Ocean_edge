from gridfs import AsyncGridFSBucket

from app import db
from app.migrate_files import migrate
from app.storage import FileNotFound, get_storage
from tests.helpers import PDF


async def test_gridfs_round_trip():
    storage = get_storage()
    await storage.put("tests/a.pdf", PDF, "application/pdf")
    assert await storage.exists("tests/a.pdf")
    assert await storage.get("tests/a.pdf") == PDF
    await storage.delete("tests/a.pdf")
    assert not await storage.exists("tests/a.pdf")


async def test_missing_file_raises():
    try:
        await get_storage().get("tests/nope")
    except FileNotFound:
        return
    raise AssertionError("expected FileNotFound")


async def test_migrates_legacy_receipt(client, engineer):
    claim = (await client.post("/expense-claims", headers=engineer.headers, json={"category": "other", "amount": 5, "description": "x"})).json()
    database = db.get_db()
    file_id = await AsyncGridFSBucket(database, bucket_name="receipts").upload_from_stream("old.pdf", PDF)
    await database.expense_claims.update_one(
        {"claim_number": claim["claim_number"]},
        {"$set": {"receipt": {"file_id": file_id, "filename": "old.pdf", "content_type": "application/pdf", "size": len(PDF)}}},
    )
    before = await client.get(f"/expense-claims/{claim['id']}/receipt", headers=engineer.headers)
    assert before.status_code == 404  # not migrated yet

    report = await migrate(dry_run=False, delete_source=True)
    assert report.copied == 1 and not report.problems
    after = await client.get(f"/expense-claims/{claim['id']}/receipt", headers=engineer.headers)
    assert after.content == PDF
    assert await database["receipts.files"].count_documents({}) == 0
    assert (await migrate(dry_run=False, delete_source=False)).copied == 0
