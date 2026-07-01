from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_servers.business_query_server import MockDatabaseClient, query_bom_cost
from sql_templates.registry import get_sql_template


@pytest.fixture(scope="session", autouse=True)
def _run_migrations() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_db() -> None:
    pass


@pytest.fixture(autouse=True)
def _patch_app_storage() -> None:
    pass


def test_query_bom_cost_returns_one_row() -> None:
    db_client = MockDatabaseClient(
        rows=[
            {
                "part_no": "A123",
                "component_part_no": "C001",
                "quantity": 2,
                "unit_cost": 10,
                "extended_cost": 20,
            }
        ]
    )

    response = query_bom_cost({"part_no": "A123"}, db_client=db_client)

    assert response.query_name == "query_bom_cost"
    assert response.status == "ok"
    assert response.row_count == 1
    assert response.data[0]["part_no"] == "A123"
    assert response.error is None


def test_query_bom_cost_returns_zero_rows_when_empty() -> None:
    db_client = MockDatabaseClient(rows=[])

    response = query_bom_cost({"part_no": "A123"}, db_client=db_client)

    assert response.status == "ok"
    assert response.row_count == 0
    assert response.columns == []
    assert response.data == []


def test_query_bom_cost_rejects_raw_sql_argument() -> None:
    with pytest.raises(ValidationError):
        query_bom_cost({"part_no": "A123", "raw_sql": "SELECT * FROM bom_items"})


def test_query_bom_cost_uses_registry_template_id() -> None:
    db_client = MockDatabaseClient(rows=[])
    template = get_sql_template("query_bom_cost")

    response = query_bom_cost({"part_no": "A123"}, db_client=db_client)

    assert response.source.template_id == template.template_id
    assert db_client.calls[0]["sql"] == template.sql


def test_query_bom_cost_uses_template_timeout_sec() -> None:
    db_client = MockDatabaseClient(rows=[])
    template = get_sql_template("query_bom_cost")

    query_bom_cost({"part_no": "A123"}, db_client=db_client)

    assert db_client.calls[0]["timeout_sec"] == template.timeout_sec
