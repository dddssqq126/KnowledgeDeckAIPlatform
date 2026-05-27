import pytest

from app.db.models import KnowledgeBase, User
from app.features.rag.services import qdrant_store


@pytest.fixture()
async def two_users_kb(db_session):
    alice = User(username="alice_ft", password="x")
    bob = User(username="bob_ft", password="x")
    db_session.add_all([alice, bob])
    await db_session.flush()
    kb = KnowledgeBase(owner_user_id=alice.id, name="alice-kb")
    db_session.add(kb)
    await db_session.commit()
    await db_session.refresh(alice)
    await db_session.refresh(bob)
    await db_session.refresh(kb)
    return alice, bob, kb


@pytest.mark.asyncio
async def test_file_tags_returns_tags_for_owner(http_client, two_users_kb, monkeypatch):
    alice, _bob, kb = two_users_kb
    rows = [{"file_id": 7, "doc_type": "guide", "intent": "how_to", "tags_topic": ["k8s"], "chunk_count": 3}]

    async def fake_list(*, user_id, kb_id):
        assert user_id == alice.id and kb_id == kb.id
        return rows

    monkeypatch.setattr(qdrant_store, "list_file_tags", fake_list)

    res = await http_client.get(f"/rag/kb/{kb.id}/file-tags", headers={"Authorization": f"Bearer u_{alice.id}"})
    assert res.status_code == 200
    assert res.json() == rows


@pytest.mark.asyncio
async def test_file_tags_404_for_non_owner(http_client, two_users_kb):
    _alice, bob, kb = two_users_kb
    res = await http_client.get(f"/rag/kb/{kb.id}/file-tags", headers={"Authorization": f"Bearer u_{bob.id}"})
    assert res.status_code == 404
