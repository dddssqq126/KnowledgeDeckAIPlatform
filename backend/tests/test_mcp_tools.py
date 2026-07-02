from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import base as db_base
from app.db.base import Base
from app.db.models import McpTool, User
from app.core.config import Settings
from app.features.mcp_tools.services import tool_service
from app.features.mcp_tools.services.tool_service import (
    execute_registered_tool,
    seed_builtin_tools,
)
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
    assert rows[0].method == "POST"
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
            "method": "POST",
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
    assert created["method"] == "POST"

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


def _http_tool_card(**overrides):
    payload = {
        "query_name": "query_http_status",
        "title": "HTTP Status",
        "description": "Looks up status from an HTTP tool.",
        "transport": "http",
        "method": "POST",
        "status": "enabled",
        "endpoint": "http://allowed.test/tools/status",
        "timeout_sec": 5,
        "template_id": "query_http_status:v1",
        "required_args": {"part_no": {"type": "string"}},
        "optional_args": {},
        "output_schema": {"status": "string"},
    }
    payload.update(overrides)
    return payload


def test_execute_enabled_http_tool_calls_allowed_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == "http://allowed.test/tools/status"
        assert request.read() == b'{"part_no":"A123"}'
        return httpx.Response(200, json={"status": "ok", "part_no": "A123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card()],
        http_client=client,
    )

    assert result["status"] == "ok"
    assert result["row_count"] == 1
    assert result["data"] == [{"status": "ok", "part_no": "A123"}]
    assert requests[0].method == "POST"


def test_execute_enabled_http_get_tool_sends_query_params(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://allowed.test/tools/status?part_no=A123"
        return httpx.Response(200, json=[{"status": "ok"}])

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card(method="GET")],
        http_client=client,
    )

    assert result["status"] == "ok"
    assert result["data"] == [{"status": "ok"}]


def test_execute_disabled_http_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="disabled"):
        execute_registered_tool(
            query_name="query_http_status",
            arguments={"part_no": "A123"},
            tool_cards=[_http_tool_card(status="disabled")],
        )


def test_execute_http_tool_rejects_disallowed_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card(endpoint="http://evil.test/tools/status")],
    )

    assert result["status"] == "error"
    assert result["error"] == "endpoint_not_allowed"


def test_execute_http_tool_reports_non_json_response(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json")
        )
    )

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card()],
        http_client=client,
    )

    assert result["status"] == "error"
    assert result["error"] == "response_not_json"


def test_execute_http_tool_reports_http_status(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json={"error": "down"})
        )
    )

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card()],
        http_client=client,
    )

    assert result["status"] == "error"
    assert result["error"] == "http_status_503"


def test_execute_http_tool_reports_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_service,
        "get_settings",
        lambda: Settings(mcp_tool_allowed_base_urls="http://allowed.test"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = execute_registered_tool(
        query_name="query_http_status",
        arguments={"part_no": "A123"},
        tool_cards=[_http_tool_card()],
        http_client=client,
    )

    assert result["status"] == "error"
    assert result["error"] == "http_timeout"
