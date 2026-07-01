from __future__ import annotations

import pytest

from agents.entity_resolver import resolve_entities


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def test_resolve_part_no_a123_exact_match() -> None:
    result = resolve_entities(part_no="A123")

    entity = result.entities["part_no"]
    assert entity.match_type == "exact"
    assert entity.resolved_value == "A123"


def test_resolve_project_p01_exact_match() -> None:
    result = resolve_entities(project_id="P01")

    entity = result.entities["project_id"]
    assert entity.match_type == "exact"
    assert entity.resolved_value == "P01"


def test_resolve_vendor_name_exact_match() -> None:
    result = resolve_entities(vendor_name="Acme")

    entity = result.entities["vendor_name"]
    assert entity.match_type == "exact"
    assert entity.resolved_value == "ACME"


def test_resolve_fan_motor_fuzzy_multiple_candidates_is_ambiguous() -> None:
    result = resolve_entities(part_no="風扇馬達")

    entity = result.entities["part_no"]
    assert result.status == "ambiguous"
    assert result.ambiguous == ["part_no"]
    assert entity.match_type == "ambiguous"
    assert entity.resolved_value is None
    assert {candidate["value"] for candidate in entity.candidates} == {"A123", "B456"}


def test_resolve_unknown_part_no_is_missing() -> None:
    result = resolve_entities(part_no="ZZZ999")

    entity = result.entities["part_no"]
    assert result.status == "missing"
    assert result.missing == ["part_no"]
    assert entity.match_type == "missing"
    assert entity.resolved_value is None


def test_resolve_vendor_not_provided() -> None:
    result = resolve_entities(part_no="A123")

    entity = result.entities["vendor_name"]
    assert result.status == "resolved"
    assert entity.match_type == "not_provided"
    assert entity.resolved_value is None
    assert entity.candidates == []
