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


def test_resolve_pattern_part_no() -> None:
    result = resolve_entities(part_no="abcd12")

    entity = result.entities["part_no"]
    assert result.status == "resolved"
    assert entity.match_type == "pattern"
    assert entity.resolved_value == "ABCD12"


def test_resolve_part_no_does_not_use_old_alias() -> None:
    result = resolve_entities(part_no="A123")

    entity = result.entities["part_no"]
    assert result.status == "missing"
    assert result.missing == ["part_no"]
    assert entity.match_type == "missing"
    assert entity.resolved_value is None


def test_resolve_project_alphanumeric() -> None:
    result = resolve_entities(project_id="123a")

    entity = result.entities["project_id"]
    assert result.status == "resolved"
    assert entity.match_type == "pattern"
    assert entity.resolved_value == "123A"


def test_resolve_non_pattern_text_is_missing_not_fuzzy() -> None:
    result = resolve_entities(part_no="風扇馬達")

    entity = result.entities["part_no"]
    assert result.status == "missing"
    assert result.ambiguous == []
    assert result.missing == ["part_no"]
    assert entity.match_type == "missing"
    assert entity.resolved_value is None
    assert entity.candidates == []


def test_resolve_vendor_not_provided() -> None:
    result = resolve_entities(part_no="ABCD12")

    entity = result.entities["vendor_name"]
    assert result.status == "resolved"
    assert entity.match_type == "not_provided"
    assert entity.resolved_value is None
    assert entity.candidates == []


def test_resolve_vendor_does_not_use_old_alias() -> None:
    result = resolve_entities(vendor_name="Acme")

    entity = result.entities["vendor_name"]
    assert result.status == "missing"
    assert result.missing == ["vendor_name"]
    assert entity.match_type == "missing"
    assert entity.resolved_value is None
