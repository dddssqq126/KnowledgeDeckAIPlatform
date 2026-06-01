import pytest
from sqlalchemy import select

from app.db.models import (
    ChatFeedbackType,
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
