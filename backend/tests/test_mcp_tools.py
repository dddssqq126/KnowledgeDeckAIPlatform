from __future__ import annotations

from typing import Any

import httpx
import json
import pytest

from app.features.mcp_tools.services import tool_service
from app.features.mcp_tools.services.tool_service import (
    execute_registered_tool,
    list_remote_tool_cards,
)


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


class FakeMcpSession:
    def __init__(
        self,
        *,
        tools: list[dict[str, Any]] | None = None,
        call_result: dict[str, Any] | None = None,
    ) -> None:
        self.tools = tools or []
        self.call_result = call_result or {}
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeMcpSession":
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def list_tools(self) -> list[dict[str, Any]]:
        return self.tools

    def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": arguments})
        return self.call_result


def test_list_remote_tool_cards_preserves_registration_shape() -> None:
    fake = FakeMcpSession(
        tools=[
            {
                "name": "query_bom_cost",
                "queryName": "query_bom_cost",
                "title": "BOM Cost",
                "description": "Fixed query template for BOM cost lookup.",
                "inputSchema": {"part_no": "string"},
                "outputSchema": {"unit_cost": "number"},
                "annotations": {"readOnlyHint": True},
                "templateId": "query_bom_cost:v1",
                "status": "enabled",
            }
        ]
    )

    cards = list_remote_tool_cards(client_factory=lambda: fake)

    assert cards == [
        {
            "query_name": "query_bom_cost",
            "title": "BOM Cost",
            "auth_scope": "mcp-sse",
            "description": "Fixed query template for BOM cost lookup.",
            "sql_type": "tool",
            "when_to_use": ["Fixed query template for BOM cost lookup."],
            "do_not_use_when": ["The user asks an unrelated documentation question."],
            "required_args": {"part_no": {"type": "string"}},
            "optional_args": {},
            "input_schema": {"part_no": "string"},
            "output_schema": {"unit_cost": "number"},
            "output_schema_raw": {"unit_cost": "number"},
            "annotations": {"readOnlyHint": True},
            "empty_result_policy": {"answer": "No rows were returned by the tool."},
            "row_limit": 500,
            "transport": "mcp-sse",
            "status": "enabled",
            "handler_key": "",
            "template_id": "query_bom_cost:v1",
            "timeout_sec": 30,
            "mcp_tool_name": "query_bom_cost",
        }
    ]


def test_list_remote_tool_cards_accepts_native_mcp_input_schema() -> None:
    fake = FakeMcpSession(
        tools=[
            {
                "name": "query_project_spec",
                "description": "Lookup project specification.",
                "inputSchema": {
                    "type": "object",
                    "required": ["project_id"],
                    "properties": {
                        "project_id": {
                            "type": "string",
                            "description": "Project id.",
                        },
                        "section": {"type": "string"},
                    },
                },
            }
        ]
    )

    cards = list_remote_tool_cards(client_factory=lambda: fake)

    assert cards[0]["query_name"] == "query_project_spec"
    assert cards[0]["required_args"] == {
        "project_id": {"type": "string", "description": "Project id."}
    }
    assert cards[0]["optional_args"] == {"section": {"type": "string"}}
    assert cards[0]["input_schema"]["required"] == ["project_id"]
    assert cards[0]["transport"] == "mcp-sse"


