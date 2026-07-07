from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
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


TOOL_RANKER_FULL_PASS_THRESHOLD = 20
TOOL_RANKER_LIMIT = 8


@dataclass(frozen=True)
class ToolRankerResult:
    cards: list[dict[str, Any]]
    all_candidate_query_names: list[str]
    ranked_candidate_query_names: list[str]
    tool_ranker_applied: bool
    tool_ranker_scores: list[dict[str, Any]]


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


def _sql_template_from_query_card(card: dict[str, Any]) -> SqlTemplate | None:
    query_name = str(card.get("query_name") or "")
    sql = card.get("sql")
    template_payload = card.get("sql_template")
    if isinstance(template_payload, dict):
        sql = template_payload.get("sql", sql)
    else:
        template_payload = {}

    if not query_name or not isinstance(sql, str) or not sql.strip():
        return None

    arg_names: list[str] = []
    required_args = card.get("required_args") or {}
    if isinstance(required_args, dict):
        arg_names.extend(str(name) for name in required_args)
    optional_args = card.get("optional_args") or {}
    if isinstance(optional_args, dict):
        arg_names.extend(str(name) for name in optional_args)
    raw_allowed_params = (
        template_payload.get("allowed_params")
        or template_payload.get("allowedParams")
        or card.get("allowed_params")
        or card.get("allowedParams")
        or arg_names
    )
    if isinstance(raw_allowed_params, str):
        allowed_params = [raw_allowed_params]
    else:
        allowed_params = list(raw_allowed_params)
    return SqlTemplate(
        template_id=str(
            template_payload.get("template_id")
            or template_payload.get("templateId")
            or card.get("template_id")
            or f"{query_name}:query-card"
        ),
        query_name=query_name,
        version=str(
            template_payload.get("version")
            or card.get("version")
            or str(card.get("template_id") or "query-card").rsplit(":", 1)[-1]
        ),
        sql=sql,
        allowed_params=tuple(str(param) for param in allowed_params),
        row_limit=int(
            template_payload.get("row_limit") or card.get("row_limit") or 500
        ),
        timeout_sec=int(
            template_payload.get("timeout_sec") or card.get("timeout_sec") or 10
        ),
    )


def _sql_template_registry_from_query_cards(
    candidate_query_cards: list[dict[str, Any]],
) -> dict[str, SqlTemplate]:
    registry: dict[str, SqlTemplate] = {}
    for card in candidate_query_cards:
        template = _sql_template_from_query_card(card)
        if template is not None:
            registry[template.query_name] = template
    return registry


def _validation_registry(
    *,
    candidate_query_cards: list[dict[str, Any]],
    query_cards: list[dict[str, Any]] | None,
    sql_template_registry: dict[str, SqlTemplate] | None,
) -> dict[str, SqlTemplate]:
    if sql_template_registry is not None:
        return sql_template_registry
    query_card_registry = _sql_template_registry_from_query_cards(candidate_query_cards)
    if query_card_registry or query_cards is not None:
        return query_card_registry
    return SQL_TEMPLATE_REGISTRY


def _validation_schema_map(
    *,
    query_cards: list[dict[str, Any]] | None,
    query_arg_schema_map: dict[str, type[BaseModel]] | None,
) -> dict[str, type[BaseModel]] | None:
    if query_arg_schema_map is not None:
        return query_arg_schema_map
    if query_cards is not None:
        return None
    return QUERY_ARG_SCHEMA_MAP


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


def _enabled_query_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        card
        for card in cards
        if card.get("query_name")
        and str(card.get("status") or "enabled").casefold() != "disabled"
    ]


def _tokens(text: str) -> Counter[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    normalized = normalized.replace("_", " ").replace("-", " ")
    return Counter(re.findall(r"[a-zA-Z0-9]+", normalized.casefold()))


def _metadata_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_metadata_text(item)}" for key, item in value.items()
        )
    if isinstance(value, list | tuple | set):
        return " ".join(_metadata_text(item) for item in value)
    return str(value)


