"""S3 兼容对象存储（MinIO）客户端：put / get（流式）/ exists / delete。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class ObjectNotFound(Exception):
    """对象不存在。"""


class S3Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self.bucket = s.S3_BUCKET
        self._session = aioboto3.Session()
        self._kwargs: dict[str, Any] = {
            "endpoint_url": s.S3_ENDPOINT,
            "aws_access_key_id": s.S3_ACCESS_KEY,
            "aws_secret_access_key": s.S3_SECRET_KEY,
            "region_name": s.S3_REGION,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 2},
            ),
        }

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[Any]:
        async with self._session.client("s3", **self._kwargs) as client:
            yield client

    async def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        async with self._client() as c:
            await c.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get_bytes(self, key: str) -> bytes:
        async with self._client() as c:
            try:
                resp = await c.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    raise ObjectNotFound(key) from exc
                raise
            body = resp["Body"]
            try:
                data: bytes = await body.read()
            finally:
                body.close()
            return data

    async def iter_bytes(self, key: str, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        """流式读取（供下载转发）；对象不存在时在首次迭代抛 ObjectNotFound。"""
        async with self._client() as c:
            try:
                resp = await c.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    raise ObjectNotFound(key) from exc
                raise
            body = resp["Body"]
            try:
                async for chunk in body.iter_chunks(chunk_size):
                    yield chunk
            finally:
                body.close()

    async def exists(self, key: str) -> bool:
        async with self._client() as c:
            try:
                await c.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if _is_not_found(exc):
                    return False
                raise
            return True

    async def delete(self, key: str) -> None:
        """删除对象；对象不存在视为成功（幂等）。"""
        async with self._client() as c:
            await c.delete_object(Bucket=self.bucket, Key=key)

    async def ping(self) -> bool:
        """桶是否可访问（供运维检查，不进入 /readyz）。"""
        async with self._client() as c:
            try:
                await c.head_bucket(Bucket=self.bucket)
            except ClientError:
                return False
            return True


def _is_not_found(exc: ClientError) -> bool:
    return str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND_CODES


_storage: S3Storage | None = None


def get_storage() -> S3Storage:
    """进程内单例（测试可替换 ``app.storage.s3._storage``）。"""
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage
