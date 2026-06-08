import io
import json

import pytest
from starlette.requests import Request

from app.db.models import (
    ChatMessage,
    ChatMessageAttachment,
    ChatRole,
    ChatSession,
    User,
)
from app.features.chat.api.chat import _parse_stream_request
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


def _request_with_body(*, content_type: str, body: bytes) -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/stream",
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


@pytest.mark.asyncio
async def test_parse_stream_request_accepts_text_without_attachments() -> None:
    request = _request_with_body(
        content_type="application/json",
        body=json.dumps(
            {
                "session_id": 1,
                "message": "Plain text question",
                "use_rag": True,
                "kb_ids": None,
            }
        ).encode(),
    )

    body, uploads = await _parse_stream_request(request)

    assert body.message == "Plain text question"
    assert uploads == []


@pytest.mark.asyncio
async def test_parse_stream_request_accepts_multipart_text_without_files() -> None:
    boundary = "----kd-test-boundary"
    multipart_body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="session_id"\r\n\r\n'
        "1\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="message"\r\n\r\n'
        "Plain multipart question\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="use_rag"\r\n\r\n'
        "true\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    request = _request_with_body(
        content_type=f"multipart/form-data; boundary={boundary}",
        body=multipart_body,
    )

    body, uploads = await _parse_stream_request(request)

    assert body.message == "Plain multipart question"
    assert uploads == []


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
