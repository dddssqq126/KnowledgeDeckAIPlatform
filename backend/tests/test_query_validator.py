from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agents.query_validator import validate_query_plan
from sql_templates.registry import SQL_TEMPLATE_REGISTRY


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


class BomCostArgs(BaseModel):
    part_no: str
    project_id: str


def _candidate_query_cards() -> list[dict[str, Any]]:
    return [
        {
            "query_name": "query_bom_cost",
            "title": "BOM Cost",
            "required_args": {
                "part_no": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "template_id": "query_bom_cost:project-v1",
            "sql": (
                "SELECT part_no, project_id FROM bom_items "
                "WHERE part_no = :part_no AND project_id = :project_id"
            ),
        }
    ]


def _schema_map() -> dict[str, type[BaseModel]]:
    return {"query_bom_cost": BomCostArgs}


def _plan(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "decision": "call_query_template",
        "query_name": "query_bom_cost",
        "arguments": {"part_no": "A123", "project_id": "P01"},
        "missing_args": [],
        "confidence": 0.9,
        "reason": "BOM cost query.",
        "required_evidence_ids": ["doc-1"],
    }
    payload.update(overrides)
    return payload


def test_validate_query_plan_allows_valid_query_bom_cost() -> None:
    result = validate_query_plan(
        query_plan=_plan(),
        candidate_query_cards=_candidate_query_cards(),
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map=_schema_map(),
    )

    assert result.ok is True
    assert result.action == "execute"
    assert result.query_name == "query_bom_cost"
    assert result.normalized_arguments == {"part_no": "A123", "project_id": "P01"}
    assert all(result.checks.values())


def test_validate_query_plan_rejects_query_name_missing_from_registry() -> None:
    result = validate_query_plan(
        query_plan=_plan(query_name="query_missing"),
        candidate_query_cards=[
            {
                "query_name": "query_missing",
                "title": "Missing",
                "required_args": {"part_no": {"type": "string"}},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map={"query_missing": BomCostArgs},
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.checks["query_exists_in_registry"] is False
    assert result.checks["sql_template_valid"] is False


def test_validate_query_plan_rejects_query_name_missing_from_candidate_cards() -> None:
    result = validate_query_plan(
        query_plan=_plan(),
        candidate_query_cards=[
            {
                "query_name": "query_inventory",
                "title": "Inventory",
                "required_args": {"part_no": {"type": "string"}},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map=_schema_map(),
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.checks["query_exists_in_candidate_cards"] is False


def test_validate_query_plan_asks_clarification_when_project_id_missing() -> None:
    result = validate_query_plan(
        query_plan=_plan(arguments={"part_no": "A123"}, missing_args=["project_id"]),
        candidate_query_cards=_candidate_query_cards(),
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map=_schema_map(),
    )

    assert result.ok is False
    assert result.action == "ask_clarification"
    assert result.checks["required_args_complete"] is False
    assert result.checks["pydantic_schema_valid"] is False


def test_validate_query_plan_rejects_raw_sql_in_arguments() -> None:
    result = validate_query_plan(
        query_plan=_plan(
            arguments={
                "part_no": "A123",
                "project_id": "P01",
                "raw_sql": "SELECT * FROM bom_items",
            }
        ),
        candidate_query_cards=_candidate_query_cards(),
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map=_schema_map(),
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.checks["raw_sql_absent"] is False


def test_validate_query_plan_rejects_low_confidence() -> None:
    result = validate_query_plan(
        query_plan=_plan(confidence=0.69),
        candidate_query_cards=_candidate_query_cards(),
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
        query_arg_schema_map=_schema_map(),
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.checks["confidence_passed"] is False


def test_validate_query_plan_allows_mcp_sse_tool_without_handler_or_sql_template() -> None:
    result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"part_no": "A123"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=[
            {
                "query_name": "query_mcp_status",
                "title": "MCP Status",
                "transport": "mcp-sse",
                "required_args": {"part_no": {"type": "string"}},
                "optional_args": {},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )

    assert result.ok is True
    assert result.action == "execute"
    assert result.checks["query_exists_in_registry"] is True
    assert result.checks["sql_template_valid"] is True
    assert result.checks["handler_valid"] is True
    assert result.normalized_arguments == {"part_no": "A123"}


def test_validate_query_plan_rejects_disabled_mcp_tool() -> None:
    result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"part_no": "A123"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=[
            {
                "query_name": "query_mcp_status",
                "title": "MCP Status",
                "transport": "mcp-sse",
                "status": "disabled",
                "required_args": {"part_no": {"type": "string"}},
                "optional_args": {},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.checks["tool_enabled"] is False


def test_validate_query_plan_rejects_unknown_argument_for_mcp_tool() -> None:
    result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"part_no": "A123", "raw_status": "all"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=[
            {
                "query_name": "query_mcp_status",
                "title": "MCP Status",
                "transport": "mcp-sse",
                "required_args": {"part_no": {"type": "string"}},
                "optional_args": {},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.error is not None
    assert "unknown argument" in result.error


def test_validate_query_plan_rejects_wrong_primitive_type_for_mcp_tool() -> None:
    result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"part_no": 123},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=[
            {
                "query_name": "query_mcp_status",
                "title": "MCP Status",
                "transport": "mcp-sse",
                "required_args": {"part_no": {"type": "string"}},
                "optional_args": {},
            }
        ],
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )

    assert result.ok is False
    assert result.action == "reject"
    assert result.error is not None
    assert "argument part_no must be string" in result.error


def test_validate_query_plan_validates_nested_schema_and_enum_for_mcp_tool() -> None:
    candidate_cards = [
        {
            "query_name": "query_mcp_status",
            "title": "MCP Status",
            "transport": "mcp-sse",
            "required_args": {
                "filters": {
                    "type": "object",
                    "required": ["region"],
                    "properties": {
                        "region": {"type": "string", "enum": ["tw", "us"]},
                    },
                }
            },
            "optional_args": {
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
    ]

    ok_result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"filters": {"region": "tw"}, "tags": ["ate"]},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=candidate_cards,
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )
    bad_result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_mcp_status",
            "arguments": {"filters": {"region": "eu"}},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "MCP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=candidate_cards,
        sql_template_registry=SQL_TEMPLATE_REGISTRY,
    )

    assert ok_result.ok is True
    assert bad_result.ok is False
    assert bad_result.action == "reject"
