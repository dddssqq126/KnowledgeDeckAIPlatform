import io

import pytest

from app.db.models import ChatMessage, ChatMessageAttachment, ChatRole, ChatSession, User
from app.features.knowledge_bases.services.object_storage import get_storage_client


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
async def test_session_history_includes_chat_attachment_metadata(
    http_client, db_session, alice: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Attachment chat")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.USER,
        content="Please review this.",
        citations=None,
    )
    db_session.add(message)
    await db_session.flush()
    attachment = ChatMessageAttachment(
        message_id=message.id,
        owner_user_id=alice.id,
        filename="notes.txt",
        extension="txt",
        size_bytes=11,
        content_sha256="sha",
        storage_key="chat/test/notes.txt",
    )
    db_session.add(attachment)
    await db_session.commit()

    res = await http_client.get(f"/chat/sessions/{chat.id}", headers=auth(alice))

    assert res.status_code == 200
    body = res.json()
    assert body["messages"][0]["attachments"] == [
        {
            "id": attachment.id,
            "filename": "notes.txt",
            "extension": "txt",
            "size_bytes": 11,
            "created_at": attachment.created_at.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_owner_can_download_chat_attachment(
    http_client, db_session, alice: User, bob: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Attachment chat")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.USER,
        content="",
        citations=None,
    )
    db_session.add(message)
    await db_session.flush()
    payload = b"hello world"
    storage_key = "chat/test/download.txt"
    await get_storage_client().put_object(
        storage_key,
        io.BytesIO(payload),
        len(payload),
        "text/plain; charset=utf-8",
    )
    attachment = ChatMessageAttachment(
        message_id=message.id,
        owner_user_id=alice.id,
        filename="download.txt",
        extension="txt",
        size_bytes=len(payload),
        content_sha256="sha",
        storage_key=storage_key,
    )
    db_session.add(attachment)
    await db_session.commit()

    owner_res = await http_client.get(
        f"/chat/attachments/{attachment.id}/download", headers=auth(alice)
    )
    other_res = await http_client.get(
        f"/chat/attachments/{attachment.id}/download", headers=auth(bob)
    )

    assert owner_res.status_code == 200
    assert owner_res.content == payload
    assert "download.txt" in owner_res.headers["Content-Disposition"]
    assert other_res.status_code == 404
