from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import base as db_base
from app.db.base import Base
from app.db.models import McpTool, User
from app.features.mcp_tools.services.tool_service import seed_builtin_tools
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest_asyncio.fixture(autouse=True)
async def _patch_app_db(monkeypatch, tmp_path: Path) -> AsyncIterator[None]:
    from app.db import models  # noqa: F401

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'mcp-tools.db'}",
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
async def test_seed_builtin_llm_info_is_idempotent(db_session) -> None:
    await seed_builtin_tools(db_session)
    await seed_builtin_tools(db_session)
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(McpTool).where(McpTool.query_name == "query_llm_info")
        )
    ).all()

    assert len(rows) == 1
    assert rows[0].built_in is True
    assert rows[0].handler_key == "llm_info"
    assert rows[0].output_schema == {"label": "string", "model_id": "string"}


@pytest.mark.asyncio
async def test_mcp_tools_api_lists_seeded_builtin(http_client, db_session, alice) -> None:
    await seed_builtin_tools(db_session)
    await db_session.commit()

    res = await http_client.get("/mcp-tools", headers=auth(alice))

    assert res.status_code == 200
    body = res.json()
    names = {tool["queryName"] for tool in body}
    assert "query_llm_info" in names


@pytest.mark.asyncio
async def test_mcp_tools_api_create_update_delete_custom_tool(
    http_client, db_session, alice
) -> None:
    await seed_builtin_tools(db_session)
    await db_session.commit()

    create = await http_client.post(
        "/mcp-tools",
        headers=auth(alice),
        json={
            "name": "Local Status",
            "queryName": "query_local_status",
            "serverName": "business_query_server",
            "description": "Checks local status.",
            "transport": "in-process",
            "endpoint": "backend/mcp_servers/business_query_server.py",
            "templateId": "",
            "timeoutSec": 10,
            "inputSchema": {"part_no": "string"},
            "outputSchema": {"status": "string"},
        },
    )
    assert create.status_code == 201
    created = create.json()
    assert created["builtIn"] is False
    assert created["queryName"] == "query_local_status"

    duplicate = await http_client.post(
        "/mcp-tools",
        headers=auth(alice),
        json={
            "name": "Duplicate",
            "queryName": "query_local_status",
            "serverName": "business_query_server",
        },
    )
    assert duplicate.status_code == 409

    disabled = await http_client.patch(
        f"/mcp-tools/{created['id']}/status",
        headers=auth(alice),
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    deleted = await http_client.delete(
        f"/mcp-tools/{created['id']}",
        headers=auth(alice),
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_mcp_tools_api_rejects_builtin_delete(http_client, db_session, alice) -> None:
    await seed_builtin_tools(db_session)
    await db_session.commit()
    tool = await db_session.scalar(
        select(McpTool).where(McpTool.query_name == "query_llm_info")
    )
    assert tool is not None

    res = await http_client.delete(f"/mcp-tools/{tool.id}", headers=auth(alice))

    assert res.status_code == 409
    assert res.json() == {"detail": "built_in_tool"}
