import json

import pytest

from app.db.models import ChatSession, User
from app.features.chat.api import chat as chat_api
from app.features.rag.services import rag


@pytest.fixture()
async def alice(db_session) -> User:
    user = User(username="alice", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


@pytest.mark.asyncio
async def test_chat_stream_deep_mode_uses_checked_retrieval(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Deep")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    captured: dict[str, object] = {}

    async def fake_rewrite_for_retrieval(**_kwargs):
        return "rewritten query"

    async def fake_checked_retrieval(**kwargs):
        captured["checked_kwargs"] = kwargs
        return rag.RagContextResult(
            context="checked context",
            citations=[{"file_id": 7, "filename": "source.txt"}],
            diagnostics=rag.RagDiagnostics(
                deep_mode=True,
                coverage_status="miss",
                coverage_reason="missing direct answer",
            ),
        )

    async def fail_normal_retrieval(**_kwargs):
        raise AssertionError("normal retrieve_context should not run in deep mode")

    async def fake_stream_answer(**kwargs):
        captured["retrieval_note"] = kwargs.get("retrieval_note")
        captured["context"] = kwargs.get("context")
        yield "answer"

    monkeypatch.setattr(
        chat_api.chat_service,
        "rewrite_for_retrieval",
        fake_rewrite_for_retrieval,
    )
    monkeypatch.setattr(chat_api.rag, "retrieve_context_checked", fake_checked_retrieval)
    monkeypatch.setattr(chat_api.rag, "retrieve_context", fail_normal_retrieval)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        json={
            "session_id": chat.id,
            "message": "What does the source say?",
            "use_rag": True,
            "deep_mode": True,
        },
    )

    assert res.status_code == 200
    assert "event: token" in res.text
    assert "feedback_message_id" in res.text
    assert captured["checked_kwargs"] == {
        "user_id": alice.id,
        "kb_ids": None,
        "query": "rewritten query",
        "user_message": "What does the source say?",
        "query_tags": chat_api.chat_service.detect_query_tags(
            "What does the source say?", "rewritten query"
        ),
        "deep_mode": True,
    }
    assert captured["context"] == "checked context"
    assert isinstance(captured["retrieval_note"], str)


@pytest.mark.asyncio
async def test_chat_stream_normal_rag_skips_checked_retrieval(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Normal")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    captured: dict[str, object] = {}

    async def fake_rewrite_for_retrieval(**_kwargs):
        return "rewritten query"

    async def fail_checked_retrieval(**_kwargs):
        raise AssertionError("checked retrieval should not run outside deep mode")

    async def fake_normal_retrieval(**kwargs):
        captured["normal_kwargs"] = kwargs
        return "normal context", [{"file_id": 8, "filename": "normal.txt"}]

    async def fake_stream_answer(**kwargs):
        captured["retrieval_note"] = kwargs.get("retrieval_note")
        captured["context"] = kwargs.get("context")
        yield "answer"

    monkeypatch.setattr(
        chat_api.chat_service,
        "rewrite_for_retrieval",
        fake_rewrite_for_retrieval,
    )
    monkeypatch.setattr(chat_api.rag, "retrieve_context_checked", fail_checked_retrieval)
    monkeypatch.setattr(chat_api.rag, "retrieve_context", fake_normal_retrieval)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        json={
            "session_id": chat.id,
            "message": "What does the source say?",
            "use_rag": True,
            "deep_mode": False,
        },
    )

    assert res.status_code == 200
    assert captured["normal_kwargs"]["deep_mode"] is False
    assert captured["context"] == "normal context"
    assert captured["retrieval_note"] is None


@pytest.mark.asyncio
async def test_chat_stream_uses_attachment_text_as_retrieval_hint(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Attachment RAG")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    captured: dict[str, object] = {}

    async def fake_rewrite_for_retrieval(**kwargs):
        captured["rewrite_kwargs"] = kwargs
        return "query with uploaded alarm ALM-42"

    async def fake_normal_retrieval(**kwargs):
        captured["normal_kwargs"] = kwargs
        return "kb context", [{"file_id": 9, "filename": "kb.txt"}]

    async def fake_stream_answer(**kwargs):
        captured["answer_context"] = kwargs.get("context")
        yield "answer"

    monkeypatch.setattr(
        chat_api.chat_service,
        "rewrite_for_retrieval",
        fake_rewrite_for_retrieval,
    )
    monkeypatch.setattr(chat_api.rag, "retrieve_context", fake_normal_retrieval)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "payload": json.dumps(
                {
                    "session_id": chat.id,
                    "message": "請根據上傳的錯誤找相關文件",
                    "use_rag": True,
                    "deep_mode": False,
                }
            )
        },
        files={
            "files": (
                "alarm.txt",
                b"UltraFLEX pattern compiler alarm ALM-42 during vector load",
                "text/plain",
            )
        },
    )

    assert res.status_code == 200
    rewrite_kwargs = captured["rewrite_kwargs"]
    assert rewrite_kwargs["user_message"] == "請根據上傳的錯誤找相關文件"
    assert "Filename: alarm.txt" in rewrite_kwargs["attachment_retrieval_text"]
    assert "ALM-42" in rewrite_kwargs["attachment_retrieval_text"]
    rag_query = captured["normal_kwargs"]["query"]
    assert rag_query.startswith("query with uploaded alarm ALM-42")
    assert "Uploaded input data for RAG search:" in rag_query
    assert "Filename: alarm.txt" in rag_query
    assert "ALM-42" in rag_query
    assert captured["answer_context"].startswith("kb context")
    assert "User-uploaded files for this chat turn:" in captured["answer_context"]
    assert "ALM-42" in captured["answer_context"]


