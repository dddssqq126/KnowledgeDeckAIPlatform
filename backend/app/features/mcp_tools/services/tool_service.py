from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
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
ALLOWED_HTTP_METHODS = {"GET", "POST"}
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
    "method": "POST",
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
        "method": "POST",
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
    method: str,
    timeout_sec: int,
    status: str = ENABLED,
) -> None:
    if not name.strip() or not query_name.strip() or not server_name.strip():
        raise ToolRegistrationError("required_fields_missing")
    if transport not in ALLOWED_TRANSPORTS:
        raise ToolRegistrationError("unsupported_transport")
    if method.upper() not in ALLOWED_HTTP_METHODS:
        raise ToolRegistrationError("unsupported_method")
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
        existing.method = payload["method"]
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
    method: str,
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
    method = method.strip().upper() or "POST"
    endpoint = endpoint.strip()
    _validate_tool_payload(
        name=name,
        query_name=query_name,
        server_name=server_name,
        transport=transport,
        method=method,
        timeout_sec=timeout_sec,
    )
    if transport == "http" and not endpoint:
        raise ToolRegistrationError("endpoint_required")
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
        method=method,
        endpoint=endpoint,
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
        "method": tool.method,
        "status": tool.status,
        "handler_key": tool.handler_key,
        "template_id": tool.template_id,
        "timeout_sec": tool.timeout_sec,
    }


def tools_to_query_cards(tools: list[McpTool]) -> list[dict[str, Any]]:
    return [tool_to_query_card(tool) for tool in tools if tool.status == ENABLED]


def _url_allowed(endpoint: str, allowed_base_urls: list[str]) -> bool:
    target = urlparse(endpoint)
    if target.scheme not in {"http", "https"} or not target.netloc:
        return False

    for base in allowed_base_urls:
        parsed = urlparse(base)
        if parsed.scheme != target.scheme or parsed.hostname != target.hostname:
            continue
        if parsed.port is not None and parsed.port != target.port:
            continue
        base_path = parsed.path.rstrip("/")
        if base_path and not target.path.startswith(f"{base_path}/") and target.path != base_path:
            continue
        return True
    return False


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for name in row:
            if name not in seen:
                seen.add(name)
                columns.append(name)
    return columns


def _rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            rows.append(item if isinstance(item, dict) else {"value": item})
        return rows
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"value": item} for item in data]
        return [payload]
    return [{"value": payload}]


def _error_result(
    *,
    query_name: str,
    arguments: dict[str, Any],
    template_id: str | None,
    error: str,
) -> dict[str, Any]:
    return {
        "query_name": query_name,
        "status": "error",
        "input": arguments,
        "row_count": 0,
        "columns": [],
        "data": [],
        "source": {
            "database": "http",
            "template_id": template_id,
            "executed_at": _now().isoformat(),
        },
        "warnings": [],
        "error": error,
    }


def _execute_http_tool(
    *,
    tool: dict[str, Any],
    query_name: str,
    arguments: dict[str, Any],
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    endpoint = str(tool.get("endpoint") or "")
    template_id = str(tool.get("template_id") or "") or None
    allowed = get_settings().mcp_tool_allowed_base_urls_list
    if not _url_allowed(endpoint, allowed):
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error="endpoint_not_allowed",
        )

    method = str(tool.get("method") or "POST").upper()
    timeout_sec = int(tool.get("timeout_sec") or 10)
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout_sec)
    try:
        if method == "GET":
            response = client.get(endpoint, params=arguments)
        elif method == "POST":
            response = client.post(endpoint, json=arguments)
        else:
            return _error_result(
                query_name=query_name,
                arguments=arguments,
                template_id=template_id,
                error=f"unsupported_method: {method}",
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return _error_result(
                query_name=query_name,
                arguments=arguments,
                template_id=template_id,
                error="response_not_json",
            )
    except httpx.TimeoutException:
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error="http_timeout",
        )
    except httpx.HTTPStatusError as exc:
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error=f"http_status_{exc.response.status_code}",
        )
    except httpx.HTTPError as exc:
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error=f"http_error: {exc.__class__.__name__}",
        )
    finally:
        if owns_client:
            client.close()

    rows = _rows_from_json(payload)
    return {
        "query_name": query_name,
        "status": "ok",
        "input": arguments,
        "row_count": len(rows),
        "columns": _columns(rows),
        "data": rows,
        "source": {
            "database": "http",
            "template_id": template_id,
            "executed_at": _now().isoformat(),
        },
        "warnings": [],
        "error": None,
    }


def execute_registered_tool(
    *,
    query_name: str,
    arguments: dict[str, Any],
    tool_cards: list[dict[str, Any]],
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    if "raw_sql" in arguments:
        raise ValueError("raw_sql is not allowed")
    tool = next((card for card in tool_cards if card.get("query_name") == query_name), None)
    if tool is None:
        raise KeyError(f"Tool not found for query_name: {query_name}")
    if str(tool.get("status", ENABLED)) != ENABLED:
        raise ValueError("Tool is disabled")

    transport = str(tool.get("transport") or IN_PROCESS)
    if transport == "http":
        return _execute_http_tool(
            tool=tool,
            query_name=query_name,
            arguments=arguments,
            http_client=http_client,
        )
    if transport != IN_PROCESS:
        raise ValueError("Only in-process and HTTP tools are executable in this version")

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
