from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings

ENABLED = "enabled"
DISABLED = "disabled"
MCP_SSE_TRANSPORT = "mcp-sse"


class McpToolError(RuntimeError):
    """Raised when the external MCP server cannot complete a JSON-RPC request."""


class McpSseSession:
    def __init__(
        self,
        *,
        sse_url: str,
        timeout_sec: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.sse_url = sse_url
        self.timeout_sec = timeout_sec
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout_sec)
        self._stream_context: Any = None
        self._response: httpx.Response | None = None
        self._lines: Iterator[str] | None = None
        self._message_url: str | None = None
        self._next_id = 1

    def __enter__(self) -> "McpSseSession":
        self._stream_context = self._client.stream("GET", self.sse_url)
        self._response = self._stream_context.__enter__()
        self._response.raise_for_status()
        self._lines = self._response.iter_lines()
        event, data = self._read_event()
        if event != "endpoint" or not data:
            raise McpToolError("mcp_sse_endpoint_missing")
        self._message_url = urljoin(self.sse_url, data)
        self._initialize()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._stream_context is not None:
            self._stream_context.__exit__(exc_type, exc, tb)
        if self._owns_client:
            self._client.close()

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list")
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise McpToolError("mcp_tools_list_invalid")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    def _initialize(self) -> None:
        settings = get_settings()
        self._request(
            "initialize",
            {
                "protocolVersion": settings.mcp_protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "KnowledgeDeck",
                    "version": "0.1.0",
                },
            },
        )
        self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        while True:
            event, data = self._read_event()
            if event != "message" or not data:
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise McpToolError("mcp_message_not_json") from exc
            if payload.get("id") != request_id:
                continue
            if payload.get("error") is not None:
                raise McpToolError(str(payload["error"]))
            result = payload.get("result", {})
            if not isinstance(result, dict):
                raise McpToolError("mcp_result_invalid")
            return result

    def _post(self, payload: dict[str, Any]) -> None:
        if not self._message_url:
            raise McpToolError("mcp_message_endpoint_missing")
        response = self._client.post(self._message_url, json=payload)
        response.raise_for_status()

    def _read_event(self) -> tuple[str | None, str]:
        if self._lines is None:
            raise McpToolError("mcp_sse_not_connected")

        event: str | None = None
        data: list[str] = []
        for raw_line in self._lines:
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line == "":
                if event is not None or data:
                    return event, "\n".join(data)
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").lstrip())
        raise McpToolError("mcp_sse_closed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _contains_raw_sql(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key == "raw_sql" or _contains_raw_sql(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_raw_sql(item) for item in value)
    return False


def _schema_type(spec: Any) -> str:
    if isinstance(spec, dict):
        raw_type = spec.get("type") or "any"
        if isinstance(raw_type, list):
            return " | ".join(str(item) for item in raw_type)
        return str(raw_type)
    return str(spec or "any")


def _arg_spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, dict):
        payload: dict[str, Any] = {"type": _schema_type(spec)}
        if spec.get("description"):
            payload["description"] = str(spec["description"])
        if "default" in spec:
            payload["default"] = spec["default"]
        if "enum" in spec and isinstance(spec["enum"], list):
            payload["allowed_values"] = spec["enum"]
        return payload
    return {"type": _schema_type(spec)}


def _split_input_schema(input_schema: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_schema, dict):
        return {}, {}

    properties = input_schema.get("properties")
    if isinstance(properties, dict):
        required_names = {
            str(name) for name in input_schema.get("required", []) if name is not None
        }
        required: dict[str, Any] = {}
        optional: dict[str, Any] = {}
        for name, spec in properties.items():
            target = required if str(name) in required_names else optional
            target[str(name)] = _arg_spec(spec)
        return required, optional

    return {str(name): _arg_spec(spec) for name, spec in input_schema.items()}, {}


def _flat_output_schema(output_schema: Any) -> dict[str, str]:
    if not isinstance(output_schema, dict):
        return {}
    properties = output_schema.get("properties")
    if isinstance(properties, dict):
        return {str(name): _schema_type(spec) for name, spec in properties.items()}
    return {str(name): _schema_type(spec) for name, spec in output_schema.items()}


