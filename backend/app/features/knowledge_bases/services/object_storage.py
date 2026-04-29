import asyncio
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings


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
        content_type: str,
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
            with path.open("rb") as f:
                return f.read()

        return await asyncio.to_thread(_impl)

    async def delete_object(self, key: str) -> None:
        def _impl() -> None:
            path = self._base / key
            if path.exists():
                path.unlink()

        await asyncio.to_thread(_impl)


_client: LocalObjectStorageClient | None = None


def get_storage_client() -> LocalObjectStorageClient:
    """Process-wide local object storage client."""
    global _client
    if _client is None:
        s = get_settings()
        _client = LocalObjectStorageClient(
            root=s.local_storage_root,
            bucket=s.storage_bucket,
        )
    return _client
