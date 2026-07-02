from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import McpTool
from mcp_servers.business_query_server import query_bom_cost

ENABLED = "enabled"
DISABLED = "disabled"
IN_PROCESS = "in-process"
ALLOWED_STATUSES = {ENABLED, DISABLED}
ALLOWED_TRANSPORTS = {IN_PROCESS, "stdio", "http"}
EXECUTABLE_HANDLER_KEYS = {"llm_info", "query_bom_cost"}

SYSTEM_LLM_INFO_TOOL: dict[str, Any] = {
    "name": "System LLM Info",
    "query_name": "query_llm_info",
    "server_name": "system_info_server",
    "description": (
        "Returns the configured chat LLM label and model id for this "
        "KnowledgeDeck system. Use when the user asks what LLM/model this "
        "system uses, what model it is based on, or asks for system LLM info."
    ),
    "transport": IN_PROCESS,
    "endpoint": "app.shared.api.llm_info",
    "template_id": "query_llm_info:v1",
    "timeout_sec": 5,
    "status": ENABLED,
    "input_schema": {},
    "output_schema": {
        "label": "string",
        "model_id": "string",
    },
    "built_in": True,
    "handler_key": "llm_info",
}

BUILT_IN_TOOLS: tuple[dict[str, Any], ...] = (
    SYSTEM_LLM_INFO_TOOL,
    {
        "name": "BOM Cost",
        "query_name": "query_bom_cost",
        "server_name": "business_query_server",
        "description": "Fixed query template for BOM cost lookup by part number.",
        "transport": IN_PROCESS,
        "endpoint": "backend/mcp_servers/business_query_server.py",
        "template_id": "query_bom_cost:v1",
        "timeout_sec": 10,
        "status": ENABLED,
        "input_schema": {
            "part_no": "string",
        },
        "output_schema": {
            "part_no": "string",
            "component_part_no": "string",
            "quantity": "number",
            "unit_cost": "number",
            "extended_cost": "number",
        },
        "built_in": True,
        "handler_key": "query_bom_cost",
    },
)


class ToolRegistrationError(ValueError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, str]:
    if not schema:
        return {}
    return {str(key): str(value) for key, value in schema.items()}


def _validate_tool_payload(
    *,
    name: str,
    query_name: str,
    server_name: str,
    transport: str,
    timeout_sec: int,
    status: str = ENABLED,
) -> None:
    if not name.strip() or not query_name.strip() or not server_name.strip():
        raise ToolRegistrationError("required_fields_missing")
    if transport not in ALLOWED_TRANSPORTS:
        raise ToolRegistrationError("unsupported_transport")
    if status not in ALLOWED_STATUSES:
        raise ToolRegistrationError("unsupported_status")
    if timeout_sec <= 0:
        raise ToolRegistrationError("timeout_must_be_positive")


async def seed_builtin_tools(session: AsyncSession) -> None:
    for payload in BUILT_IN_TOOLS:
        existing = await session.scalar(
            select(McpTool).where(
                McpTool.owner_user_id.is_(None),
                McpTool.query_name == payload["query_name"],
            )
        )
        if existing is None:
            session.add(McpTool(owner_user_id=None, **payload))
            continue

        # Keep built-in definitions fresh while preserving operator status changes.
        existing.name = payload["name"]
        existing.server_name = payload["server_name"]
        existing.description = payload["description"]
        existing.transport = payload["transport"]
        existing.endpoint = payload["endpoint"]
        existing.template_id = payload["template_id"]
        existing.timeout_sec = payload["timeout_sec"]
        existing.input_schema = dict(payload["input_schema"])
        existing.output_schema = dict(payload["output_schema"])
        existing.built_in = True
        existing.handler_key = payload["handler_key"]
        existing.updated_at = _now()


async def list_visible_tools(
    session: AsyncSession,
    *,
    owner_user_id: int,
    enabled_only: bool = False,
) -> list[McpTool]:
    stmt = select(McpTool).where(
        or_(McpTool.owner_user_id.is_(None), McpTool.owner_user_id == owner_user_id)
    )
    if enabled_only:
        stmt = stmt.where(McpTool.status == ENABLED)
    rows = await session.scalars(stmt.order_by(McpTool.built_in.desc(), McpTool.name.asc()))
    return list(rows.all())


