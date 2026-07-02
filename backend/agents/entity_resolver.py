from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


EntityStatus = Literal["resolved", "missing"]
EntityMatchType = Literal["pattern", "missing", "not_provided"]


class EntityResult(BaseModel):
    input: str | None
    resolved_value: str | None
    match_type: EntityMatchType
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class EntityResolutionResult(BaseModel):
    status: EntityStatus
    entities: dict[str, EntityResult]
    ambiguous: list[str]
    missing: list[str]


PART_NO_PATTERN = re.compile(r"^[A-Z]{4}\d{2}$", flags=re.IGNORECASE)
PROJECT_ID_PATTERN = re.compile(
    r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9][A-Z0-9_-]*$", flags=re.IGNORECASE
)


def _resolve_by_pattern(
    value: str | None,
    *,
    pattern: re.Pattern[str] | None,
    normalize_value: bool = True,
) -> EntityResult:
    if value is None or not value.strip():
        return EntityResult(
            input=value,
            resolved_value=None,
            match_type="not_provided",
        )

    clean_value = value.strip()
    if pattern is not None and pattern.fullmatch(clean_value):
        resolved_value = clean_value.upper() if normalize_value else clean_value
        return EntityResult(
            input=value,
            resolved_value=resolved_value,
            match_type="pattern",
            candidates=[
                {
                    "value": resolved_value,
                    "alias": clean_value,
                    "label": resolved_value,
                }
            ],
        )

    return EntityResult(
        input=value,
        resolved_value=None,
        match_type="missing",
    )


def resolve_entities(
    *,
    part_no: str | None = None,
    project_id: str | None = None,
    vendor_name: str | None = None,
) -> EntityResolutionResult:
    entities = {
        "part_no": _resolve_by_pattern(part_no, pattern=PART_NO_PATTERN),
        "project_id": _resolve_by_pattern(project_id, pattern=PROJECT_ID_PATTERN),
        "vendor_name": _resolve_by_pattern(vendor_name, pattern=None),
    }
    missing = [name for name, result in entities.items() if result.match_type == "missing"]
    status: EntityStatus = "missing" if missing else "resolved"

    return EntityResolutionResult(
        status=status,
        entities=entities,
        ambiguous=[],
        missing=missing,
    )
