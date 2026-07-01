from __future__ import annotations

import pytest

from agents.result_verifier import verify_query_result


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def _query_card() -> dict:
    return {
        "query_name": "query_bom_cost",
        "row_limit": 2,
        "output_schema": {
            "part_no": "string",
            "component_part_no": "string",
            "quantity": "number",
            "unit_price": "number",
        },
        "empty_result_policy": {
            "answer": "No BOM cost rows were found.",
        },
    }


def test_verify_query_result_accepts_one_valid_row() -> None:
    result = verify_query_result(
        query_result={
            "status": "success",
            "row_count": 1,
            "data": [
                {
                    "part_no": "A123",
                    "component_part_no": "C001",
                    "quantity": 2,
                    "unit_price": 10.5,
                }
            ],
        },
        query_card=_query_card(),
    )

    assert result.ok is True
    assert result.empty_result is False
    assert result.required_columns_exist is True
    assert result.output_schema_valid is True
    assert result.error is None


def test_verify_query_result_accepts_empty_result_with_policy_answer() -> None:
    result = verify_query_result(
        query_result={"status": "success", "row_count": 0, "data": []},
        query_card=_query_card(),
    )

    assert result.ok is True
    assert result.empty_result is True
    assert result.deterministic_summary == {
        "empty_result_answer": "No BOM cost rows were found."
    }


def test_verify_query_result_flags_missing_unit_price() -> None:
    result = verify_query_result(
        query_result={
            "status": "success",
            "row_count": 1,
            "data": [
                {
                    "part_no": "A123",
                    "component_part_no": "C001",
                    "quantity": 2,
                }
            ],
        },
        query_card=_query_card(),
    )

    assert result.ok is False
    assert result.required_columns_exist is False
    assert result.output_schema_valid is False
    assert result.error == "query_result does not match output_schema"


def test_verify_query_result_flags_over_limit_and_summarizes() -> None:
    result = verify_query_result(
        query_result={
            "status": "success",
            "row_count": 3,
            "data": [
                {
                    "part_no": "A123",
                    "component_part_no": "C001",
                    "quantity": 1,
                    "unit_price": 10,
                },
                {
                    "part_no": "A123",
                    "component_part_no": "C002",
                    "quantity": 2,
                    "unit_price": 20,
                },
                {
                    "part_no": "A123",
                    "component_part_no": "C003",
                    "quantity": 3,
                    "unit_price": 30,
                },
            ],
        },
        query_card=_query_card(),
    )

    assert result.ok is True
    assert result.over_limit is True
    assert result.deterministic_summary is not None
    assert result.deterministic_summary["row_count"] == 3
    assert result.deterministic_summary["preview_count"] == 2
    assert result.warnings == ["row_count exceeds row_limit=2"]


def test_verify_query_result_rejects_error_status() -> None:
    result = verify_query_result(
        query_result={
            "status": "error",
            "row_count": 0,
            "data": [],
            "error": "database timeout",
        },
        query_card=_query_card(),
    )

    assert result.ok is False
    assert result.status == "error"
    assert result.error == "database timeout"