def tool_to_query_card(tool: dict[str, Any]) -> dict[str, Any]:
    input_schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    output_schema = tool.get("outputSchema") or tool.get("output_schema") or {}
    required_args, optional_args = _split_input_schema(input_schema)
    query_name = str(tool.get("queryName") or tool.get("query_name") or tool.get("name") or "")
    title = str(tool.get("title") or tool.get("name") or query_name)
    description = str(tool.get("description") or "")

    return {
        "query_name": query_name,
        "title": title,
        "auth_scope": str(tool.get("auth_scope") or "mcp-sse"),
        "description": description,
        "sql_type": str(tool.get("sql_type") or tool.get("sqlType") or "tool"),
        "when_to_use": tool.get("when_to_use")
        or tool.get("whenToUse")
        or ([description] if description else [f"Use {title}."]),
        "do_not_use_when": tool.get("do_not_use_when")
        or tool.get("doNotUseWhen")
        or ["The user asks an unrelated documentation question."],
        "required_args": required_args,
        "optional_args": optional_args,
        "output_schema": _flat_output_schema(output_schema),
        "empty_result_policy": tool.get("empty_result_policy")
        or tool.get("emptyResultPolicy")
        or {"answer": "No rows were returned by the tool."},
        "row_limit": int(tool.get("row_limit") or tool.get("rowLimit") or 500),
        "transport": MCP_SSE_TRANSPORT,
        "status": str(tool.get("status") or ENABLED),
        "handler_key": "",
        "template_id": str(tool.get("templateId") or tool.get("template_id") or f"{query_name}:mcp"),
        "timeout_sec": int(tool.get("timeoutSec") or tool.get("timeout_sec") or get_settings().mcp_sse_timeout_sec),
        "mcp_tool_name": str(tool.get("name") or query_name),
    }


def tools_to_query_cards(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = [tool_to_query_card(tool) for tool in tools]
    return [
        card
        for card in cards
        if card["query_name"] and str(card.get("status") or ENABLED) == ENABLED
    ]


def list_remote_tools(
    *,
    client_factory: Callable[[], McpSseSession] | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    factory = client_factory or (
        lambda: McpSseSession(
            sse_url=settings.mcp_sse_url,
            timeout_sec=settings.mcp_sse_timeout_sec,
        )
    )
    with factory() as client:
        return client.list_tools()


def list_remote_tool_cards(
    *,
    client_factory: Callable[[], McpSseSession] | None = None,
) -> list[dict[str, Any]]:
    return tools_to_query_cards(list_remote_tools(client_factory=client_factory))


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
        return [item if isinstance(item, dict) else {"value": item} for item in payload]
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
            "database": "mcp-sse",
            "template_id": template_id,
            "executed_at": _now().isoformat(),
        },
        "warnings": [],
        "error": error,
    }


def _payload_from_call_result(result: dict[str, Any]) -> Any:
    if "structuredContent" in result:
        return result["structuredContent"]
    if "structured_content" in result:
        return result["structured_content"]

    content = result.get("content")
    if isinstance(content, list):
        values: list[Any] = []
        for item in content:
            if not isinstance(item, dict):
                values.append(item)
                continue
            if "json" in item:
                values.append(item["json"])
                continue
            if item.get("type") == "text" and "text" in item:
                text = str(item["text"])
                try:
                    values.append(json.loads(text))
                except json.JSONDecodeError:
                    values.append({"text": text})
        if len(values) == 1:
            return values[0]
        return values

    return result


def _normalize_call_result(
    *,
    query_name: str,
    arguments: dict[str, Any],
    template_id: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("isError") is True:
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error=str(_payload_from_call_result(result)),
        )

    payload = _payload_from_call_result(result)
    if isinstance(payload, dict) and {"row_count", "data", "status"}.issubset(payload):
        normalized = dict(payload)
        normalized.setdefault("query_name", query_name)
        normalized.setdefault("input", arguments)
        normalized.setdefault("columns", _columns(_rows_from_json(normalized.get("data"))))
        normalized.setdefault("warnings", [])
        normalized.setdefault("error", None)
        normalized.setdefault(
            "source",
            {
                "database": "mcp-sse",
                "template_id": template_id,
                "executed_at": _now().isoformat(),
            },
        )
        return normalized

    rows = _rows_from_json(payload)
    return {
        "query_name": query_name,
        "status": "ok",
        "input": arguments,
        "row_count": len(rows),
        "columns": _columns(rows),
        "data": rows,
        "source": {
            "database": "mcp-sse",
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
    client_factory: Callable[[], McpSseSession] | None = None,
) -> dict[str, Any]:
    if _contains_raw_sql(arguments):
        raise ValueError("raw_sql is not allowed")
    tool = next((card for card in tool_cards if card.get("query_name") == query_name), None)
    if tool is None:
        raise KeyError(f"Tool not found for query_name: {query_name}")
    if str(tool.get("status", ENABLED)) != ENABLED:
        raise ValueError("Tool is disabled")

    settings = get_settings()
    factory = client_factory or (
        lambda: McpSseSession(
            sse_url=settings.mcp_sse_url,
            timeout_sec=float(tool.get("timeout_sec") or settings.mcp_sse_timeout_sec),
        )
    )
    template_id = str(tool.get("template_id") or "") or None
    try:
        with factory() as client:
            result = client.call_tool(
                name=str(tool.get("mcp_tool_name") or query_name),
                arguments=arguments,
            )
    except (httpx.HTTPError, McpToolError) as exc:
        return _error_result(
            query_name=query_name,
            arguments=arguments,
            template_id=template_id,
            error=f"mcp_error: {exc.__class__.__name__}",
        )

    return _normalize_call_result(
        query_name=query_name,
        arguments=arguments,
        template_id=template_id,
        result=result,
    )
