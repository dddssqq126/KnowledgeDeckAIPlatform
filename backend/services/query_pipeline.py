from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.features.mcp_tools.services import tool_service
from agents.query_planner import QueryPlannerLLMClient, generate_query_plan
from agents.query_validator import validate_query_plan
from agents.result_verifier import verify_query_result
from agents.synthesizer import synthesize_answer
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


QUERY_ARG_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "query_bom_cost": BomCostArgs,
}


DEFAULT_QUERY_CARDS: list[dict[str, Any]] = [
    {
        "query_name": "query_bom_cost",
        "title": "BOM Cost",
        "description": "Returns BOM cost rows for a part number.",
        "sql_type": "select",
        "when_to_use": ["User asks for BOM cost by part number."],
        "do_not_use_when": ["User asks about process documentation only."],
        "required_args": {"part_no": {"type": "string", "description": "Part number."}},
        "optional_args": {},
        "output_schema": {
            "part_no": "string",
            "component_part_no": "string",
            "quantity": "number",
            "unit_cost": "number",
            "extended_cost": "number",
        },
        "empty_result_policy": {
            "answer": "No BOM cost rows were found for the query conditions."
        },
        "row_limit": 500,
        "transport": "in-process",
        "handler_key": "query_bom_cost",
        "template_id": "query_bom_cost:v1",
    }
]


def _json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Query planner LLM must return a JSON object")
    return parsed


class ConfiguredQueryPlannerLLMClient:
    def generate_query_plan(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            streaming=False,
            temperature=0,
            max_tokens=512,
        )
        result = llm.invoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )
        return _json_from_text(str(result.content or ""))


class McpQueryExecutor:
    def __init__(self, tool_cards: list[dict[str, Any]] | None = None) -> None:
        self.tool_cards = tool_cards or DEFAULT_QUERY_CARDS

    def execute(self, query_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return tool_service.execute_registered_tool(
            query_name=query_name,
            arguments=arguments,
            tool_cards=self.tool_cards,
        )


def find_candidate_query_cards(
    *, search_text: str, query_cards: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    _ = search_text
    cards = DEFAULT_QUERY_CARDS if query_cards is None else query_cards
    return [card for card in cards if card.get("query_name")]


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
    error = query_result.get("error") or result_verification.get("error")
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
            f"error: {error}" if error else "error: None",
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
            llm_client=planner_client or ConfiguredQueryPlannerLLMClient(),
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

    runner = executor or McpQueryExecutor(tool_cards=candidate_query_cards)
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
