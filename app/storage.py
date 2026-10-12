"""File storage for receipts and signatures.

Files are addressed by a key such as "receipts/EXP-2026-001/3f2a….pdf". STORAGE_BACKEND picks where they live:

- "gridfs" (default): inside MongoDB, convenient for local development.
- "r2": a Cloudflare R2 bucket (S3-compatible). MongoDB only stores the key.
"""

import asyncio
from functools import lru_cache
from typing import Protocol
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from app.config import settings
from app.db import get_db


class FileNotFound(Exception):
    pass


class Storage(Protocol):
    async def check(self) -> None: ...
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
    def link(self, key: str, filename: str, content_type: str) -> str | None:
        """A short-lived URL the browser can fetch directly, or None if the backend has no such links."""


def content_disposition(filename: str) -> str:
    return f"inline; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"


class GridFSStorage:
    def _bucket(self) -> AsyncGridFSBucket:
        return AsyncGridFSBucket(get_db(), bucket_name="files")

    async def check(self) -> None:
        pass

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._bucket().upload_from_stream_with_id(key, key, data, metadata={"content_type": content_type})

    async def get(self, key: str) -> bytes:
        try:
            stream = await self._bucket().open_download_stream(key)
        except NoFile:
            raise FileNotFound(key)
        return await stream.read()

    async def exists(self, key: str) -> bool:
        return await get_db()["files.files"].count_documents({"_id": key}, limit=1) > 0

    async def delete(self, key: str) -> None:
        try:
            await self._bucket().delete(key)
        except NoFile:
            pass

    def link(self, key: str, filename: str, content_type: str) -> str | None:
        return None


class R2Storage:
    def __init__(self) -> None:
        endpoint = settings.r2_endpoint or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        self._bucket = settings.r2_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )

    # boto3 is synchronous, so calls run in a worker thread to keep the event loop free.
    async def _call(self, method: str, **kwargs):
        return await asyncio.to_thread(getattr(self._client, method), Bucket=self._bucket, **kwargs)

    async def check(self) -> None:
        """Fail at startup, with a clear message, if the bucket or credentials are wrong."""
        try:
            await self._call("head_bucket")
        except ClientError as exc:
            raise RuntimeError(f"Can't access R2 bucket {self._bucket!r}: {exc}") from exc

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._call("put_object", Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        try:
            response = await self._call("get_object", Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise FileNotFound(key)
            raise
        return await asyncio.to_thread(response["Body"].read)

    async def exists(self, key: str) -> bool:
        try:
            await self._call("head_object", Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return False
            raise
        return True

    async def delete(self, key: str) -> None:
        await self._call("delete_object", Key=key)  # no error if it's already gone

    def link(self, key: str, filename: str, content_type: str) -> str | None:
        # Signed locally; no request to R2. Anyone with the URL can fetch the file until it expires.
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": content_disposition(filename),
            },
            ExpiresIn=settings.file_link_expiry_seconds,
        )


@lru_cache
def get_storage() -> Storage:
    if settings.storage_backend == "r2":
        missing = [
            name
            for name in ("r2_access_key_id", "r2_secret_access_key", "r2_bucket")
            if not getattr(settings, name)
        ]
        if not (settings.r2_account_id or settings.r2_endpoint):
            missing.append("r2_account_id")
        if missing:
            raise RuntimeError(f"STORAGE_BACKEND=r2 needs: {', '.join(m.upper() for m in missing)}")
        return R2Storage()
    return GridFSStorage()
