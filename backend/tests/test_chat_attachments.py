import io

import pytest

from app.db.models import ChatSession, User
from app.features.chat.api import chat as chat_api


@pytest.fixture()
async def alice(db_session) -> User:
    user = User(username="alice", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


async def make_chat(db_session, user: User) -> ChatSession:
    chat = ChatSession(owner_user_id=user.id, title="Attachments")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


@pytest.mark.asyncio
async def test_chat_stream_appends_txt_attachment_to_context(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    captured: dict[str, object] = {}

    async def fake_stream_answer(**kwargs):
        captured["context"] = kwargs["context"]
        captured["user_message"] = kwargs["user_message"]
        yield "answer"

    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "session_id": str(chat.id),
            "message": "Summarize the attachment",
            "use_rag": "false",
            "kb_ids": "null",
            "deep_mode": "false",
        },
        files={
            "files": ("notes.txt", io.BytesIO(b"attachment body"), "text/plain"),
        },
    )

    assert res.status_code == 200
    assert "event: token" in res.text
    assert captured["user_message"] == "Summarize the attachment"
    assert "User-uploaded files for this chat turn:" in str(captured["context"])
    assert "[Attachment 1] notes.txt" in str(captured["context"])
    assert "attachment body" in str(captured["context"])


@pytest.mark.asyncio
async def test_chat_stream_appends_bas_and_word_txt_attachments_to_context(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    captured: dict[str, object] = {}

    async def fake_stream_answer(**kwargs):
        captured["context"] = kwargs["context"]
        yield "answer"

    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "session_id": str(chat.id),
            "message": "Summarize the attachments",
            "use_rag": "false",
            "kb_ids": "null",
            "deep_mode": "false",
        },
        files=[
            (
                "files",
                (
                    "Macro.bas",
                    io.BytesIO(b"Sub Main()\n  MsgBox \"hello\"\nEnd Sub\n"),
                    "text/plain",
                ),
            ),
            (
                "files",
                ("notes.word.txt", io.BytesIO(b"word txt body"), "text/plain"),
            ),
        ],
    )

    assert res.status_code == 200
    context = str(captured["context"])
    assert "[Attachment 1] Macro.bas" in context
    assert "Sub Main()" in context
    assert "[Attachment 2] notes.word.txt" in context
    assert "word txt body" in context


@pytest.mark.asyncio
async def test_chat_stream_rejects_invalid_attachment_extension(
    http_client, db_session, alice: User
) -> None:
    chat = await make_chat(db_session, alice)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "session_id": str(chat.id),
            "message": "Read this",
            "use_rag": "false",
            "kb_ids": "null",
        },
        files={
            "files": (
                "malware.exe",
                io.BytesIO(b"not allowed"),
                "application/octet-stream",
            ),
        },
    )

    assert res.status_code == 400
    assert res.json() == {"detail": "malware.exe: invalid_extension"}


@pytest.mark.asyncio
async def test_chat_stream_rejects_legacy_ppt_attachment(
    http_client, db_session, alice: User
) -> None:
    chat = await make_chat(db_session, alice)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "session_id": str(chat.id),
            "message": "Read this",
            "use_rag": "false",
            "kb_ids": "null",
        },
        files={
            "files": (
                "legacy.ppt",
                io.BytesIO(b"\xd0\xcf\x11\xe0"),
                "application/vnd.ms-powerpoint",
            ),
        },
    )

    assert res.status_code == 400
    assert res.json() == {"detail": "legacy.ppt: invalid_extension"}


@pytest.mark.asyncio
async def test_chat_stream_rejects_invalid_text_attachment_content(
    http_client, db_session, alice: User
) -> None:
    chat = await make_chat(db_session, alice)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "session_id": str(chat.id),
            "message": "Read this",
            "use_rag": "false",
            "kb_ids": "null",
        },
        files={
            "files": ("bad.txt", io.BytesIO(b"hello\x00world"), "text/plain"),
        },
    )

    assert res.status_code == 400
    assert res.json() == {"detail": "bad.txt: invalid_content"}
