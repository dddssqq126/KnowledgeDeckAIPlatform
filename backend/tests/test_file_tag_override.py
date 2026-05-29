import io

import pytest
from sqlalchemy import select

from app.db.models import FileStatus, KnowledgeBase, KnowledgeFile, User
from app.features.knowledge_bases.api import files as files_module


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


@pytest.fixture()
async def two_users_file(db_session):
    alice = User(username="alice_override", password="x")
    bob = User(username="bob_override", password="x")
    db_session.add_all([alice, bob])
    await db_session.flush()
    kb = KnowledgeBase(owner_user_id=alice.id, name="ATE docs")
    db_session.add(kb)
    await db_session.flush()
    row = KnowledgeFile(
        knowledge_base_id=kb.id,
        owner_user_id=alice.id,
        filename="flow.txt",
        extension="txt",
        size_bytes=10,
        content_sha256="x",
        storage_key=f"kb/{kb.id}/files/1/original.txt",
        status=FileStatus.INDEXED,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(alice)
    await db_session.refresh(bob)
    await db_session.refresh(kb)
    await db_session.refresh(row)
    await files_module.get_storage_client().put_object(
        row.storage_key,
        io.BytesIO(b"hello"),
        5,
        "text/plain",
    )
    return alice, bob, kb, row


@pytest.mark.asyncio
async def test_update_file_tags_reindexes_and_returns_summary(
    http_client, db_session, two_users_file, monkeypatch
):
    alice, _bob, kb, row = two_users_file
    calls = {"cleanup": [], "ingest": []}

    async def fake_cleanup(*, file_id):
        calls["cleanup"].append(file_id)

    async def fake_ingest(*, session, file_row, data):
        calls["ingest"].append((file_row.id, data))
        file_row.status = FileStatus.INDEXED
        await session.commit()

    async def fake_list_file_tags(*, user_id, kb_id):
        return [
            {
                "file_id": row.id,
                "doc_type": "guide",
                "intent": "how_to",
                "tags_topic": ["ate"],
                "vendor": "advantest",
                "platform": "v93000",
                "knowledge_type": "internal_bkm",
                "chunk_count": 4,
            }
        ]

    monkeypatch.setattr(files_module.ingestion, "cleanup_file_vectors", fake_cleanup)
    monkeypatch.setattr(files_module.ingestion, "ingest_file", fake_ingest)
    monkeypatch.setattr(
        files_module.qdrant_store, "list_file_tags", fake_list_file_tags
    )

    res = await http_client.patch(
        f"/knowledge-bases/{kb.id}/files/{row.id}/tags",
        json={
            "vendor": "advantest",
            "platform": "v93000",
            "knowledge_type": "internal_bkm",
        },
        headers=auth(alice),
    )

    assert res.status_code == 200
    assert res.json() == {
        "file_id": row.id,
        "doc_type": "guide",
        "intent": "how_to",
        "tags_topic": ["ate"],
        "vendor": "advantest",
        "platform": "v93000",
        "knowledge_type": "internal_bkm",
        "chunk_count": 4,
    }
    assert calls == {"cleanup": [row.id], "ingest": [(row.id, b"hello")]}
    stored = await db_session.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == row.id)
    )
    assert stored.tag_vendor == "advantest"
    assert stored.tag_platform == "v93000"
    assert stored.tag_knowledge_type == "internal_bkm"


@pytest.mark.asyncio
async def test_update_file_tags_accepts_flexible_values(
    http_client, db_session, two_users_file, monkeypatch
):
    alice, _bob, kb, row = two_users_file
    calls = {"cleanup": [], "ingest": []}

    async def fake_cleanup(*, file_id):
        calls["cleanup"].append(file_id)

    async def fake_ingest(*, session, file_row, data):
        calls["ingest"].append((file_row.id, data))
        file_row.status = FileStatus.INDEXED
        await session.commit()

    async def fake_list_file_tags(*, user_id, kb_id):
        return [
            {
                "file_id": row.id,
                "doc_type": "reference",
                "intent": "conceptual",
                "tags_topic": ["5g"],
                "vendor": "unknown",
                "platform": "unknown",
                "knowledge_type": "unknown",
                "chunk_count": 2,
            }
        ]

    monkeypatch.setattr(files_module.ingestion, "cleanup_file_vectors", fake_cleanup)
    monkeypatch.setattr(files_module.ingestion, "ingest_file", fake_ingest)
    monkeypatch.setattr(
        files_module.qdrant_store, "list_file_tags", fake_list_file_tags
    )

    res = await http_client.patch(
        f"/knowledge-bases/{kb.id}/files/{row.id}/tags",
        json={
            "vendor": "3GPP",
            "platform": "5G NR",
            "knowledge_type": "Wireless Standard",
        },
        headers=auth(alice),
    )

    assert res.status_code == 200
    assert res.json()["vendor"] == "3gpp"
    assert res.json()["platform"] == "5g_nr"
    assert res.json()["knowledge_type"] == "wireless_standard"
    assert calls == {"cleanup": [row.id], "ingest": [(row.id, b"hello")]}
    stored = await db_session.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == row.id)
    )
    assert stored.tag_vendor == "3gpp"
    assert stored.tag_platform == "5g_nr"
    assert stored.tag_knowledge_type == "wireless_standard"


@pytest.mark.asyncio
async def test_update_file_tags_rejects_blank_value(http_client, two_users_file):
    alice, _bob, kb, row = two_users_file
    res = await http_client.patch(
        f"/knowledge-bases/{kb.id}/files/{row.id}/tags",
        json={
            "vendor": "   ",
            "platform": "v93000",
            "knowledge_type": "internal_bkm",
        },
        headers=auth(alice),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_update_file_tags_enforces_owner(http_client, two_users_file):
    _alice, bob, kb, row = two_users_file
    res = await http_client.patch(
        f"/knowledge-bases/{kb.id}/files/{row.id}/tags",
        json={
            "vendor": "advantest",
            "platform": "v93000",
            "knowledge_type": "internal_bkm",
        },
        headers=auth(bob),
    )
    assert res.status_code == 404
