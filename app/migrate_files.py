"""Move receipt and signature files into the configured storage backend.

Handles two kinds of existing files:

- Legacy GridFS files from before the storage layer: receipts in the "receipts" bucket and signatures in the
  "signatures" bucket, referenced by `file_id`. They get a storage key and are copied to the current backend.
- Files already stored by key in GridFS (bucket "files"), when STORAGE_BACKEND is now "r2": copied to R2 under
  the same key.

Every copy is read back and compared before the database is updated, and the script can be re-run safely:
files already in place are skipped. GridFS copies are only deleted with --delete-source.

Run inside the API container, with STORAGE_BACKEND and the R2 settings as they will be in production:

    docker compose exec api python -m app.migrate_files --dry-run
    docker compose exec api python -m app.migrate_files
    docker compose exec api python -m app.migrate_files --delete-source   # once you've checked the result
"""

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass, field
from uuid import uuid4

from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from app import db
from app.config import settings
from app.storage import FileNotFound, GridFSStorage, get_storage

_EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@dataclass
class Report:
    copied: int = 0
    already_done: int = 0
    deleted_sources: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class FileRef:
    """One file referenced from a document, and how to update that document once the file has moved."""

    label: str  # for the report, e.g. "receipt EXP-2026-001"
    collection: str
    doc_id: object
    path: str  # the embedded document's path, e.g. "receipt" or "service_engineer.signature"
    content_type: str
    key: str  # target key (existing, or newly generated for legacy files)
    key_is_new: bool = False  # True for legacy files that haven't been given a key yet
    # The legacy GridFS original, while the document still references it by file_id.
    legacy_bucket: str | None = None
    legacy_file_id: object | None = None

    @property
    def needs_copy_from_legacy(self) -> bool:
        return self.legacy_file_id is not None and self.key_is_new


async def _refs() -> list[FileRef]:
    database = db.get_db()
    refs: list[FileRef] = []
    async for claim in database.expense_claims.find({"receipt": {"$ne": None}}, {"claim_number": 1, "receipt": 1}):
        receipt = claim["receipt"]
        content_type = receipt.get("content_type", "application/octet-stream")
        refs.append(
            FileRef(
                label=f"receipt {claim['claim_number']}",
                collection="expense_claims",
                doc_id=claim["_id"],
                path="receipt",
                content_type=content_type,
                key=receipt.get("key")
                or f"receipts/{claim['claim_number']}/{uuid4().hex}{_EXTENSIONS.get(content_type, '')}",
                key_is_new="key" not in receipt,
                legacy_bucket="receipts" if "file_id" in receipt else None,
                legacy_file_id=receipt.get("file_id"),
            )
        )
    async for user in database.users.find(
        {"service_engineer.signature": {"$exists": True}}, {"service_engineer": 1}
    ):
        signature = user["service_engineer"]["signature"]
        engineer_id = user["service_engineer"]["engineer_id"]
        refs.append(
            FileRef(
                label=f"signature {engineer_id}",
                collection="users",
                doc_id=user["_id"],
                path="service_engineer.signature",
                content_type="image/png",
                key=signature.get("key") or f"signatures/{engineer_id}/{uuid4().hex}.png",
                key_is_new="key" not in signature,
                legacy_bucket="signatures" if "file_id" in signature else None,
                legacy_file_id=signature.get("file_id"),
            )
        )
    return refs


async def _read_source(ref: FileRef) -> bytes:
    if ref.needs_copy_from_legacy:
        bucket = AsyncGridFSBucket(db.get_db(), bucket_name=ref.legacy_bucket)
        return await (await bucket.open_download_stream(ref.legacy_file_id)).read()
    return await GridFSStorage().get(ref.key)


async def _delete_sources(ref: FileRef, target_is_gridfs: bool) -> int:
    """Delete GridFS copies that are no longer needed. Returns how many were deleted."""
    deleted = 0
    if ref.legacy_file_id is not None:
        try:
            await AsyncGridFSBucket(db.get_db(), bucket_name=ref.legacy_bucket).delete(ref.legacy_file_id)
            deleted += 1
        except NoFile:
            pass
        await db.get_db()[ref.collection].update_one(
            {"_id": ref.doc_id}, {"$unset": {f"{ref.path}.file_id": ""}}
        )
    # A keyed GridFS copy is the live file when GridFS is the target, so only delete it when moving to R2.
    if not target_is_gridfs and await GridFSStorage().exists(ref.key):
        await GridFSStorage().delete(ref.key)
        deleted += 1
    return deleted


async def migrate(dry_run: bool, delete_source: bool) -> Report:
    target = get_storage()
    target_is_gridfs = isinstance(target, GridFSStorage)
    report = Report()
    for ref in await _refs():
        if not ref.key_is_new and await target.exists(ref.key):
            report.already_done += 1
        else:
            try:
                data = await _read_source(ref)
            except (NoFile, FileNotFound):
                where = f"bucket {ref.legacy_bucket!r}" if ref.needs_copy_from_legacy else f"key {ref.key}"
                report.problems.append(f"{ref.label}: source file is missing from GridFS ({where}); re-upload it")
                continue
            if dry_run:
                print(f"  would copy {ref.label} ({len(data)} bytes) -> {ref.key}")
                report.copied += 1
                continue

            await target.put(ref.key, data, ref.content_type)
            if hashlib.sha256(await target.get(ref.key)).digest() != hashlib.sha256(data).digest():
                report.problems.append(f"{ref.label}: copy didn't match the original; left unchanged")
                await target.delete(ref.key)
                continue
            if ref.key_is_new:
                # Keep file_id for now so a later --delete-source run can still find the original.
                await db.get_db()[ref.collection].update_one(
                    {"_id": ref.doc_id}, {"$set": {f"{ref.path}.key": ref.key}}
                )
            report.copied += 1
            print(f"  copied {ref.label} -> {ref.key}")

        if delete_source and not dry_run:
            report.deleted_sources += await _delete_sources(ref, target_is_gridfs)
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.migrate_files", description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied; change nothing")
    parser.add_argument("--delete-source", action="store_true", help="Delete GridFS copies after a verified copy")
    args = parser.parse_args()

    print(f"Target storage: {settings.storage_backend}" + (" (dry run)" if args.dry_run else ""))
    await get_storage().check()
    await db.connect()
    try:
        report = await migrate(args.dry_run, args.delete_source)
    finally:
        await db.disconnect()
    verb = "Would copy" if args.dry_run else "Copied"
    print(f"{verb} {report.copied}, already in place {report.already_done}, deleted sources {report.deleted_sources}")
    for problem in report.problems:
        print(f"  PROBLEM: {problem}")
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
