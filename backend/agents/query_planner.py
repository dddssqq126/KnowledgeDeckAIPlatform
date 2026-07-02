from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


PlanDecision = Literal["answer_from_docs", "call_query_template", "ask_clarification"]


class QueryPlan(BaseModel):
    decision: PlanDecision
    query_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    missing_args: list[str] = Field(default_factory=list)
    confidence: float
    reason: str
    required_evidence_ids: list[str] = Field(default_factory=list)


class QueryPlannerLLMClient(Protocol):
    def generate_query_plan(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Return a JSON-like QueryPlan payload."""


def _sanitize_candidate_query_card(card: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in card.items() if k not in {"auth_scope", "risk_level"}}


def _sanitize_candidate_query_cards(
    candidate_query_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [_sanitize_candidate_query_card(card) for card in candidate_query_cards]


def build_query_planner_prompt(
    *,
    user_query: str,
    evidence_pack: list[dict[str, Any]],
    candidate_query_cards: list[dict[str, Any]],
) -> tuple[str, str]:
    sanitized_cards = _sanitize_candidate_query_cards(candidate_query_cards)
    system_prompt = """
You are a query planner. Produce exactly one QueryPlan JSON object.

Allowed decisions:
- answer_from_docs: use this for process, policy, definition, or documentation questions.
- call_query_template: use this when a registered tool or database-backed query
  template is needed and all required arguments are available.
- ask_clarification: use this when required arguments are missing or ambiguous.

Rules:
- Do not write SQL.
- Do not output raw_sql.
- Choose query_name only from candidate_query_cards.
- Use missing_args for any required argument that is not available.
- For zero-argument tools, use arguments={} and missing_args=[].
- Use required_evidence_ids for evidence items needed to justify the plan.
""".strip()
    user_prompt = json.dumps(
        {
            "user_query": user_query,
            "evidence_pack": evidence_pack,
            "candidate_query_cards": sanitized_cards,
            "output_schema": QueryPlan.model_json_schema(),
        },
        ensure_ascii=False,
        indent=2,
    )
    return system_prompt, user_prompt


def _candidate_query_names(candidate_query_cards: list[dict[str, Any]]) -> set[str]:
    return {
        str(card["query_name"])
        for card in candidate_query_cards
        if card.get("query_name") is not None
    }


def _contains_raw_sql(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k == "raw_sql" or _contains_raw_sql(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_raw_sql(item) for item in value)
    return False


def validate_query_plan(
    plan: QueryPlan,
    *,
    candidate_query_cards: list[dict[str, Any]],
) -> None:
    candidate_names = _candidate_query_names(candidate_query_cards)
    if plan.query_name is not None and plan.query_name not in candidate_names:
        raise ValueError(f"query_name is not in candidate_query_cards: {plan.query_name}")
    if _contains_raw_sql(plan.arguments):
        raise ValueError("QueryPlan arguments must not contain raw_sql")
    if plan.decision == "call_query_template" and plan.query_name is None:
        raise ValueError("call_query_template requires query_name")
    if plan.decision == "call_query_template" and plan.missing_args:
        raise ValueError("call_query_template must not include missing_args")


class StubQueryPlannerLLMClient:
    def generate_query_plan(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = json.loads(user_prompt)
        user_query = str(payload["user_query"])
        evidence_pack = payload["evidence_pack"]
        candidate_query_cards = payload["candidate_query_cards"]
        return _stub_plan(
            user_query=user_query,
            evidence_pack=evidence_pack,
            candidate_query_cards=candidate_query_cards,
        )


def _required_args(card: dict[str, Any]) -> list[str]:
    required_args = card.get("required_args") or {}
    if isinstance(required_args, dict):
        return list(required_args)
    if isinstance(required_args, list):
        return [str(item) for item in required_args]
    return []


def _extract_argument(user_query: str, arg_name: str) -> str | None:
    if arg_name == "part_no":
        match = re.search(r"\b[A-Z]\d{3}\b", user_query, flags=re.IGNORECASE)
        return match.group(0).upper() if match else None
    if arg_name == "project_id":
        match = re.search(r"\bP\d{2}\b", user_query, flags=re.IGNORECASE)
        return match.group(0).upper() if match else None
    if arg_name == "vendor_name":
        match = re.search(r"\b(?:Acme|Globex)\b", user_query, flags=re.IGNORECASE)
        return match.group(0) if match else None
    return None


def _evidence_ids(evidence_pack: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in evidence_pack:
        value = item.get("id") or item.get("evidence_id")
        if value is not None:
            ids.append(str(value))
    return ids


def _stub_plan(
    *,
    user_query: str,
    evidence_pack: list[dict[str, Any]],
    candidate_query_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    lowered = user_query.casefold()
    evidence_ids = _evidence_ids(evidence_pack)
    if any(token in lowered for token in ("流程", "process", "how to", "文件")):
        return {
            "decision": "answer_from_docs",
            "query_name": None,
            "arguments": {},
            "missing_args": [],
            "confidence": 0.72,
            "reason": "The user is asking a documentation or process question.",
            "required_evidence_ids": evidence_ids,
        }

    selected_card = next(
        (
            card
            for card in candidate_query_cards
            if "bom" in str(card.get("query_name", "")).casefold()
            or "bom" in str(card.get("title", "")).casefold()
        ),
        candidate_query_cards[0] if candidate_query_cards else None,
    )
    if selected_card is None:
        return {
            "decision": "answer_from_docs",
            "query_name": None,
            "arguments": {},
            "missing_args": [],
            "confidence": 0.3,
            "reason": "No candidate query card was available.",
            "required_evidence_ids": evidence_ids,
        }

    arguments: dict[str, Any] = {}
    missing_args: list[str] = []
    for arg_name in _required_args(selected_card):
        value = _extract_argument(user_query, arg_name)
        if value is None:
            missing_args.append(arg_name)
        else:
            arguments[arg_name] = value

    if missing_args:
        return {
            "decision": "ask_clarification",
            "query_name": selected_card["query_name"],
            "arguments": arguments,
            "missing_args": missing_args,
            "confidence": 0.68,
            "reason": "A query template appears relevant, but required arguments are missing.",
            "required_evidence_ids": evidence_ids,
        }

    return {
        "decision": "call_query_template",
        "query_name": selected_card["query_name"],
        "arguments": arguments,
        "missing_args": [],
        "confidence": 0.82,
        "reason": "The question needs database-backed facts and all required arguments are present.",
        "required_evidence_ids": evidence_ids,
    }


def generate_query_plan(
    *,
    user_query: str,
    evidence_pack: list[dict[str, Any]],
    candidate_query_cards: list[dict[str, Any]],
    llm_client: QueryPlannerLLMClient | None = None,
) -> QueryPlan:
    system_prompt, user_prompt = build_query_planner_prompt(
        user_query=user_query,
        evidence_pack=evidence_pack,
        candidate_query_cards=candidate_query_cards,
    )
    client = llm_client or StubQueryPlannerLLMClient()
    plan = QueryPlan.model_validate(
        client.generate_query_plan(system_prompt=system_prompt, user_prompt=user_prompt)
    )
    validate_query_plan(plan, candidate_query_cards=candidate_query_cards)
    return plan
