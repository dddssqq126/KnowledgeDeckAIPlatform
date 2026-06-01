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
