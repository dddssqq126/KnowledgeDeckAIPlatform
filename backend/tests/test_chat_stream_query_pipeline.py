from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import base as db_base
from app.db.base import Base
from app.db.models import ChatSession, User
from app.features.chat.api import chat as chat_api
from app.main import create_app
from services.query_pipeline import QueryPipelineResult


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest_asyncio.fixture(autouse=True)
async def _patch_app_db(monkeypatch, tmp_path: Path) -> AsyncIterator[None]:
    from app.db import models  # noqa: F401

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'chat-stream.db'}",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_base, "_engine", engine, raising=False)
    monkeypatch.setattr(db_base, "_session_factory", factory, raising=False)
    try:
        yield
    finally:
        monkeypatch.setattr(db_base, "_engine", None, raising=False)
        monkeypatch.setattr(db_base, "_session_factory", None, raising=False)
        await engine.dispose()


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    async with db_base.async_session_factory()() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture()
async def http_client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture()
async def alice(db_session: AsyncSession) -> User:
    user = User(username="alice", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


async def make_chat(db_session: AsyncSession, user: User) -> ChatSession:
    chat = ChatSession(owner_user_id=user.id, title="Stream")
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


async def _post_stream(
    http_client: AsyncClient, user: User, chat: ChatSession, message: str
):
    return await http_client.post(
        "/chat/stream",
        headers=auth(user),
        json={
            "session_id": chat.id,
            "message": message,
            "use_rag": True,
            "deep_mode": False,
        },
    )


def _patch_rag(monkeypatch, *, context: str = "rag context") -> None:
    async def fake_rewrite_for_retrieval(**_kwargs):
        return "rewritten query"

    async def fake_retrieve_context(**_kwargs):
        return context, [{"file_id": 1, "filename": "source.txt"}]

    monkeypatch.setattr(
        chat_api.chat_service,
        "rewrite_for_retrieval",
        fake_rewrite_for_retrieval,
    )
    monkeypatch.setattr(chat_api.rag, "retrieve_context", fake_retrieve_context)


@pytest.mark.asyncio
async def test_chat_stream_general_rag_still_streams(
    http_client: AsyncClient, db_session: AsyncSession, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    captured: dict[str, Any] = {}
    _patch_rag(monkeypatch)

    def fake_run(**_kwargs):
        return QueryPipelineResult(
            decision="not_applicable",
            citations=[],
            debug={},
        )

    async def fake_stream_answer(**kwargs):
        captured["query_pipeline_result"] = kwargs.get("query_pipeline_result")
        captured["context"] = kwargs.get("context")
        yield "rag answer"

    monkeypatch.setattr(chat_api.query_pipeline, "run", fake_run)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await _post_stream(http_client, alice, chat, "What does the source say?")

    assert res.status_code == 200
    assert "rag answer" in res.text
    assert captured["context"] == "rag context"
    assert captured["query_pipeline_result"].decision == "not_applicable"


@pytest.mark.asyncio
async def test_chat_stream_bom_cost_appends_query_pipeline_context(
    http_client: AsyncClient, db_session: AsyncSession, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    captured: dict[str, Any] = {}
    _patch_rag(monkeypatch)

    def fake_run(**kwargs):
        captured["pipeline_kwargs"] = kwargs
        return QueryPipelineResult(
            decision="call_query_template",
            query_name="query_bom_cost",
            query_plan={"decision": "call_query_template"},
            query_result={"row_count": 1},
            result_verification={"ok": True},
            context_block="Query Template 名稱: query_bom_cost\nunit_price: 12.5",
            citations=[{"file_id": 2, "filename": "api-result"}],
            debug={},
        )

    async def fake_stream_answer(**kwargs):
        captured["context"] = kwargs.get("context")
        captured["query_pipeline_result"] = kwargs.get("query_pipeline_result")
        yield "final answer"

    monkeypatch.setattr(chat_api.query_pipeline, "run", fake_run)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await _post_stream(http_client, alice, chat, "請查 A123 在 P01 的 BOM cost")

    assert res.status_code == 200
    assert "final answer" in res.text
    assert captured["pipeline_kwargs"]["evidence_context"] == "rag context"
    assert "unit_price: 12.5" in captured["context"]
    assert captured["query_pipeline_result"].decision == "call_query_template"


@pytest.mark.asyncio
async def test_chat_stream_missing_project_id_streams_clarification_without_llm(
    http_client: AsyncClient, db_session: AsyncSession, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    _patch_rag(monkeypatch)

    def fake_run(**_kwargs):
        return QueryPipelineResult(
            decision="ask_clarification",
            query_name="query_bom_cost",
            query_plan={
                "decision": "ask_clarification",
                "missing_args": ["project_id"],
            },
            citations=[],
            user_visible_message="請補充 project_id。",
            debug={},
        )

    async def fail_stream_answer(**_kwargs):
        raise AssertionError("stream_answer should not be called")
        yield ""

    monkeypatch.setattr(chat_api.query_pipeline, "run", fake_run)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fail_stream_answer)

    res = await _post_stream(http_client, alice, chat, "請查 A123 的 BOM cost")

    assert res.status_code == 200
    assert "project_id" in res.text
    assert "event: done" in res.text


@pytest.mark.asyncio
async def test_chat_stream_query_pipeline_error_falls_back_to_rag(
    http_client: AsyncClient, db_session: AsyncSession, alice: User, monkeypatch
) -> None:
    chat = await make_chat(db_session, alice)
    captured: dict[str, Any] = {}
    _patch_rag(monkeypatch)

    def fake_run(**_kwargs):
        raise RuntimeError("pipeline unavailable")

    async def fake_stream_answer(**kwargs):
        captured["context"] = kwargs.get("context")
        yield "fallback answer"

    monkeypatch.setattr(chat_api.query_pipeline, "run", fake_run)
    monkeypatch.setattr(chat_api.chat_service, "stream_answer", fake_stream_answer)

    res = await _post_stream(http_client, alice, chat, "請查 A123 在 P01 的 BOM cost")

    assert res.status_code == 200
    assert "fallback answer" in res.text
    assert "API" in captured["context"]
