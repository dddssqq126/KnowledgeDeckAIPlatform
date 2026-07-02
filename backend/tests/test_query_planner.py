from __future__ import annotations

import json
from typing import Any

import pytest

from agents.query_planner import build_query_planner_prompt, generate_query_plan


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


class FakeLLMClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate_query_plan(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return self.payload


def _candidate_query_cards() -> list[dict[str, Any]]:
    return [
        {
            "query_name": "query_bom_cost",
            "title": "BOM Cost",
            "description": "Returns BOM cost for a part in a project.",
            "required_args": {
                "part_no": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "optional_args": {},
            "auth_scope": "cost:read",
            "risk_level": "low",
        }
    ]


def _evidence_pack() -> list[dict[str, Any]]:
    return [{"id": "doc-1", "text": "BOM cost requires part_no and project_id."}]


def test_generate_query_plan_calls_query_template_for_complete_bom_cost_request() -> None:
    plan = generate_query_plan(
        user_query="請查 ABCD12 在 123A 的 BOM cost",
        evidence_pack=_evidence_pack(),
        candidate_query_cards=_candidate_query_cards(),
    )

    assert plan.decision == "call_query_template"
    assert plan.query_name == "query_bom_cost"
    assert plan.arguments == {"part_no": "ABCD12", "project_id": "123A"}
    assert plan.missing_args == []


def test_generate_query_plan_asks_clarification_when_project_id_missing() -> None:
    plan = generate_query_plan(
        user_query="請查 ABCD12 的 BOM cost",
        evidence_pack=_evidence_pack(),
        candidate_query_cards=_candidate_query_cards(),
    )

    assert plan.decision == "ask_clarification"
    assert plan.query_name == "query_bom_cost"
    assert plan.arguments == {"part_no": "ABCD12"}
    assert plan.missing_args == ["project_id"]


def test_generate_query_plan_answers_process_question_from_docs() -> None:
    plan = generate_query_plan(
        user_query="請說明 BOM cost 流程",
        evidence_pack=_evidence_pack(),
        candidate_query_cards=_candidate_query_cards(),
    )

    assert plan.decision == "answer_from_docs"
    assert plan.query_name is None
    assert plan.arguments == {}
    assert plan.required_evidence_ids == ["doc-1"]


def test_generate_query_plan_rejects_query_name_outside_candidates() -> None:
    client = FakeLLMClient(
        {
            "decision": "call_query_template",
            "query_name": "query_inventory",
            "arguments": {"part_no": "ABCD12", "project_id": "123A"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "Bad query name.",
            "required_evidence_ids": [],
        }
    )

    with pytest.raises(ValueError, match="candidate_query_cards"):
        generate_query_plan(
            user_query="請查 ABCD12 在 123A 的 BOM cost",
            evidence_pack=_evidence_pack(),
            candidate_query_cards=_candidate_query_cards(),
            llm_client=client,
        )


def test_generate_query_plan_rejects_raw_sql_output() -> None:
    client = FakeLLMClient(
        {
            "decision": "call_query_template",
            "query_name": "query_bom_cost",
            "arguments": {"raw_sql": "SELECT * FROM bom_items"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "Bad raw SQL.",
            "required_evidence_ids": [],
        }
    )

    with pytest.raises(ValueError, match="raw_sql"):
        generate_query_plan(
            user_query="請查 ABCD12 在 123A 的 BOM cost",
            evidence_pack=_evidence_pack(),
            candidate_query_cards=_candidate_query_cards(),
            llm_client=client,
        )


def test_build_query_planner_prompt_removes_auth_scope_and_risk_level() -> None:
    _system_prompt, user_prompt = build_query_planner_prompt(
        user_query="請查 ABCD12 在 123A 的 BOM cost",
        evidence_pack=_evidence_pack(),
        candidate_query_cards=_candidate_query_cards(),
    )

    payload = json.loads(user_prompt)
    card = payload["candidate_query_cards"][0]
    assert "auth_scope" not in card
    assert "risk_level" not in card
