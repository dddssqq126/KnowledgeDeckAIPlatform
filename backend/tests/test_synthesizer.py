from __future__ import annotations

import pytest

from agents.synthesizer import synthesize_answer


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def _plan(**overrides):
    payload = {
        "decision": "call_query_template",
        "query_name": "query_bom_cost",
        "arguments": {"part_no": "A123", "project_id": "P01"},
        "missing_args": [],
        "confidence": 0.9,
        "reason": "Need database result.",
        "required_evidence_ids": ["doc-1"],
    }
    payload.update(overrides)
    return payload


def _result(**overrides):
    payload = {
        "query_name": "query_bom_cost",
        "status": "success",
        "input": {"part_no": "A123", "project_id": "P01"},
        "row_count": 1,
        "columns": ["unit_price", "currency", "vendor", "updated_at"],
        "data": [
            {
                "unit_price": 12.5,
                "currency": "USD",
                "vendor": "Acme",
                "updated_at": "2026-06-30T12:00:00Z",
            }
        ],
        "source": {
            "database": "mock",
            "template_id": "query_bom_cost:v1",
            "executed_at": "2026-07-01T00:00:00Z",
        },
        "warnings": [],
        "error": None,
    }
    payload.update(overrides)
    return payload


def _verification(**overrides):
    payload = {
        "ok": True,
        "status": "success",
        "row_count": 1,
        "empty_result": False,
        "over_limit": False,
        "required_columns_exist": True,
        "output_schema_valid": True,
        "deterministic_summary": None,
        "warnings": [],
        "error": None,
    }
    payload.update(overrides)
    return payload


def test_synthesize_one_row_includes_returned_fields() -> None:
    answer = synthesize_answer(
        user_query="A123 在 P01 的 BOM cost?",
        evidence_pack=[{"id": "doc-1", "text": "Old document data."}],
        query_plan=_plan(),
        query_result=_result(),
        result_verification=_verification(),
    ).final_answer

    assert "unit_price: 12.5" in answer
    assert "currency: USD" in answer
    assert "vendor: Acme" in answer
    assert "updated_at: 2026-06-30T12:00:00Z" in answer
    assert "part_no=A123" in answer
    assert "template_id=query_bom_cost:v1" in answer


def test_synthesize_zero_rows_says_no_data() -> None:
    answer = synthesize_answer(
        user_query="A123 在 P01 的 BOM cost?",
        evidence_pack=[{"id": "doc-1", "text": "Document says historical cost exists."}],
        query_plan=_plan(),
        query_result=_result(row_count=0, data=[]),
        result_verification=_verification(
            row_count=0,
            empty_result=True,
            deterministic_summary={"empty_result_answer": "No BOM cost rows were found."},
        ),
    ).final_answer

    assert "查無資料" in answer
    assert "No BOM cost rows were found." in answer
    assert "historical cost exists" not in answer


def test_synthesize_error_status_reports_failure_reason() -> None:
    answer = synthesize_answer(
        user_query="A123 在 P01 的 BOM cost?",
        evidence_pack=[],
        query_plan=_plan(),
        query_result=_result(status="error", row_count=0, data=[], error="database timeout"),
        result_verification=_verification(ok=False, status="error", error="database timeout"),
    ).final_answer

    assert "查詢失敗" in answer
    assert "database timeout" in answer


def test_synthesize_ask_clarification_mentions_project_id() -> None:
    answer = synthesize_answer(
        user_query="A123 的 BOM cost?",
        evidence_pack=[],
        query_plan=_plan(
            decision="ask_clarification",
            arguments={"part_no": "A123"},
            missing_args=["project_id"],
        ),
        query_result={},
        result_verification={},
    ).final_answer

    assert "project_id" in answer
    assert "查詢完成" not in answer


def test_synthesize_answer_from_docs_does_not_fake_api_result() -> None:
    answer = synthesize_answer(
        user_query="BOM cost 流程是什麼?",
        evidence_pack=[{"id": "doc-1", "text": "BOM cost 流程需要先確認料號與專案。"}],
        query_plan=_plan(decision="answer_from_docs", query_name=None, arguments={}),
        query_result={},
        result_verification={},
    ).final_answer

    assert "BOM cost 流程需要先確認料號與專案" in answer
    assert "查詢完成" not in answer
    assert "row_count" not in answer
    assert "API / SQL 查詢結果" not in answer
