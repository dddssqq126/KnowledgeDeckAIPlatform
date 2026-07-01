from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError


class QueryArgSpec(BaseModel):
    type: str
    description: str | None = None
    default: Any | None = None
    allowed_values: list[Any] | None = None
    examples: list[Any] | None = None


class EmptyResultPolicy(BaseModel):
    answer: str


class QueryExample(BaseModel):
    user: str
    query_name: str
    arguments: dict[str, Any]


class QueryCard(BaseModel):
    query_name: str
    title: str
    auth_scope: str
    description: str
    sql_type: str
    when_to_use: list[str]
    do_not_use_when: list[str]
    required_args: dict[str, QueryArgSpec]
    optional_args: dict[str, QueryArgSpec] = Field(default_factory=dict)
    output_schema: dict[str, str]
    empty_result_policy: EmptyResultPolicy
    examples: list[QueryExample] = Field(default_factory=list)


def load_query_cards(catalog_dir: str | Path) -> dict[str, QueryCard]:
    catalog_path = Path(catalog_dir)
    if not catalog_path.is_dir():
        raise ValueError(f"catalog_dir does not exist or is not a directory: {catalog_path}")

    cards: dict[str, QueryCard] = {}
    for path in sorted([*catalog_path.glob("*.yaml"), *catalog_path.glob("*.yml")]):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in query card {path}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"Query card {path} must contain a YAML object")

        try:
            card = QueryCard.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid query card {path}: {exc}") from exc

        if card.query_name in cards:
            raise ValueError(f"Duplicate query_name: {card.query_name}")
        cards[card.query_name] = card

    return cards
