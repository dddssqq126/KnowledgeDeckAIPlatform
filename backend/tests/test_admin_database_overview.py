import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import ChatMessage, ChatRole, ChatSession, User


@pytest.fixture()
async def http_client():
    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_database_overview_lists_users_and_chat_messages(
    http_client, db_session
) -> None:
    user = User(username="admin", password="secret")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    chat = ChatSession(owner_user_id=user.id, title="Gemini styled admin")
    db_session.add(chat)
    await db_session.flush()
    db_session.add_all(
        [
            ChatMessage(session_id=chat.id, role=ChatRole.USER, content="Hello DB"),
            ChatMessage(
                session_id=chat.id, role=ChatRole.ASSISTANT, content="Printed rows"
            ),
        ]
    )
    await db_session.commit()

    response = await http_client.get(
        "/admin/database-overview",
        headers={"Authorization": f"Bearer u_{user.id}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {"users": 1, "chat_sessions": 1, "chat_messages": 2}
    assert body["users"][0]["username"] == "admin"
    assert body["users"][0]["password"] == "secret"
    assert body["users"][0]["chat_session_count"] == 1
    assert body["users"][0]["chat_message_count"] == 2
    assert body["chat_sessions"][0]["owner_username"] == "admin"
    assert [message["content"] for message in body["chat_sessions"][0]["messages"]] == [
        "Hello DB",
        "Printed rows",
    ]


@pytest.mark.asyncio
async def test_database_overview_requires_auth(http_client) -> None:
    response = await http_client.get("/admin/database-overview")

    assert response.status_code == 401