def _tool_metadata_text(card: dict[str, Any]) -> str:
    fields = [
        card.get("query_name"),
        card.get("mcp_tool_name"),
        card.get("title"),
        card.get("description"),
        card.get("when_to_use"),
        card.get("do_not_use_when"),
        card.get("input_schema"),
        card.get("required_args"),
        card.get("optional_args"),
        card.get("annotations"),
    ]
    return " ".join(_metadata_text(field) for field in fields)


def _schema_description_text(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        description = value.get("description")
        if description:
            parts.append(str(description))
        for child in value.values():
            parts.append(_schema_description_text(child))
        return " ".join(parts)
    if isinstance(value, list):
        return " ".join(_schema_description_text(item) for item in value)
    return ""


def _token_overlap_score(query: Counter[str], text: Any) -> float:
    if not query:
        return 0.0
    target = _tokens(_metadata_text(text))
    return float(sum(min(query[token], target[token]) for token in query))


def _score_query_card(*, search_text: str, card: dict[str, Any]) -> float:
    query = _tokens(search_text)
    if not query:
        return 0.0

    score = _token_overlap_score(query, _tool_metadata_text(card))
    score += 3.0 * _token_overlap_score(
        query,
        [card.get("query_name"), card.get("mcp_tool_name"), card.get("title")],
    )
    score += 2.0 * _token_overlap_score(
        query,
        list((card.get("required_args") or {}).keys())
        if isinstance(card.get("required_args"), dict)
        else card.get("required_args"),
    )
    score += 1.5 * _token_overlap_score(
        query,
        _schema_description_text(card.get("input_schema"))
        or _schema_description_text(card.get("required_args"))
        or _schema_description_text(card.get("optional_args")),
    )
    score -= 4.0 * _token_overlap_score(query, card.get("do_not_use_when"))
    return score


def rank_candidate_query_cards(
    *, search_text: str, query_cards: list[dict[str, Any]] | None = None
) -> ToolRankerResult:
    cards = DEFAULT_QUERY_CARDS if query_cards is None else query_cards
    enabled_cards = _enabled_query_cards(cards)
    all_names = [str(card.get("query_name")) for card in enabled_cards]
    scored_cards = [
        (index, _score_query_card(search_text=search_text, card=card), card)
        for index, card in enumerate(enabled_cards)
    ]

    if len(enabled_cards) <= TOOL_RANKER_FULL_PASS_THRESHOLD:
        return ToolRankerResult(
            cards=enabled_cards,
            all_candidate_query_names=all_names,
            ranked_candidate_query_names=all_names,
            tool_ranker_applied=False,
            tool_ranker_scores=[
                {"query_name": card.get("query_name"), "score": score}
                for _, score, card in scored_cards
            ],
        )

    ranked = sorted(scored_cards, key=lambda item: (-item[1], item[0]))
    selected = ranked[:TOOL_RANKER_LIMIT]
    return ToolRankerResult(
        cards=[card for _, _, card in selected],
        all_candidate_query_names=all_names,
        ranked_candidate_query_names=[str(card.get("query_name")) for _, _, card in selected],
        tool_ranker_applied=True,
        tool_ranker_scores=[
            {"query_name": card.get("query_name"), "score": score}
            for _, score, card in ranked
        ],
    )


def find_candidate_query_cards(
    *, search_text: str, query_cards: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    return rank_candidate_query_cards(
        search_text=search_text,
        query_cards=query_cards,
    ).cards



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
    ranker_result = rank_candidate_query_cards(
        search_text=search_text,
        query_cards=query_cards,
    )
    candidate_query_cards = ranker_result.cards
    debug: dict[str, Any] = {
        "user_id": user_id,
        "kb_ids": kb_ids,
        "history_count": len(history),
        "candidate_query_names": [
            card.get("query_name") for card in candidate_query_cards
        ],
        "all_candidate_query_names": ranker_result.all_candidate_query_names,
        "ranked_candidate_query_names": ranker_result.ranked_candidate_query_names,
        "tool_ranker_applied": ranker_result.tool_ranker_applied,
        "tool_ranker_scores": ranker_result.tool_ranker_scores,
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
    registry = _validation_registry(
        candidate_query_cards=candidate_query_cards,
        query_cards=query_cards,
        sql_template_registry=sql_template_registry,
    )
    schema_map = _validation_schema_map(
        query_cards=query_cards,
        query_arg_schema_map=query_arg_schema_map,
    )
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
