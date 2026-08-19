"""Thin async wrapper around the S3 API used by the document endpoints.

Locally this talks to LocalStack through ``AWS_ENDPOINT_URL``; in production the
same calls hit real S3 once that setting is empty.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.exceptions import NotFoundError, StorageError

CHUNK_SIZE = 1024 * 1024

_MISSING_OBJECT_CODES = {"404", "NoSuchKey", "NoSuchBucket"}
# aioboto3 ships no py.typed/stubs, so its dynamically-built client() return
# type can't be inferred; typing this Any avoids a bogus __aenter__ error.
_session: Any = aioboto3.Session()


def build_document_key(project_id: int, document_id: int, filename: str) -> str:
    """Key layout that keeps every object for one project under a shared prefix."""
    return f"projects/{project_id}/{document_id}/{filename}"


@asynccontextmanager
async def s3_client() -> AsyncIterator[Any]:
    async with _session.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url or None,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    ) as client:
        yield client


def _is_missing_object(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    return str(error.get("Code")) in _MISSING_OBJECT_CODES


def _storage_error(action: str, exc: Exception) -> StorageError:
    return StorageError(f"Could not {action} the document in object storage")


async def ensure_bucket() -> None:
    """Create the configured bucket when it is missing (LocalStack starts empty)."""
    async with s3_client() as client:
        try:
            await client.head_bucket(Bucket=settings.s3_bucket_name)
            return
        except ClientError as exc:
            if not _is_missing_object(exc):
                raise _storage_error("reach", exc) from exc

        create_kwargs: dict[str, Any] = {"Bucket": settings.s3_bucket_name}
        if settings.aws_region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.aws_region}

        try:
            await client.create_bucket(**create_kwargs)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code"))
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise _storage_error("create the bucket for", exc) from exc


async def upload(key: str, data: bytes, content_type: str) -> None:
    try:
        async with s3_client() as client:
            await client.put_object(
                Bucket=settings.s3_bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
    except (BotoCoreError, ClientError) as exc:
        raise _storage_error("store", exc) from exc


async def ensure_object_exists(key: str) -> None:
    """Fail fast with a proper status code before a streaming response starts."""
    try:
        async with s3_client() as client:
            await client.head_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError as exc:
        if _is_missing_object(exc):
            raise NotFoundError("Document content is missing from storage") from exc
        raise _storage_error("read", exc) from exc
    except BotoCoreError as exc:
        raise _storage_error("read", exc) from exc


async def stream_object(key: str) -> AsyncIterator[bytes]:
    """Yield the object body in chunks so large downloads stay off the heap."""
    async with s3_client() as client:
        try:
            response = await client.get_object(Bucket=settings.s3_bucket_name, Key=key)
        except ClientError as exc:
            if _is_missing_object(exc):
                raise NotFoundError("Document content is missing from storage") from exc
            raise _storage_error("read", exc) from exc

        # aiobotocore hands back an aiohttp response, so chunked reads go
        # through its StreamReader rather than a sized ``read()``.
        async with response["Body"] as body:
            async for chunk in body.content.iter_chunked(CHUNK_SIZE):
                yield chunk


async def delete_object(key: str) -> None:
    try:
        async with s3_client() as client:
            await client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except ClientError as exc:
        if _is_missing_object(exc):
            return
        raise _storage_error("delete", exc) from exc
    except BotoCoreError as exc:
        raise _storage_error("delete", exc) from exc


async def delete_objects(keys: list[str]) -> None:
    if not keys:
        return

    try:
        async with s3_client() as client:
            # delete_objects caps each request at 1000 keys.
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                await client.delete_objects(
                    Bucket=settings.s3_bucket_name,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                )
    except ClientError as exc:
        if _is_missing_object(exc):
            return
        raise _storage_error("delete", exc) from exc
    except BotoCoreError as exc:
        raise _storage_error("delete", exc) from exc
