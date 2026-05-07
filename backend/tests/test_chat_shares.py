from datetime import datetime, timezone

import pytest

from app.db.models import ChatMessage, ChatRole, ChatSession, User


@pytest.fixture()
async def alice(db_session) -> User:
    user = User(username="alice", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def bob(db_session) -> User:
    user = User(username="bob", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


@pytest.mark.asyncio
async def test_owner_creates_stable_share(http_client, db_session, alice: User) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Shared notes")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    first = await http_client.post(f"/chat/sessions/{chat.id}/share", headers=auth(alice))
    second = await http_client.post(f"/chat/sessions/{chat.id}/share", headers=auth(alice))

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["token"] == second.json()["token"]
    assert first.json()["url_path"] == f"/shared-chat/{first.json()['token']}"


@pytest.mark.asyncio
async def test_other_user_cannot_create_share(
    http_client, db_session, alice: User, bob: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Private")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    res = await http_client.post(f"/chat/sessions/{chat.id}/share", headers=auth(bob))

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_authenticated_user_can_read_shared_session(
    http_client, db_session, alice: User, bob: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="RAG summary")
    db_session.add(chat)
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(
                session_id=chat.id,
                role=ChatRole.USER,
                content="Summarize the source.",
                citations=None,
            ),
            ChatMessage(
                session_id=chat.id,
                role=ChatRole.ASSISTANT,
                content="Summary with a citation.",
                citations=[{"file_id": 7, "filename": "source.pdf"}],
            ),
        ]
    )
    await db_session.commit()
    await db_session.refresh(chat)

    share = await http_client.post(f"/chat/sessions/{chat.id}/share", headers=auth(alice))
    token = share.json()["token"]
    res = await http_client.get(f"/chat/shares/{token}", headers=auth(bob))

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "RAG summary"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["citations"] == [{"file_id": 7, "filename": "source.pdf"}]


@pytest.mark.asyncio
async def test_shared_session_returns_404_when_deleted(
    http_client, db_session, alice: User, bob: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Deleted")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    share = await http_client.post(f"/chat/sessions/{chat.id}/share", headers=auth(alice))
    token = share.json()["token"]
    chat.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    res = await http_client.get(f"/chat/shares/{token}", headers=auth(bob))

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_missing_share_token_returns_404(http_client, alice: User) -> None:
    res = await http_client.get("/chat/shares/nope", headers=auth(alice))

    assert res.status_code == 404
