from __future__ import annotations

from typing import Any

import pytest

from services.query_pipeline import (
    find_candidate_query_cards,
    rank_candidate_query_cards,
    run_query_pipeline,
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


class FakeExecutor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def execute(self, query_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"query_name": query_name, "arguments": arguments})
        return {
            "query_name": query_name,
            "status": "success",
            "input": arguments,
            "row_count": len(self.rows),
            "columns": list(self.rows[0]) if self.rows else [],
            "data": self.rows,
            "source": {
                "database": "mock",
                "template_id": f"{query_name}:v1",
                "executed_at": "2026-07-01T00:00:00Z",
            },
            "warnings": [],
            "error": None,
        }


class FakePlannerClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_user_prompt: str | None = None

    def generate_query_plan(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.last_user_prompt = user_prompt
        return self.payload


def _run(**overrides: Any):
    payload = {
        "user_id": 1,
        "user_message": "Please query BOM cost for A123",
        "rag_query": None,
        "history": [],
        "evidence_context": "BOM cost needs part_no.",
        "citations": [{"id": "doc-1", "text": "BOM cost background."}],
        "kb_ids": [1],
        "planner_client": FakePlannerClient(
            {
                "decision": "call_query_template",
                "query_name": "query_bom_cost",
                "arguments": {"part_no": "A123"},
                "missing_args": [],
                "confidence": 0.9,
                "reason": "The discovered BOM cost tool matches the request.",
                "required_evidence_ids": [],
            }
        ),
    }
    payload.update(overrides)
    return run_query_pipeline(**payload)


def _tool_card(
    name: str,
    *,
    title: str | None = None,
    description: str = "",
    required_args: dict[str, Any] | None = None,
    status: str = "enabled",
    do_not_use_when: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "query_name": name,
        "mcp_tool_name": name,
        "title": title or name.replace("_", " ").title(),
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": required_args or {},
            "required": list((required_args or {}).keys()),
        },
        "required_args": required_args or {},
        "optional_args": {},
        "do_not_use_when": do_not_use_when or [],
        "status": status,
        "transport": "mcp-sse",
    }


def _filler_cards(count: int) -> list[dict[str, Any]]:
    return [
        _tool_card(
            f"query_filler_{index}",
            title=f"Filler Tool {index}",
            description=f"Generic unrelated tool number {index}.",
        )
        for index in range(count)
    ]


def test_find_candidate_query_cards_small_set_returns_all_enabled_tools() -> None:
    cards = [
        _tool_card("query_weather"),
        _tool_card("query_disabled_weather", status="disabled"),
        _tool_card("query_inventory"),
    ]

    result = find_candidate_query_cards(search_text="weather", query_cards=cards)

    assert [card["query_name"] for card in result] == [
        "query_weather",
        "query_inventory",
    ]


def test_find_candidate_query_cards_large_set_returns_top_8() -> None:
    cards = _filler_cards(25)
    cards[18] = _tool_card(
        "query_weather",
        title="Current Weather",
        description="Get current weather forecast by city and location.",
        required_args={"location": {"type": "string", "description": "City location."}},
    )

    result = find_candidate_query_cards(
        search_text="weather forecast for city location",
        query_cards=cards,
    )

    assert len(result) == 8
    assert result[0]["query_name"] == "query_weather"


def test_find_candidate_query_cards_schema_arg_match_ranks_above_unrelated_tools() -> None:
    cards = _filler_cards(21)
    cards[7] = _tool_card(
        "query_part_status",
        title="Part Status",
        description="Lookup operational state.",
        required_args={
            "part_no": {
                "type": "string",
                "description": "Part number or component identifier.",
            }
        },
    )

    result = find_candidate_query_cards(
        search_text="component part number status",
        query_cards=cards,
    )

    assert result[0]["query_name"] == "query_part_status"


def test_find_candidate_query_cards_do_not_use_when_lowers_rank() -> None:
    cards = _filler_cards(21)
    cards[3] = _tool_card(
        "query_process_data",
        title="Process Data",
        description="Returns process data metrics.",
        do_not_use_when=["The user asks about process documentation."],
    )
    cards[9] = _tool_card(
        "query_process_docs",
        title="Process Documentation",
        description="Answers process documentation questions.",
    )

    result = rank_candidate_query_cards(
        search_text="process documentation",
        query_cards=cards,
    )
    scores = {
        item["query_name"]: item["score"]
        for item in result.tool_ranker_scores
    }

    assert scores["query_process_docs"] > scores["query_process_data"]