@pytest.mark.asyncio
async def test_chat_stream_empty_first_message_with_csv_attachment_uses_rag(
    http_client, db_session, alice: User, monkeypatch
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="New Chat")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    captured: dict[str, object] = {}

    async def fake_rewrite_for_retrieval(**kwargs):
        captured["rewrite_kwargs"] = kwargs
        return "UltraFLEX ALM-42 CSV failure"

    async def fake_normal_retrieval(**kwargs):
        captured["normal_kwargs"] = kwargs
        return "csv matched kb context", [{"file_id": 10, "filename": "alarm-bkm.csv"}]

    async def fake_stream_answer(**kwargs):
        captured["answer_context"] = kwargs.get("context")
        yield "answer"

    monkeypatch.setattr(
        chat_api.chat_service,
        "rewrite_for_retrieval",
        fake_rewrite_for_retrieval,
    )
    monkeypatch.setattr(chat_api.rag, "retrieve_context", fake_normal_retrieval)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        data={
            "payload": json.dumps(
                {
                    "session_id": chat.id,
                    "message": "",
                    "use_rag": True,
                    "deep_mode": False,
                }
            )
        },
        files={
            "files": (
                "alarms.csv",
                b"platform,alarm,detail\nUltraFLEX,ALM-42,vector load failure\n",
                "text/csv",
            )
        },
    )

    assert res.status_code == 200
    rewrite_kwargs = captured["rewrite_kwargs"]
    assert rewrite_kwargs["user_message"].startswith("請根據我附加的檔案內容做 RAG 搜尋")
    assert "Filename: alarms.csv" in rewrite_kwargs["attachment_retrieval_text"]
    assert "UltraFLEX" in rewrite_kwargs["attachment_retrieval_text"]
    assert "ALM-42" in rewrite_kwargs["attachment_retrieval_text"]
    rag_query = captured["normal_kwargs"]["query"]
    assert rag_query.startswith("UltraFLEX ALM-42 CSV failure")
    assert "Uploaded input data for RAG search:" in rag_query
    assert "Filename: alarms.csv" in rag_query
    assert "ALM-42" in rag_query
    assert "csv matched kb context" in captured["answer_context"]
    assert "alarms.csv" in captured["answer_context"]


@pytest.mark.asyncio
async def test_chat_stream_rejects_empty_message_without_attachment(
    http_client, db_session, alice: User
) -> None:
    chat = ChatSession(owner_user_id=alice.id, title="Empty")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    res = await http_client.post(
        "/chat/stream",
        headers=auth(alice),
        json={
            "session_id": chat.id,
            "message": "",
            "use_rag": True,
            "deep_mode": False,
        },
    )

    assert res.status_code == 422
    assert res.json()["detail"] == "message_or_attachment_required"
