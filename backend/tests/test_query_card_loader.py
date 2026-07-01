from __future__ import annotations

import pytest

from schemas.query_card import load_query_cards


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def _write_card(catalog_dir, filename: str, *, query_name: str = "query_bom_cost") -> None:
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / filename).write_text(
        f"""
query_name: {query_name}
title: BOM Cost
auth_scope: cost:read
description: Summarizes bill of materials cost for a product.
sql_type: select
when_to_use:
  - User asks for BOM cost.
do_not_use_when:
  - User asks for inventory availability.
required_args:
  product_id:
    type: string
    description: Product identifier.
    default:
    allowed_values:
    examples:
      - P-100
optional_args:
  currency:
    type: string
    description: Output currency.
    default: USD
    allowed_values:
      - USD
      - TWD
    examples:
      - USD
output_schema:
  product_id: string
  total_cost: number
empty_result_policy:
  answer: No BOM cost rows were found.
examples:
  - user: Show BOM cost for P-100.
    query_name: {query_name}
    arguments:
      product_id: P-100
""",
        encoding="utf-8",
    )


def test_load_query_cards_loads_query_bom_cost_yaml(tmp_path) -> None:
    catalog_dir = tmp_path / "api_catalog"
    _write_card(catalog_dir, "query_bom_cost.yaml")

    cards = load_query_cards(catalog_dir)

    assert list(cards) == ["query_bom_cost"]
    card = cards["query_bom_cost"]
    assert card.title == "BOM Cost"
    assert card.auth_scope == "cost:read"
    assert card.required_args["product_id"].examples == ["P-100"]
    assert card.optional_args["currency"].default == "USD"
    assert card.empty_result_policy.answer == "No BOM cost rows were found."
    assert card.examples[0].arguments == {"product_id": "P-100"}


def test_load_query_cards_rejects_duplicate_query_name(tmp_path) -> None:
    catalog_dir = tmp_path / "api_catalog"
    _write_card(catalog_dir, "query_bom_cost.yaml")
    _write_card(catalog_dir, "query_bom_cost_copy.yml")

    with pytest.raises(ValueError, match="Duplicate query_name: query_bom_cost"):
        load_query_cards(catalog_dir)


def test_load_query_cards_rejects_missing_required_args(tmp_path) -> None:
    catalog_dir = tmp_path / "api_catalog"
    catalog_dir.mkdir()
    (catalog_dir / "query_bom_cost.yaml").write_text(
        """
query_name: query_bom_cost
title: BOM Cost
auth_scope: cost:read
description: Summarizes bill of materials cost for a product.
sql_type: select
when_to_use:
  - User asks for BOM cost.
do_not_use_when:
  - User asks for inventory availability.
output_schema:
  product_id: string
  total_cost: number
empty_result_policy:
  answer: No BOM cost rows were found.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="required_args"):
        load_query_cards(catalog_dir)
