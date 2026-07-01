from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EntityStatus = Literal["resolved", "ambiguous", "missing"]
EntityMatchType = Literal["exact", "fuzzy", "ambiguous", "missing", "not_provided"]


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


part_no_aliases: list[dict[str, str]] = [
    {"alias": "A123", "value": "A123", "label": "Fan motor A123"},
    {"alias": "fan motor a123", "value": "A123", "label": "Fan motor A123"},
    {"alias": "風扇馬達 A123", "value": "A123", "label": "Fan motor A123"},
    {"alias": "B456", "value": "B456", "label": "Fan motor B456"},
    {"alias": "風扇馬達 B456", "value": "B456", "label": "Fan motor B456"},
    {"alias": "C789", "value": "C789", "label": "Control board C789"},
]

project_aliases: list[dict[str, str]] = [
    {"alias": "P01", "value": "P01", "label": "Project P01"},
    {"alias": "project p01", "value": "P01", "label": "Project P01"},
    {"alias": "P02", "value": "P02", "label": "Project P02"},
]

vendor_aliases: list[dict[str, str]] = [
    {"alias": "Acme", "value": "ACME", "label": "Acme Corporation"},
    {"alias": "Acme Corporation", "value": "ACME", "label": "Acme Corporation"},
    {"alias": "Globex", "value": "GLOBEX", "label": "Globex Corporation"},
]


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _candidate(row: dict[str, str]) -> dict[str, str]:
    return {
        "value": row["value"],
        "alias": row["alias"],
        "label": row["label"],
    }


def _resolve_one(value: str | None, aliases: list[dict[str, str]]) -> EntityResult:
    if value is None or not value.strip():
        return EntityResult(
            input=value,
            resolved_value=None,
            match_type="not_provided",
        )

    normalized = _normalize(value)
    exact_matches = [row for row in aliases if _normalize(row["alias"]) == normalized]
    exact_values = {row["value"] for row in exact_matches}
    if len(exact_values) == 1:
        return EntityResult(
            input=value,
            resolved_value=next(iter(exact_values)),
            match_type="exact",
            candidates=[_candidate(row) for row in exact_matches],
        )
    if len(exact_values) > 1:
        return EntityResult(
            input=value,
            resolved_value=None,
            match_type="ambiguous",
            candidates=[_candidate(row) for row in exact_matches],
        )

    fuzzy_matches = [
        row
        for row in aliases
        if normalized in _normalize(row["alias"]) or _normalize(row["alias"]) in normalized
    ]
    fuzzy_by_value = {row["value"]: row for row in fuzzy_matches}
    if len(fuzzy_by_value) == 1:
        row = next(iter(fuzzy_by_value.values()))
        return EntityResult(
            input=value,
            resolved_value=row["value"],
            match_type="fuzzy",
            candidates=[_candidate(row)],
        )
    if len(fuzzy_by_value) > 1:
        return EntityResult(
            input=value,
            resolved_value=None,
            match_type="ambiguous",
            candidates=[_candidate(row) for row in fuzzy_by_value.values()],
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
        "part_no": _resolve_one(part_no, part_no_aliases),
        "project_id": _resolve_one(project_id, project_aliases),
        "vendor_name": _resolve_one(vendor_name, vendor_aliases),
    }
    ambiguous = [
        name for name, result in entities.items() if result.match_type == "ambiguous"
    ]
    missing = [name for name, result in entities.items() if result.match_type == "missing"]

    if ambiguous:
        status: EntityStatus = "ambiguous"
    elif missing:
        status = "missing"
    else:
        status = "resolved"

    return EntityResolutionResult(
        status=status,
        entities=entities,
        ambiguous=ambiguous,
        missing=missing,
    )