def test_find_candidate_query_cards_uses_stable_order_for_equal_scores() -> None:
    cards = _filler_cards(24)

    result = find_candidate_query_cards(
        search_text="no matching vocabulary",
        query_cards=cards,
    )

    assert [card["query_name"] for card in result] == [
        f"query_filler_{index}" for index in range(8)
    ]


def test_query_pipeline_executes_bom_cost_and_context_contains_unit_price() -> None:
    executor = FakeExecutor(
        rows=[
            {
                "part_no": "A123",
                "unit_price": 12.5,
                "currency": "USD",
                "vendor": "Acme",
                "updated_at": "2026-06-30T12:00:00Z",
            }
        ]
    )

    result = _run(executor=executor)

    assert result.decision == "call_query_template"
    assert result.query_name == "query_bom_cost"
    assert result.query_result is not None
    assert result.query_result["row_count"] == 1
    assert result.context_block is not None
    assert "unit_price" in result.context_block
    assert "12.5" in result.context_block
    assert executor.calls == [
        {"query_name": "query_bom_cost", "arguments": {"part_no": "A123"}}
    ]


def test_query_pipeline_missing_part_no_asks_clarification_without_executor() -> None:
    executor = FakeExecutor(rows=[])
    planner = FakePlannerClient(
        {
            "decision": "ask_clarification",
            "query_name": "query_bom_cost",
            "arguments": {},
            "missing_args": ["part_no"],
            "confidence": 0.8,
            "reason": "Missing part number.",
            "required_evidence_ids": [],
        }
    )

    result = _run(executor=executor, planner_client=planner)

    assert result.decision == "ask_clarification"
    assert result.query_name == "query_bom_cost"
    assert result.user_visible_message is not None
    assert "part_no" in result.user_visible_message
    assert executor.calls == []


def test_query_pipeline_empty_result_context_says_no_data() -> None:
    executor = FakeExecutor(rows=[])

    result = _run(executor=executor)

    assert result.decision == "call_query_template"
    assert result.query_result is not None
    assert result.query_result["row_count"] == 0
    assert result.context_block is not None
    assert "row_count: 0" in result.context_block


def test_query_pipeline_no_candidate_cards_is_not_applicable() -> None:
    executor = FakeExecutor(rows=[])

    result = _run(
        user_message="What is the inventory process?",
        rag_query="inventory process",
        query_cards=[],
        executor=executor,
    )

    assert result.decision == "not_applicable"
    assert result.query_plan is None
    assert executor.calls == []


