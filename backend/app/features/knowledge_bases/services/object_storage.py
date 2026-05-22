from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO, Protocol

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.base import async_session_factory
from app.db.models import StoredObject


class ObjectStorageClient(Protocol):
    @property
    def bucket(self) -> str: ...

    async def ensure_bucket(self) -> None: ...

    async def put_object(
        self,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str | None,
    ) -> None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def delete_object(self, key: str) -> None: ...


class ObjectNotFoundError(FileNotFoundError):
    """Raised when an object key is missing from configured storage."""

    def __init__(self, *, bucket: str, key: str) -> None:
        super().__init__(f"object not found: bucket={bucket!r} key={key!r}")
        self.bucket = bucket
        self.key = key


class LocalObjectStorageClient:
    """Single-machine local filesystem storage."""

    def __init__(self, *, root: str, bucket: str) -> None:
        self._root = Path(root)
        self._bucket = bucket
        self._base = self._root / bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._base.mkdir, parents=True, exist_ok=True)

    async def put_object(
        self,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str | None,
    ) -> None:
        _ = content_type

        def _impl() -> None:
            path = self._base / key
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = data.read(length)
            with path.open("wb") as f:
                f.write(payload)

        await asyncio.to_thread(_impl)

    async def get_object(self, key: str) -> bytes:
        def _impl() -> bytes:
            path = self._base / key
            try:
                with path.open("rb") as f:
                    return f.read()
            except FileNotFoundError as exc:
                raise ObjectNotFoundError(bucket=self._bucket, key=key) from exc

        return await asyncio.to_thread(_impl)

    async def delete_object(self, key: str) -> None:
        def _impl() -> None:
            path = self._base / key
            if path.exists():
                path.unlink()

        await asyncio.to_thread(_impl)


class SQLiteObjectStorageClient:
    """Database-backed object storage using the app SQLite database."""

    def __init__(self, *, bucket: str) -> None:
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self) -> None:
        """No-op: startup migrations/create_all ensure the backing table exists."""
        return None

    async def put_object(
        self,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str | None,
    ) -> None:
        payload = data.read(length)
        async with async_session_factory()() as session:
            row = await session.scalar(
                select(StoredObject).where(
                    StoredObject.bucket == self._bucket,
                    StoredObject.key == key,
                )
            )
            if row is None:
                session.add(
                    StoredObject(
                        bucket=self._bucket,
                        key=key,
                        content_type=content_type,
                        size_bytes=len(payload),
                        data=payload,
                    )
                )
            else:
                row.content_type = content_type
                row.size_bytes = len(payload)
                row.data = payload
            await session.commit()

    async def get_object(self, key: str) -> bytes:
        async with async_session_factory()() as session:
            data = await session.scalar(
                select(StoredObject.data).where(
                    StoredObject.bucket == self._bucket,
                    StoredObject.key == key,
                )
            )
            if data is None:
                raise ObjectNotFoundError(bucket=self._bucket, key=key)
            return data

    async def delete_object(self, key: str) -> None:
        async with async_session_factory()() as session:
            await session.execute(
                delete(StoredObject).where(
                    StoredObject.bucket == self._bucket,
                    StoredObject.key == key,
                )
            )
            await session.commit()


_client: ObjectStorageClient | None = None


def get_storage_client() -> ObjectStorageClient:
    """Process-wide object storage client."""
    global _client
    if _client is None:
        s = get_settings()
        if s.object_storage_backend == "sqlite":
            _client = SQLiteObjectStorageClient(bucket=s.storage_bucket)
        elif s.object_storage_backend == "local":
            _client = LocalObjectStorageClient(
                root=s.local_storage_root,
                bucket=s.storage_bucket,
            )
        else:
            raise ValueError(
                "unsupported object_storage_backend "
                f"{s.object_storage_backend!r}; expected 'sqlite' or 'local'"
            )
    return _client


def get_minio_client() -> ObjectStorageClient:
    """Backward-compatible alias for historical call sites/tests."""
    return get_storage_client()
