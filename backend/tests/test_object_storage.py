import io

import pytest

from app.features.knowledge_bases.services.object_storage import (
    LocalObjectStorageClient,
    get_storage_client,
)


@pytest.mark.asyncio
async def test_get_client_returns_patched_instance() -> None:
    client = get_storage_client()
    assert isinstance(client, LocalObjectStorageClient)


@pytest.mark.asyncio
async def test_ensure_bucket_is_idempotent() -> None:
    client = get_storage_client()
    await client.ensure_bucket()
    await client.ensure_bucket()  # second call must not raise


@pytest.mark.asyncio
async def test_put_then_delete_object_round_trip() -> None:
    client = get_storage_client()
    await client.ensure_bucket()
    payload = b"hello"
    await client.put_object(
        "kb/1/files/1/original.txt", io.BytesIO(payload), len(payload), "text/plain"
    )
    # Re-uploading same key must succeed (overwrite).
    await client.put_object(
        "kb/1/files/1/original.txt", io.BytesIO(payload), len(payload), "text/plain"
    )
    await client.delete_object("kb/1/files/1/original.txt")
    # Deleting twice must not raise.
    await client.delete_object("kb/1/files/1/original.txt")
