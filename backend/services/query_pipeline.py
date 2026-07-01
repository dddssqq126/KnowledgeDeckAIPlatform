from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from agents.query_planner import QueryPlannerLLMClient, generate_query_plan
from agents.query_validator import validate_query_plan
from agents.result_verifier import verify_query_result
from agents.synthesizer import synthesize_answer
from mcp_servers.business_query_server import query_bom_cost
from sql_templates.registry import SQL_TEMPLATE_REGISTRY, SqlTemplate


PipelineDecision = Literal[
    "answer_from_docs",
    "call_query_template",
    "ask_clarification",
    "rejected",
    "not_applicable",
]


class QueryPipelineResult(BaseModel):
    decision: PipelineDecision
    query_name: str | None = None
    query_plan: dict[str, Any] | None = None
    query_result: dict[str, Any] | None = None
    result_verification: dict[str, Any] | None = None
    context_block: str | None = None
    citations: list[dict[str, Any]]
    user_visible_message: str | None = None
    debug: dict[str, Any]


class QueryExecutor(Protocol):
    def execute(self, query_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a fixed query template. Implementations must not accept raw SQL."""


class BomCostArgs(BaseModel):
    part_no: str
    project_id: str


QUERY_ARG_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "query_bom_cost": BomCostArgs,
}


DEFAULT_QUERY_CARDS: list[dict[str, Any]] = [
    {
        "query_name": "query_bom_cost",
        "title": "BOM Cost",
        "description": "Returns BOM cost rows for a part in a project.",
        "sql_type": "select",
        "when_to_use": ["User asks for BOM cost by part and project."],
        "do_not_use_when": ["User asks about process documentation only."],
        "required_args": {
            "part_no": {"type": "string", "description": "Part number."},
            "project_id": {"type": "string", "description": "Project id."},
        },
        "optional_args": {},
        "output_schema": {
            "part_no": "string",
            "unit_price": "number",
            "currency": "string",
            "vendor": "string",
            "updated_at": "string",
        },
        "empty_result_policy": {
            "answer": "No BOM cost rows were found for the query conditions."
        },
        "row_limit": 500,
    }
]


class McpQueryExecutor:
    def execute(self, query_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if "raw_sql" in arguments:
            raise ValueError("raw_sql is not allowed")
        if query_name == "query_bom_cost":
            response = query_bom_cost({"part_no": arguments["part_no"]})
            return response.model_dump()
        raise KeyError(f"Unsupported query_name: {query_name}")


def find_candidate_query_cards(
    *, search_text: str, query_cards: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    cards = query_cards or DEFAULT_QUERY_CARDS
    lowered = search_text.casefold()
    if "bom" in lowered and ("cost" in lowered or "成本" in lowered):
        return [card for card in cards if card.get("query_name") == "query_bom_cost"]
    return []


def _evidence_pack(
    *, evidence_context: str | None, citations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    pack: list[dict[str, Any]] = []
    if evidence_context:
        pack.append({"id": "evidence_context", "text": evidence_context})
    for idx, citation in enumerate(citations, start=1):
        item = dict(citation)
        item.setdefault("id", item.get("evidence_id") or f"citation_{idx}")
        pack.append(item)
    return pack


def _query_card_for(
    query_name: str | None, candidate_query_cards: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if query_name is None:
        return None
    return next(
        (card for card in candidate_query_cards if card.get("query_name") == query_name),
        None,
    )


def _format_context_block(
    *,
    query_name: str,
    arguments: dict[str, Any],
    query_result: dict[str, Any],
    result_verification: dict[str, Any],
) -> str:
    source = query_result.get("source") or {}
    rows = query_result.get("data") or []
    row_count = query_result.get("row_count", 0)
    if result_verification.get("empty_result") or row_count == 0:
        summary = "查無資料"
    else:
        summary = json.dumps(rows[:5], ensure_ascii=False, sort_keys=True)
    return "\n".join(
        [
            f"Query Template 名稱: {query_name}",
            f"查詢條件: {json.dumps(arguments, ensure_ascii=False, sort_keys=True)}",
            f"查詢結果摘要: {summary}",
            f"row_count: {row_count}",
            f"source.database: {source.get('database')}",
            f"source.template_id: {source.get('template_id')}",
            f"source.executed_at: {source.get('executed_at')}",
        ]
    )


def run_query_pipeline(
    *,
    user_id: int,
    user_message: str,
    rag_query: str | None,
    history: list[dict[str, Any]],
    evidence_context: str | None,
    citations: list[dict[str, Any]],
    kb_ids: list[int],
    query_cards: list[dict[str, Any]] | None = None,
    sql_template_registry: dict[str, SqlTemplate] | None = None,
    query_arg_schema_map: dict[str, type[BaseModel]] | None = None,
    planner_client: QueryPlannerLLMClient | None = None,
    executor: QueryExecutor | None = None,
) -> QueryPipelineResult:
    search_text = rag_query or user_message
    candidate_query_cards = find_candidate_query_cards(
        search_text=search_text,
        query_cards=query_cards,
    )
    debug: dict[str, Any] = {
        "user_id": user_id,
        "kb_ids": kb_ids,
        "history_count": len(history),
        "candidate_query_names": [
            card.get("query_name") for card in candidate_query_cards
        ],
    }
    if not candidate_query_cards:
        return QueryPipelineResult(
            decision="not_applicable",
            citations=citations,
            debug=debug,
        )

    evidence_pack = _evidence_pack(evidence_context=evidence_context, citations=citations)
    try:
        plan = generate_query_plan(
            user_query=user_message,
            evidence_pack=evidence_pack,
            candidate_query_cards=candidate_query_cards,
            llm_client=planner_client,
        )
    except ValueError as exc:
        return QueryPipelineResult(
            decision="rejected",
            citations=citations,
            user_visible_message=str(exc),
            debug={**debug, "planner_error": str(exc)},
        )
    plan_dict = plan.model_dump()
    registry = sql_template_registry or SQL_TEMPLATE_REGISTRY
    schema_map = query_arg_schema_map or QUERY_ARG_SCHEMA_MAP
    try:
        validation = validate_query_plan(
            query_plan=plan,
            candidate_query_cards=candidate_query_cards,
            sql_template_registry=registry,
            query_arg_schema_map=schema_map,
        )
    except ValueError as exc:
        return QueryPipelineResult(
            decision="rejected",
            query_name=plan.query_name,
            query_plan=plan_dict,
            citations=citations,
            user_visible_message=str(exc),
            debug={**debug, "validation_error": str(exc)},
        )
    debug["validation"] = validation.model_dump()

    if plan.decision == "answer_from_docs":
        message = synthesize_answer(
            user_query=user_message,
            evidence_pack=evidence_pack,
            query_plan=plan,
            query_result={},
            result_verification={},
        ).final_answer
        return QueryPipelineResult(
            decision="answer_from_docs",
            query_name=plan.query_name,
            query_plan=plan_dict,
            citations=citations,
            user_visible_message=message,
            debug=debug,
        )

    if validation.action == "ask_clarification":
        message = synthesize_answer(
            user_query=user_message,
            evidence_pack=evidence_pack,
            query_plan=plan,
            query_result={},
            result_verification={},
        ).final_answer
        return QueryPipelineResult(
            decision="ask_clarification",
            query_name=plan.query_name,
            query_plan=plan_dict,
            citations=citations,
            user_visible_message=message,
            debug=debug,
        )

    if validation.action == "reject":
        return QueryPipelineResult(
            decision="rejected",
            query_name=plan.query_name,
            query_plan=plan_dict,
            citations=citations,
            user_visible_message=validation.error or validation.reason,
            debug=debug,
        )

    runner = executor or McpQueryExecutor()
    query_result = runner.execute(
        validation.query_name or "",
        validation.normalized_arguments,
    )
    query_card = _query_card_for(validation.query_name, candidate_query_cards)
    if query_card is None:
        return QueryPipelineResult(
            decision="rejected",
            query_name=validation.query_name,
            query_plan=plan_dict,
            query_result=query_result,
            citations=citations,
            user_visible_message="Query card was not found after validation.",
            debug=debug,
        )

    verification = verify_query_result(
        query_result=query_result,
        query_card=query_card,
    )
    verification_dict = verification.model_dump()
    context_block = _format_context_block(
        query_name=validation.query_name or "",
        arguments=validation.normalized_arguments,
        query_result=query_result,
        result_verification=verification_dict,
    )

    decision: PipelineDecision = (
        "call_query_template" if plan.decision == "call_query_template" else plan.decision
    )
    user_visible_message = None
    if not verification.ok:
        user_visible_message = synthesize_answer(
            user_query=user_message,
            evidence_pack=evidence_pack,
            query_plan=plan,
            query_result=query_result,
            result_verification=verification,
        ).final_answer

    return QueryPipelineResult(
        decision=decision,
        query_name=validation.query_name,
        query_plan=plan_dict,
        query_result=query_result,
        result_verification=verification_dict,
        context_block=context_block,
        citations=citations,
        user_visible_message=user_visible_message,
        debug=debug,
    )


def run(**kwargs: Any) -> QueryPipelineResult:
    return run_query_pipeline(**kwargs)