async def get_owned_or_global_tool(
    session: AsyncSession,
    *,
    owner_user_id: int,
    tool_id: int,
) -> McpTool | None:
    return await session.scalar(
        select(McpTool).where(
            McpTool.id == tool_id,
            or_(McpTool.owner_user_id.is_(None), McpTool.owner_user_id == owner_user_id),
        )
    )


async def create_custom_tool(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    query_name: str,
    server_name: str,
    description: str,
    transport: str,
    endpoint: str,
    template_id: str,
    timeout_sec: int,
    input_schema: dict[str, Any] | None,
    output_schema: dict[str, Any] | None,
) -> McpTool:
    name = name.strip()
    query_name = query_name.strip()
    server_name = server_name.strip()
    transport = transport.strip() or IN_PROCESS
    _validate_tool_payload(
        name=name,
        query_name=query_name,
        server_name=server_name,
        transport=transport,
        timeout_sec=timeout_sec,
    )
    duplicate = await session.scalar(
        select(McpTool).where(
            McpTool.query_name == query_name,
            or_(McpTool.owner_user_id.is_(None), McpTool.owner_user_id == owner_user_id),
        )
    )
    if duplicate is not None:
        raise ToolRegistrationError("duplicate_query_name")

    tool = McpTool(
        owner_user_id=owner_user_id,
        name=name,
        query_name=query_name,
        server_name=server_name,
        description=description.strip(),
        transport=transport,
        endpoint=endpoint.strip(),
        template_id=template_id.strip(),
        timeout_sec=timeout_sec,
        status=ENABLED,
        input_schema=_normalize_schema(input_schema),
        output_schema=_normalize_schema(output_schema),
        built_in=False,
        handler_key="",
    )
    session.add(tool)
    await session.flush()
    return tool


async def set_tool_status(
    session: AsyncSession,
    *,
    tool: McpTool,
    status: str,
) -> McpTool:
    if status not in ALLOWED_STATUSES:
        raise ToolRegistrationError("unsupported_status")
    tool.status = status
    tool.updated_at = _now()
    await session.flush()
    return tool


def tool_to_query_card(tool: McpTool) -> dict[str, Any]:
    required_args = {
        name: {"type": type_name, "description": f"{name} argument"}
        for name, type_name in (tool.input_schema or {}).items()
    }
    return {
        "query_name": tool.query_name,
        "title": tool.name,
        "auth_scope": "global" if tool.owner_user_id is None else "owner",
        "description": tool.description,
        "sql_type": "tool",
        "when_to_use": [tool.description],
        "do_not_use_when": ["The user asks an unrelated documentation question."],
        "required_args": required_args,
        "optional_args": {},
        "output_schema": tool.output_schema or {},
        "empty_result_policy": {"answer": "No rows were returned by the tool."},
        "row_limit": 1 if tool.handler_key == "llm_info" else 500,
        "transport": tool.transport,
        "handler_key": tool.handler_key,
        "template_id": tool.template_id,
        "timeout_sec": tool.timeout_sec,
    }


def tools_to_query_cards(tools: list[McpTool]) -> list[dict[str, Any]]:
    return [tool_to_query_card(tool) for tool in tools if tool.status == ENABLED]


def execute_registered_tool(
    *,
    query_name: str,
    arguments: dict[str, Any],
    tool_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    if "raw_sql" in arguments:
        raise ValueError("raw_sql is not allowed")
    tool = next((card for card in tool_cards if card.get("query_name") == query_name), None)
    if tool is None:
        raise KeyError(f"Tool not found for query_name: {query_name}")
    if tool.get("transport") != IN_PROCESS:
        raise ValueError("Only in-process tools are executable in this version")

    handler_key = str(tool.get("handler_key") or "")
    if handler_key not in EXECUTABLE_HANDLER_KEYS:
        raise ValueError(f"Unsupported tool handler: {handler_key or 'none'}")

    if handler_key == "llm_info":
        settings = get_settings()
        row = {"label": settings.llm_model_label, "model_id": settings.llm_model}
        return {
            "query_name": query_name,
            "status": "ok",
            "input": arguments,
            "row_count": 1,
            "columns": list(row),
            "data": [row],
            "source": {
                "database": "settings",
                "template_id": tool.get("template_id") or "query_llm_info:v1",
                "executed_at": _now().isoformat(),
            },
            "warnings": [],
            "error": None,
        }

    if handler_key == "query_bom_cost":
        return query_bom_cost(arguments).model_dump()

    raise ValueError(f"Unsupported tool handler: {handler_key}")
