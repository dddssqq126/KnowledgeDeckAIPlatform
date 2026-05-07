import io

import pytest

from app.features.knowledge_bases.services.object_storage import (
    SQLiteObjectStorageClient,
    get_storage_client,
)


@pytest.fixture()
def sqlite_storage_client(tmp_path) -> SQLiteObjectStorageClient:
    return SQLiteObjectStorageClient(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'objects.db'}",
        bucket="kd-test",
    )


@pytest.mark.asyncio
async def test_get_client_returns_patched_instance() -> None:
    client = get_storage_client()
    assert isinstance(client, SQLiteObjectStorageClient)


@pytest.mark.asyncio
async def test_ensure_bucket_is_idempotent(sqlite_storage_client) -> None:
    await sqlite_storage_client.ensure_bucket()
    await sqlite_storage_client.ensure_bucket()  # second call must not raise


@pytest.mark.asyncio
async def test_sqlite_put_then_get_round_trips_bytes(sqlite_storage_client) -> None:
    payload = b"hello\x00sqlite"

    await sqlite_storage_client.put_object(
        "kb/1/files/1/original.txt", io.BytesIO(payload), len(payload), "text/plain"
    )

    assert await sqlite_storage_client.get_object("kb/1/files/1/original.txt") == payload


@pytest.mark.asyncio
async def test_sqlite_repeated_put_overwrites_same_key(sqlite_storage_client) -> None:
    key = "kb/1/files/1/original.txt"
    first = b"first"
    second = b"second"

    await sqlite_storage_client.put_object(key, io.BytesIO(first), len(first), "text/plain")
    await sqlite_storage_client.put_object(key, io.BytesIO(second), len(second), "text/plain")

    assert await sqlite_storage_client.get_object(key) == second


@pytest.mark.asyncio
async def test_sqlite_repeated_delete_is_idempotent(sqlite_storage_client) -> None:
    key = "kb/1/files/1/original.txt"
    payload = b"hello"
    await sqlite_storage_client.put_object(key, io.BytesIO(payload), len(payload), "text/plain")

    await sqlite_storage_client.delete_object(key)
    await sqlite_storage_client.delete_object(key)
