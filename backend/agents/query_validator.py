from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from agents.query_planner import QueryPlan
from sql_templates.registry import SqlTemplate, validate_sql_template


ValidatorAction = Literal["execute", "ask_clarification", "reject"]
EXECUTABLE_HANDLER_KEYS = {"llm_info", "query_bom_cost"}


class QueryValidationResult(BaseModel):
    ok: bool
    query_name: str | None
    normalized_arguments: dict[str, Any]
    checks: dict[str, bool]
    reason: str
    error: str | None = None
    action: ValidatorAction


def _candidate_query_names(candidate_query_cards: list[dict[str, Any]]) -> set[str]:
    return {
        str(card["query_name"])
        for card in candidate_query_cards
        if card.get("query_name") is not None
    }


def _candidate_card(
    query_name: str | None, candidate_query_cards: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if query_name is None:
        return None
    return next(
        (card for card in candidate_query_cards if card.get("query_name") == query_name),
        None,
    )


def _required_arg_names(card: dict[str, Any] | None) -> list[str]:
    if card is None:
        return []
    required_args = card.get("required_args") or {}
    if isinstance(required_args, dict):
        return list(required_args)
    if isinstance(required_args, list):
        return [str(item) for item in required_args]
    return []


def _optional_arg_names(card: dict[str, Any] | None) -> list[str]:
    if card is None:
        return []
    optional_args = card.get("optional_args") or {}
    if isinstance(optional_args, dict):
        return list(optional_args)
    if isinstance(optional_args, list):
        return [str(item) for item in optional_args]
    return []


def _contains_raw_sql(value: Any) -> bool:
    if isinstance(value, dict):
        return any(k == "raw_sql" or _contains_raw_sql(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_raw_sql(item) for item in value)
    return False


def _arg_specs(card: dict[str, Any] | None) -> dict[str, Any]:
    if card is None:
        return {}
    specs: dict[str, Any] = {}
    for group_name in ("required_args", "optional_args"):
        group = card.get(group_name) or {}
        if isinstance(group, dict):
            specs.update(group)
    return specs


def _arg_type(spec: Any) -> str:
    if isinstance(spec, dict):
        return str(spec.get("type") or "any")
    if hasattr(spec, "type"):
        return str(spec.type)
    return str(spec or "any")


def _matches_type(value: Any, expected: str) -> bool:
    normalized = expected.strip().casefold()
    if normalized in {"any", "unknown"}:
        return True
    if normalized in {"str", "string", "text"}:
        return isinstance(value, str)
    if normalized in {"int", "integer"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"float", "number", "numeric", "decimal"}:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if normalized in {"bool", "boolean"}:
        return isinstance(value, bool)
    if normalized in {"list", "array"}:
        return isinstance(value, list)
    if normalized in {"dict", "object", "json"}:
        return isinstance(value, dict)
    if normalized.endswith(" | null") or normalized.endswith(" or null"):
        base = normalized.replace(" | null", "").replace(" or null", "")
        return value is None or _matches_type(value, base)
    return True


def _validate_arguments(
    *,
    candidate_card: dict[str, Any] | None,
    arguments: dict[str, Any],
) -> tuple[bool, dict[str, Any], str | None]:
    if candidate_card is None:
        return False, {}, "query card not found for argument validation"

    specs = _arg_specs(candidate_card)
    allowed_args = set(specs)
    required_args = set(_required_arg_names(candidate_card))
    normalized: dict[str, Any] = {}

    for name in required_args:
        if name not in arguments or arguments[name] in (None, ""):
            return False, normalized, f"missing required argument: {name}"

    for name, value in arguments.items():
        if name not in allowed_args:
            return False, {}, f"unknown argument: {name}"
        if value is None:
            normalized[name] = value
            continue
        expected = _arg_type(specs[name])
        if not _matches_type(value, expected):
            return False, {}, f"argument {name} must be {expected}"
        normalized[name] = value

    return True, normalized, None


def _validate_template(template: SqlTemplate | None) -> tuple[bool, str | None]:
    if template is None:
        return False, "SQL template not found"
    try:
        validate_sql_template(template)
    except ValueError as exc:
        return False, str(exc)
    return True, None


def validate_query_plan(
    *,
    query_plan: QueryPlan | dict[str, Any],
    candidate_query_cards: list[dict[str, Any]],
    sql_template_registry: dict[str, SqlTemplate],
    query_arg_schema_map: dict[str, type[BaseModel]] | None = None,
) -> QueryValidationResult:
    plan = (
        query_plan
        if isinstance(query_plan, QueryPlan)
        else QueryPlan.model_validate(query_plan)
    )
    query_name = plan.query_name
    candidate_card = _candidate_card(query_name, candidate_query_cards)
    template = sql_template_registry.get(query_name or "")
    handler_key = str((candidate_card or {}).get("handler_key") or "")
    transport = str((candidate_card or {}).get("transport") or "in-process")
    is_http_tool = transport == "http"
    requires_sql_template = handler_key == "query_bom_cost" or (
        not handler_key and not is_http_tool
    )

    query_exists_in_registry = (query_name in sql_template_registry) if requires_sql_template else True
    query_exists_in_candidate_cards = query_name in _candidate_query_names(
        candidate_query_cards
    )
    required_args = _required_arg_names(candidate_card)
    required_args_complete = all(
        arg in plan.arguments and plan.arguments[arg] not in (None, "")
        for arg in required_args
    )
    confidence_passed = plan.confidence >= 0.7
    raw_sql_absent = not _contains_raw_sql(plan.arguments)
    sql_template_valid, template_error = (
        _validate_template(template) if requires_sql_template else (True, None)
    )
    handler_valid = (
        plan.decision != "call_query_template"
        or handler_key in EXECUTABLE_HANDLER_KEYS
        or is_http_tool
        or requires_sql_template
    )

    schema_valid = False
    normalized_arguments: dict[str, Any] = {}
    schema_error: str | None = None
    if raw_sql_absent:
        schema_valid, normalized_arguments, schema_error = _validate_arguments(
            candidate_card=candidate_card,
            arguments=plan.arguments,
        )

    checks = {
        "query_exists_in_registry": query_exists_in_registry,
        "query_exists_in_candidate_cards": query_exists_in_candidate_cards,
        "required_args_complete": required_args_complete,
        "pydantic_schema_valid": schema_valid,
        "confidence_passed": confidence_passed,
        "raw_sql_absent": raw_sql_absent,
        "sql_template_valid": sql_template_valid,
        "handler_valid": handler_valid,
    }

    if plan.decision == "answer_from_docs":
        return QueryValidationResult(
            ok=False,
            query_name=query_name,
            normalized_arguments={},
            checks=checks,
            reason="Query plan answers from documents and must not execute a query.",
            action="reject",
        )

    if plan.decision == "ask_clarification":
        return QueryValidationResult(
            ok=False,
            query_name=query_name,
            normalized_arguments=normalized_arguments,
            checks=checks,
            reason="Query plan asks for clarification and must not execute a query.",
            error=schema_error,
            action="ask_clarification",
        )

    failures: list[str] = [name for name, passed in checks.items() if not passed]
    if failures:
        error = "; ".join(failures)
        details = "; ".join(
            detail for detail in (schema_error, template_error) if detail is not None
        )
        if details:
            error = f"{error}: {details}"
        action: ValidatorAction = (
            "ask_clarification"
            if "required_args_complete" in failures
            else "reject"
        )
        return QueryValidationResult(
            ok=False,
            query_name=query_name,
            normalized_arguments=normalized_arguments,
            checks=checks,
            reason="Query plan failed validation.",
            error=error,
            action=action,
        )

    return QueryValidationResult(
        ok=True,
        query_name=query_name,
        normalized_arguments=normalized_arguments,
        checks=checks,
        reason="Query plan passed validation.",
        action="execute",
    )
