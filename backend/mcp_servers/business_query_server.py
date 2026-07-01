from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sql_templates.registry import get_sql_template, validate_sql_template


class DatabaseClient(Protocol):
    database: str

    def execute_prepared(
        self, sql: str, params: dict[str, Any], timeout_sec: int
    ) -> list[dict[str, Any]]:
        """Execute one registry-owned SQL template with named parameters only."""


class MockDatabaseClient:
    database = "mock"

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[dict[str, Any]] = []

    def execute_prepared(
        self, sql: str, params: dict[str, Any], timeout_sec: int
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "sql": sql,
                "params": params,
                "timeout_sec": timeout_sec,
            }
        )
        return list(self.rows)


class QueryBomCostArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_no: str = Field(min_length=1)


class QueryProjectSpecArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)


class QueryVendorQuoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str = Field(min_length=1)
    part_no: str | None = Field(default=None, min_length=1)


class QuerySource(BaseModel):
    database: str
    template_id: str | None
    executed_at: str


class BusinessQueryResponse(BaseModel):
    query_name: str
    status: str
    input: dict[str, Any]
    row_count: int
    columns: list[str]
    data: list[dict[str, Any]]
    source: QuerySource
    warnings: list[str]
    error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for name in row:
            if name not in seen:
                seen.add(name)
                columns.append(name)
    return columns


def _response(
    *,
    query_name: str,
    status: str,
    input_args: dict[str, Any],
    rows: list[dict[str, Any]],
    database: str,
    template_id: str | None,
    warnings: list[str] | None = None,
    error: str | None = None,
) -> BusinessQueryResponse:
    return BusinessQueryResponse(
        query_name=query_name,
        status=status,
        input=input_args,
        row_count=len(rows),
        columns=_columns(rows),
        data=rows,
        source=QuerySource(
            database=database,
            template_id=template_id,
            executed_at=_now_iso(),
        ),
        warnings=warnings or [],
        error=error,
    )


def _execute_template(
    *,
    query_name: str,
    args: BaseModel,
    db_client: DatabaseClient,
) -> BusinessQueryResponse:
    template = get_sql_template(query_name)
    validate_sql_template(template)

    input_args = args.model_dump(exclude_none=True)
    if "raw_sql" in input_args:
        raise ValueError("raw_sql is not allowed")

    params = {name: input_args[name] for name in template.allowed_params}
    rows = db_client.execute_prepared(
        template.sql,
        params,
        timeout_sec=int(template.timeout_sec or 0),
    )

    warnings: list[str] = []
    if template.row_limit is not None and len(rows) > template.row_limit:
        rows = rows[: template.row_limit]
        warnings.append(f"Result truncated to row_limit={template.row_limit}")

    return _response(
        query_name=query_name,
        status="ok",
        input_args=input_args,
        rows=rows,
        database=getattr(db_client, "database", "unknown"),
        template_id=template.template_id,
        warnings=warnings,
    )


def query_bom_cost(
    args: QueryBomCostArgs | dict[str, Any],
    *,
    db_client: DatabaseClient | None = None,
) -> BusinessQueryResponse:
    parsed_args = QueryBomCostArgs.model_validate(args)
    return _execute_template(
        query_name="query_bom_cost",
        args=parsed_args,
        db_client=db_client or MockDatabaseClient(),
    )


def query_project_spec(
    args: QueryProjectSpecArgs | dict[str, Any],
    *,
    db_client: DatabaseClient | None = None,
) -> BusinessQueryResponse:
    parsed_args = QueryProjectSpecArgs.model_validate(args)
    return _response(
        query_name="query_project_spec",
        status="not_implemented",
        input_args=parsed_args.model_dump(exclude_none=True),
        rows=[],
        database=getattr(db_client or MockDatabaseClient(), "database", "unknown"),
        template_id=None,
        warnings=["TODO: add query_project_spec SQL template to registry."],
        error="not_implemented",
    )


def query_vendor_quote(
    args: QueryVendorQuoteArgs | dict[str, Any],
    *,
    db_client: DatabaseClient | None = None,
) -> BusinessQueryResponse:
    parsed_args = QueryVendorQuoteArgs.model_validate(args)
    return _response(
        query_name="query_vendor_quote",
        status="not_implemented",
        input_args=parsed_args.model_dump(exclude_none=True),
        rows=[],
        database=getattr(db_client or MockDatabaseClient(), "database", "unknown"),
        template_id=None,
        warnings=["TODO: add query_vendor_quote SQL template to registry."],
        error="not_implemented",
    )