def test_query_pipeline_rejects_raw_sql_from_planner() -> None:
    executor = FakeExecutor(rows=[])
    planner = FakePlannerClient(
        {
            "decision": "call_query_template",
            "query_name": "query_bom_cost",
            "arguments": {"raw_sql": "SELECT * FROM bom_items"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "Unsafe raw SQL.",
            "required_evidence_ids": [],
        }
    )

    result = _run(executor=executor, planner_client=planner)

    assert result.decision == "rejected"
    assert result.user_visible_message is not None
    assert "raw_sql" in result.user_visible_message
    assert executor.calls == []


def test_query_pipeline_executes_llm_info_tool() -> None:
    executor = FakeExecutor(
        rows=[{"label": "Gemma 4 E4B", "model_id": "google/gemma-4-E4B-it"}]
    )
    planner = FakePlannerClient(
        {
            "decision": "call_query_template",
            "query_name": "query_llm_info",
            "arguments": {},
            "missing_args": [],
            "confidence": 0.92,
            "reason": "The user asks what model this system uses.",
            "required_evidence_ids": [],
        }
    )
    query_cards = [
        {
            "query_name": "query_llm_info",
            "title": "System LLM Info",
            "description": "Returns the configured chat LLM label and model id.",
            "sql_type": "tool",
            "when_to_use": ["User asks what LLM/model this system uses."],
            "do_not_use_when": [],
            "required_args": {},
            "optional_args": {},
            "output_schema": {"label": "string", "model_id": "string"},
            "empty_result_policy": {"answer": "No LLM info was returned."},
            "row_limit": 1,
            "transport": "in-process",
            "handler_key": "llm_info",
            "template_id": "query_llm_info:v1",
        }
    ]

    result = _run(
        user_message="What LLM is this system based on?",
        query_cards=query_cards,
        executor=executor,
        planner_client=planner,
    )

    assert result.decision == "call_query_template"
    assert result.query_name == "query_llm_info"
    assert result.context_block is not None
    assert "Gemma 4 E4B" in result.context_block
    assert "google/gemma-4-E4B-it" in result.context_block
    assert executor.calls == [{"query_name": "query_llm_info", "arguments": {}}]


def test_query_pipeline_prompt_receives_enabled_tool_cards() -> None:
    planner = FakePlannerClient(
        {
            "decision": "answer_from_docs",
            "query_name": None,
            "arguments": {},
            "missing_args": [],
            "confidence": 0.8,
            "reason": "Documentation question.",
            "required_evidence_ids": [],
        }
    )
    query_cards = [
        {
            "query_name": "query_llm_info",
            "title": "System LLM Info",
            "description": "Returns the configured chat LLM label and model id.",
            "required_args": {},
            "optional_args": {},
            "output_schema": {"label": "string", "model_id": "string"},
            "handler_key": "llm_info",
        }
    ]

    result = _run(query_cards=query_cards, planner_client=planner)

    assert result.decision == "answer_from_docs"
    assert planner.last_user_prompt is not None
    assert "query_llm_info" in planner.last_user_prompt


def test_query_pipeline_prompt_receives_ranked_candidates_not_full_large_tool_list() -> None:
    planner = FakePlannerClient(
        {
            "decision": "answer_from_docs",
            "query_name": None,
            "arguments": {},
            "missing_args": [],
            "confidence": 0.8,
            "reason": "Documentation question.",
            "required_evidence_ids": [],
        }
    )
    query_cards = _filler_cards(25)
    query_cards[20] = _tool_card(
        "query_weather",
        title="Current Weather",
        description="Get current weather forecast by city and location.",
        required_args={"location": {"type": "string", "description": "City location."}},
    )

    result = _run(
        user_message="What is the weather forecast for Taipei city?",
        rag_query="weather forecast Taipei city location",
        query_cards=query_cards,
        planner_client=planner,
    )

    assert result.decision == "answer_from_docs"
    assert result.debug["tool_ranker_applied"] is True
    assert result.debug["all_candidate_query_names"] == [
        card["query_name"] for card in query_cards
    ]
    assert len(result.debug["ranked_candidate_query_names"]) == 8
    assert result.debug["ranked_candidate_query_names"][0] == "query_weather"
    assert planner.last_user_prompt is not None
    assert "query_weather" in planner.last_user_prompt
    assert "query_filler_24" not in planner.last_user_prompt


def test_query_pipeline_validates_query_card_owned_template_for_custom_bom_tool() -> None:
    executor = FakeExecutor(rows=[{"part_no": "A123", "project_id": "P01"}])
    planner = FakePlannerClient(
        {
            "decision": "call_query_template",
            "query_name": "query_bom_cost",
            "arguments": {"part_no": "A123", "project_id": "P01"},
            "missing_args": [],
            "confidence": 0.9,
            "reason": "The query card requires both part and project.",
            "required_evidence_ids": [],
        }
    )
    query_cards = [
        {
            "query_name": "query_bom_cost",
            "title": "Project BOM Cost",
            "description": "Returns project-scoped BOM costs.",
            "sql_type": "select",
            "when_to_use": ["User asks for BOM cost within a project."],
            "do_not_use_when": [],
            "required_args": {
                "part_no": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "optional_args": {},
            "output_schema": {"part_no": "string", "project_id": "string"},
            "empty_result_policy": {"answer": "No rows."},
            "row_limit": 100,
            "transport": "in-process",
            "handler_key": "query_bom_cost",
            "template_id": "query_bom_cost:project-v1",
            "sql": (
                "SELECT part_no, project_id FROM bom_items "
                "WHERE part_no = :part_no AND project_id = :project_id"
            ),
        }
    ]

    result = _run(query_cards=query_cards, planner_client=planner, executor=executor)

    assert result.decision == "call_query_template"
    assert result.query_name == "query_bom_cost"
    assert result.debug["validation"]["checks"]["sql_template_valid"] is True
    assert executor.calls == [
        {
            "query_name": "query_bom_cost",
            "arguments": {"part_no": "A123", "project_id": "P01"},
        }
    ]
