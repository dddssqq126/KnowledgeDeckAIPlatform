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


def test_validate_query_plan_allows_http_tool_without_handler_or_sql_template() -> None:
    result = validate_query_plan(
        query_plan={
            "decision": "call_query_template",
            "query_name": "query_http_status",
            "arguments": {"part_no": "A123"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "HTTP tool can answer this.",
            "required_evidence_ids": [],
        },
        candidate_query_cards=[
            {
                "query_name": "query_http_status",
                "title": "HTTP Status",
                "transport": "http",
                "method": "POST",
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