def test_list_remote_tool_cards_preserves_nested_schema_enum_default_and_annotations() -> None:
    fake = FakeMcpSession(
        tools=[
            {
                "name": "query_complex_status",
                "description": "Lookup status with filters.",
                "inputSchema": {
                    "type": "object",
                    "required": ["part_no", "filters"],
                    "properties": {
                        "part_no": {"type": "string", "description": "Part number."},
                        "filters": {
                            "type": "object",
                            "required": ["region"],
                            "properties": {
                                "region": {"type": "string", "enum": ["us", "tw"]},
                                "include_history": {
                                    "type": "boolean",
                                    "default": False,
                                },
                            },
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
                "annotations": {"readOnlyHint": True, "openWorldHint": False},
            }
        ]
    )

    card = list_remote_tool_cards(client_factory=lambda: fake)[0]

    assert card["required_args"]["filters"]["properties"]["region"]["enum"] == [
        "us",
        "tw",
    ]
    assert card["required_args"]["filters"]["properties"]["include_history"][
        "default"
    ] is False
    assert card["optional_args"]["tags"]["items"] == {"type": "string"}
    assert card["input_schema"]["properties"]["filters"]["type"] == "object"
    assert card["output_schema_raw"]["properties"]["status"]["type"] == "string"
    assert card["annotations"] == {"readOnlyHint": True, "openWorldHint": False}


def test_execute_registered_tool_calls_selected_mcp_tool() -> None:
    fake = FakeMcpSession(
        call_result={
            "structuredContent": {
                "data": [{"part_no": "A123", "unit_cost": 12.5}],
            }
        }
    )

    result = execute_registered_tool(
        query_name="query_bom_cost",
        arguments={"part_no": "A123"},
        tool_cards=[
            {
                "query_name": "query_bom_cost",
                "title": "BOM Cost",
                "transport": "mcp-sse",
                "status": "enabled",
                "template_id": "query_bom_cost:v1",
                "mcp_tool_name": "query_bom_cost",
            }
        ],
        client_factory=lambda: fake,
    )

    assert fake.calls == [{"name": "query_bom_cost", "arguments": {"part_no": "A123"}}]
    assert result["status"] == "ok"
    assert result["row_count"] == 1
    assert result["columns"] == ["part_no", "unit_cost"]
    assert result["data"] == [{"part_no": "A123", "unit_cost": 12.5}]
    assert result["source"]["database"] == "mcp-sse"


def test_execute_registered_tool_uses_discovered_mcp_tool_name() -> None:
    fake = FakeMcpSession(call_result={"structuredContent": {"status": "ok"}})

    execute_registered_tool(
        query_name="query_status",
        arguments={"part_no": "A123"},
        tool_cards=[
            {
                "query_name": "query_status",
                "transport": "mcp-sse",
                "status": "enabled",
                "mcp_tool_name": "status.lookup",
            }
        ],
        client_factory=lambda: fake,
    )

    assert fake.calls == [{"name": "status.lookup", "arguments": {"part_no": "A123"}}]


def test_execute_registered_tool_preserves_query_result_payload() -> None:
    fake = FakeMcpSession(
        call_result={
            "structuredContent": {
                "query_name": "query_bom_cost",
                "status": "ok",
                "input": {"part_no": "A123"},
                "row_count": 1,
                "columns": ["part_no"],
                "data": [{"part_no": "A123"}],
                "source": {"database": "business", "template_id": "query_bom_cost:v1"},
                "warnings": [],
                "error": None,
            }
        }
    )

    result = execute_registered_tool(
        query_name="query_bom_cost",
        arguments={"part_no": "A123"},
        tool_cards=[
            {
                "query_name": "query_bom_cost",
                "status": "enabled",
                "mcp_tool_name": "query_bom_cost",
            }
        ],
        client_factory=lambda: fake,
    )

    assert result["source"]["database"] == "business"
    assert result["data"] == [{"part_no": "A123"}]


def test_execute_disabled_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="disabled"):
        execute_registered_tool(
            query_name="query_bom_cost",
            arguments={"part_no": "A123"},
            tool_cards=[{"query_name": "query_bom_cost", "status": "disabled"}],
        )


def test_execute_rejects_raw_sql_argument() -> None:
    with pytest.raises(ValueError, match="raw_sql"):
        execute_registered_tool(
            query_name="query_bom_cost",
            arguments={"nested": {"raw_sql": "SELECT * FROM bom"}},
            tool_cards=[{"query_name": "query_bom_cost", "status": "enabled"}],
        )


def test_execute_reports_mcp_client_error() -> None:
    class FailingSession(FakeMcpSession):
        def call_tool(self, *, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            raise tool_service.McpToolError("server down")

    result = execute_registered_tool(
        query_name="query_bom_cost",
        arguments={"part_no": "A123"},
        tool_cards=[
            {
                "query_name": "query_bom_cost",
                "status": "enabled",
                "template_id": "query_bom_cost:v1",
            }
        ],
        client_factory=lambda: FailingSession(),
    )

    assert result["status"] == "error"
    assert result["error"] == "mcp_error: McpToolError"


def test_mcp_http_tool_client_posts_to_fixed_tool_endpoints() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "url": str(request.url),
                "session": request.headers.get("Mcp-Session-Id"),
                "body": json.loads(request.content.decode()),
            }
        )
        if str(request.url).endswith("/tools/list"):
            return httpx.Response(200, json={"tools": [{"name": "query_status"}]})
        return httpx.Response(200, json={"structuredContent": {"status": "ok"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with tool_service.McpHttpToolClient(
        sse_url="http://10.150.186.9/sse",
        session_id="37880f8a4f",
        timeout_sec=30,
        client=client,
    ) as mcp_client:
        assert mcp_client.list_tools() == [{"name": "query_status"}]
        assert mcp_client.call_tool(
            name="query_status", arguments={"query": "keep existing shape"}
        ) == {"structuredContent": {"status": "ok"}}

    assert requests == [
        {
            "url": "http://10.150.186.9/sse/tools/list",
            "session": "37880f8a4f",
            "body": {"session_id": "37880f8a4f"},
        },
        {
            "url": "http://10.150.186.9/sse/tools/call",
            "session": "37880f8a4f",
            "body": {
                "name": "query_status",
                "arguments": {"query": "keep existing shape"},
                "session_id": "37880f8a4f",
            },
        },
    ]
