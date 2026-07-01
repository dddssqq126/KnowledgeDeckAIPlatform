from __future__ import annotations

from dataclasses import replace

import pytest

from sql_templates.registry import (
    SqlTemplate,
    get_sql_template,
    validate_sql_template,
)


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def _valid_template() -> SqlTemplate:
    return SqlTemplate(
        template_id="query_test:v1",
        query_name="query_test",
        version="v1",
        sql="SELECT id, name FROM parts WHERE part_no = :part_no",
        allowed_params=("part_no",),
        row_limit=100,
        timeout_sec=5,
    )


def test_get_sql_template_returns_query_bom_cost() -> None:
    template = get_sql_template("query_bom_cost")

    assert template.query_name == "query_bom_cost"
    assert template.template_id == "query_bom_cost:v1"
    assert template.row_limit == 500
    assert template.timeout_sec == 10


def test_get_sql_template_rejects_unknown_query_name() -> None:
    with pytest.raises(KeyError, match="SQL template not found"):
        get_sql_template("does_not_exist")


def test_validate_sql_template_rejects_missing_row_limit() -> None:
    template = replace(_valid_template(), row_limit=None)

    with pytest.raises(ValueError, match="row_limit"):
        validate_sql_template(template)


def test_validate_sql_template_rejects_raw_sql_param() -> None:
    template = replace(_valid_template(), allowed_params=("part_no", "raw_sql"))

    with pytest.raises(ValueError, match="raw_sql"):
        validate_sql_template(template)


def test_validate_sql_template_rejects_undeclared_named_parameter() -> None:
    template = replace(
        _valid_template(),
        sql="SELECT id FROM parts WHERE part_no = :part_no AND site = :site",
    )

    with pytest.raises(ValueError, match="site"):
        validate_sql_template(template)


def test_validate_sql_template_rejects_non_select_sql() -> None:
    template = replace(
        _valid_template(),
        sql="UPDATE parts SET name = :name WHERE part_no = :part_no",
        allowed_params=("name", "part_no"),
    )

    with pytest.raises(ValueError, match="Only SELECT"):
        validate_sql_template(template)
