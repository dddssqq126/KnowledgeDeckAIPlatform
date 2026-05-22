import asyncio
from pathlib import Path
from typing import BinaryIO

import aiosqlite
from sqlalchemy.engine import make_url

from app.core.config import get_settings


class SQLiteObjectStorageClient:
    """SQLite-backed object storage for single-node deployments and tests."""

    def __init__(self, *, database_url: str, bucket: str) -> None:
        self._database_url = database_url
        self._bucket = bucket
        self._db_path = self._sqlite_path(database_url)

    @staticmethod
    def _sqlite_path(database_url: str) -> str:
        url = make_url(database_url)
        if url.drivername not in {"sqlite", "sqlite+aiosqlite"}:
            raise ValueError("SQLiteObjectStorageClient requires a sqlite database_url")
        database = url.database or ":memory:"
        if database == ":memory:":
            return database
        return str(Path(database).expanduser())

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS object_blobs (
                    bucket TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    data BLOB NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (bucket, key)
                )
                """
            )
            await db.commit()

    async def put_object(
        self,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> None:
        payload = await asyncio.to_thread(data.read, length)
        await self.ensure_bucket()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO object_blobs (bucket, key, content_type, data, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bucket, key) DO UPDATE SET
                    content_type = excluded.content_type,
                    data = excluded.data,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self._bucket, key, content_type, payload),
            )
            await db.commit()

    async def get_object(self, key: str) -> bytes:
        await self.ensure_bucket()
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data FROM object_blobs WHERE bucket = ? AND key = ?",
                (self._bucket, key),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            raise FileNotFoundError(key)
        return bytes(row[0])

    async def delete_object(self, key: str) -> None:
        await self.ensure_bucket()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM object_blobs WHERE bucket = ? AND key = ?",
                (self._bucket, key),
            )
            await db.commit()


_client: SQLiteObjectStorageClient | None = None


def get_storage_client() -> SQLiteObjectStorageClient:
    """Process-wide SQLite object storage client."""
    global _client
    if _client is None:
        s = get_settings()
        _client = SQLiteObjectStorageClient(
            database_url=s.database_url,
            bucket=s.storage_bucket,
        )
    return _client
