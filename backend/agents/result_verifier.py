from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResultVerification(BaseModel):
    ok: bool
    status: str
    row_count: int
    empty_result: bool
    over_limit: bool
    required_columns_exist: bool
    output_schema_valid: bool
    deterministic_summary: dict[str, Any] | list[Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError("value must be a dict or Pydantic model")


def _field(query_card: dict[str, Any], name: str, default: Any = None) -> Any:
    return query_card.get(name, default)


def _empty_answer(query_card: dict[str, Any]) -> str | None:
    policy = query_card.get("empty_result_policy")
    if isinstance(policy, dict):
        return policy.get("answer")
    if hasattr(policy, "answer"):
        return policy.answer
    return None


def _matches_type(value: Any, expected: str) -> bool:
    normalized = expected.strip().casefold()
    if normalized in {"any", "unknown"}:
        return True
    if normalized in {"str", "string", "text"}:
        return isinstance(value, str)
    if normalized in {"int", "integer"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"float", "number", "numeric", "decimal"}:
        return (isinstance(value, int | float) and not isinstance(value, bool))
    if normalized in {"bool", "boolean"}:
        return isinstance(value, bool)
    if normalized in {"list", "array"}:
        return isinstance(value, list)
    if normalized in {"dict", "object", "json"}:
        return isinstance(value, dict)
    return True


def _deterministic_summary(
    *, rows: list[dict[str, Any]], row_count: int, row_limit: int | None
) -> dict[str, Any]:
    preview_limit = min(row_limit or 5, 5)
    return {
        "row_count": row_count,
        "preview_count": min(len(rows), preview_limit),
        "preview": rows[:preview_limit],
    }


def verify_query_result(
    *,
    query_result: dict[str, Any] | BaseModel,
    query_card: dict[str, Any] | BaseModel,
) -> ResultVerification:
    result = _as_dict(query_result)
    card = _as_dict(query_card)
    warnings: list[str] = []

    status = str(result.get("status") or "")
    status_success = status in {"success", "ok"}
    rows = result.get("data") or []
    if not isinstance(rows, list):
        rows = []
        warnings.append("data is not a list")

    row_count = int(result.get("row_count") or len(rows))
    empty_result = row_count == 0
    row_limit = _field(card, "row_limit")
    over_limit = row_limit is not None and row_count > int(row_limit)

    output_schema = _field(card, "output_schema", {}) or {}
    expected_columns = set(output_schema)
    row_columns = set().union(*(row.keys() for row in rows if isinstance(row, dict)))
    required_columns_exist = expected_columns.issubset(row_columns) if rows else True

    output_schema_valid = required_columns_exist
    for row in rows:
        if not isinstance(row, dict):
            output_schema_valid = False
            continue
        for column, expected_type in output_schema.items():
            if column not in row or not _matches_type(row[column], str(expected_type)):
                output_schema_valid = False

    deterministic_summary: dict[str, Any] | list[Any] | None = None
    if empty_result:
        answer = _empty_answer(card)
        deterministic_summary = {"empty_result_answer": answer} if answer else None
    elif over_limit:
        warnings.append(f"row_count exceeds row_limit={row_limit}")
        deterministic_summary = _deterministic_summary(
            rows=[row for row in rows if isinstance(row, dict)],
            row_count=row_count,
            row_limit=int(row_limit) if row_limit is not None else None,
        )

    error = result.get("error")
    if not status_success:
        error = str(error or f"query_result status is not success: {status}")
    elif not output_schema_valid:
        error = "query_result does not match output_schema"

    ok = status_success and output_schema_valid
    return ResultVerification(
        ok=ok,
        status=status,
        row_count=row_count,
        empty_result=empty_result,
        over_limit=over_limit,
        required_columns_exist=required_columns_exist,
        output_schema_valid=output_schema_valid,
        deterministic_summary=deterministic_summary,
        warnings=warnings,
        error=error,
    )
