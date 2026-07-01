from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SynthesisResult(BaseModel):
    final_answer: str


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError("value must be a dict or Pydantic model")


def _evidence_text(evidence_pack: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in evidence_pack:
        text = item.get("text") or item.get("content") or item.get("summary")
        if text:
            evidence_id = item.get("id") or item.get("evidence_id")
            prefix = f"[{evidence_id}] " if evidence_id else ""
            parts.append(f"{prefix}{text}")
    return "\n".join(parts) if parts else "目前沒有可用文件依據。"


def _format_conditions(arguments: dict[str, Any]) -> str:
    if not arguments:
        return "查詢條件：未提供"
    rendered = ", ".join(f"{key}={value}" for key, value in sorted(arguments.items()))
    return f"查詢條件：{rendered}"


def _format_source(source: dict[str, Any]) -> str:
    if not source:
        return "資料來源：未提供"
    database = source.get("database", "unknown")
    template_id = source.get("template_id", "unknown")
    executed_at = source.get("executed_at", "unknown")
    return (
        "資料來源："
        f"database={database}, template_id={template_id}, executed_at={executed_at}"
    )


def _format_rows(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, row in enumerate(rows, start=1):
        fields = ", ".join(f"{key}: {value}" for key, value in row.items())
        lines.append(f"{idx}. {fields}")
    return "\n".join(lines)


def synthesize_answer(
    *,
    user_query: str,
    evidence_pack: list[dict[str, Any]],
    query_plan: dict[str, Any] | BaseModel,
    query_result: dict[str, Any] | BaseModel,
    result_verification: dict[str, Any] | BaseModel,
) -> SynthesisResult:
    plan = _as_dict(query_plan)
    result = _as_dict(query_result)
    verification = _as_dict(result_verification)

    decision = plan.get("decision")
    arguments = plan.get("arguments") or result.get("input") or {}

    if decision == "ask_clarification":
        missing_args = plan.get("missing_args") or []
        missing = ", ".join(str(arg) for arg in missing_args) or "必要查詢條件"
        return SynthesisResult(
            final_answer=(
                f"我需要先釐清缺少的查詢條件：{missing}。\n"
                f"{_format_conditions(arguments)}"
            )
        )

    if decision == "answer_from_docs":
        return SynthesisResult(
            final_answer=(
                "根據目前文件資料回答如下：\n"
                f"{_evidence_text(evidence_pack)}\n"
                "資料來源：evidence_pack"
            )
        )

    source = result.get("source") or {}
    conditions = _format_conditions(arguments)
    source_text = _format_source(source)

    if not verification.get("ok", False) and result.get("status") == "error":
        error = result.get("error") or verification.get("error") or "未知錯誤"
        return SynthesisResult(
            final_answer=(
                f"查詢失敗：{error}\n"
                f"{conditions}\n"
                f"{source_text}"
            )
        )

    row_count = int(result.get("row_count") or verification.get("row_count") or 0)
    if row_count == 0 or verification.get("empty_result"):
        empty_summary = verification.get("deterministic_summary") or {}
        empty_answer = empty_summary.get("empty_result_answer")
        detail = f" {empty_answer}" if empty_answer else ""
        return SynthesisResult(
            final_answer=(
                f"查無資料。{detail}\n"
                f"{conditions}\n"
                f"{source_text}"
            )
        )

    rows = [row for row in (result.get("data") or []) if isinstance(row, dict)]
    row_text = _format_rows(rows) if rows else "查詢有回傳筆數，但沒有可呈現的列資料。"
    warnings = verification.get("warnings") or result.get("warnings") or []
    warning_text = (
        "\n警告：" + "; ".join(str(warning) for warning in warnings) if warnings else ""
    )
    return SynthesisResult(
        final_answer=(
            "查詢完成，以下以 API / SQL 查詢結果為準：\n"
            f"{conditions}\n"
            f"{source_text}\n"
            f"row_count={row_count}\n"
            f"{row_text}"
            f"{warning_text}"
        )
    )
