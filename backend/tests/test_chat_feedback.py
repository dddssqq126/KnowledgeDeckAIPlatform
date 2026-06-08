import io
import pytest
from sqlalchemy import select

from app.db.models import (
    ChatFeedbackType,
    ChatInputFile,
    ChatMessage,
    ChatMessageFeedback,
    ChatRole,
    ChatSession,
    User,
)


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
async def test_owner_can_upsert_assistant_message_feedback(
    http_client, db_session, alice: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Feedback")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.ASSISTANT,
        content="Helpful answer",
        citations=None,
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    first = await http_client.post(
        f"/chat/messages/{message.id}/feedback",
        headers=auth(alice),
        json={"feedback": "like"},
    )
    second = await http_client.post(
        f"/chat/messages/{message.id}/feedback",
        headers=auth(alice),
        json={"feedback": "dislike"},
    )

    assert first.status_code == 200
    assert first.json()["feedback"] == "like"
    assert second.status_code == 200
    assert second.json()["feedback"] == "dislike"

    rows = (
        await db_session.scalars(
            select(ChatMessageFeedback).where(
                ChatMessageFeedback.message_id == message.id
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].feedback is ChatFeedbackType.DISLIKE
    assert rows[0].content == "Helpful answer"


@pytest.mark.asyncio
async def test_session_detail_includes_existing_message_feedback(
    http_client, db_session, alice: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Feedback detail")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.ASSISTANT,
        content="Already rated",
        citations=None,
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        ChatMessageFeedback(
            message_id=message.id,
            owner_user_id=alice.id,
            feedback=ChatFeedbackType.LIKE,
            content=message.content,
        )
    )
    await db_session.commit()

    res = await http_client.get(f"/chat/sessions/{chat.id}", headers=auth(alice))

    assert res.status_code == 200
    assert res.json()["messages"][0]["feedback"] == "like"


@pytest.mark.asyncio
async def test_session_detail_includes_chat_input_files_and_downloads_them(
    http_client, db_session, alice: User
) -> None:
    from app.features.knowledge_bases.services.object_storage import get_storage_client

    chat = ChatSession(owner_user_id=alice.id, title="Input files")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.USER,
        content="Read this",
        citations=None,
    )
    db_session.add(message)
    await db_session.flush()

    storage = get_storage_client()
    await storage.ensure_bucket()
    storage_key = f"chat-input-files/{alice.id}/{chat.id}/{message.id}/1-abc.txt"
    await storage.put_object(
        storage_key,
        io.BytesIO(b"saved input file"),
        len(b"saved input file"),
        "text/plain",
    )
    input_file = ChatInputFile(
        owner_user_id=alice.id,
        session_id=chat.id,
        message_id=message.id,
        filename="input.txt",
        extension="txt",
        size_bytes=len(b"saved input file"),
        content_sha256="abc",
        storage_key=storage_key,
    )
    db_session.add(input_file)
    await db_session.commit()
    await db_session.refresh(input_file)

    detail = await http_client.get(f"/chat/sessions/{chat.id}", headers=auth(alice))
    download = await http_client.get(
        f"/chat/input-files/{input_file.id}/download", headers=auth(alice)
    )

    assert detail.status_code == 200
    files = detail.json()["messages"][0]["input_files"]
    assert files == [
        {
            "id": input_file.id,
            "filename": "input.txt",
            "extension": "txt",
            "size_bytes": len(b"saved input file"),
            "created_at": files[0]["created_at"],
        }
    ]
    assert download.status_code == 200
    assert download.content == b"saved input file"
    assert 'filename="input.txt"' in download.headers["content-disposition"]


@pytest.mark.asyncio
async def test_other_user_cannot_feedback_private_message(
    http_client, db_session, alice: User, bob: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Private")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.ASSISTANT,
        content="Private answer",
        citations=None,
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    res = await http_client.post(
        f"/chat/messages/{message.id}/feedback",
        headers=auth(bob),
        json={"feedback": "like"},
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_user_messages_cannot_receive_feedback(
    http_client, db_session, alice: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="User message")
    db_session.add(chat)
    await db_session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role=ChatRole.USER,
        content="Question",
        citations=None,
    )
    db_session.add(message)
    await db_session.commit()
    await db_session.refresh(message)

    res = await http_client.post(
        f"/chat/messages/{message.id}/feedback",
        headers=auth(alice),
        json={"feedback": "like"},
    )

    assert res.status_code == 404
