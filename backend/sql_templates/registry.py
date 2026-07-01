from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SqlTemplate:
    template_id: str
    query_name: str
    version: str
    sql: str
    allowed_params: tuple[str, ...]
    row_limit: int | None = None
    timeout_sec: int | None = None


_NAMED_PARAM_RE = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
_SELECT_RE = re.compile(r"^\s*(?:--[^\n]*\n\s*)*select\b", re.IGNORECASE)
_PYFORMAT_PARAM_RE = re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)s")
_FORMAT_PARAM_RE = re.compile(r"(?<!%)%s")
_DOLLAR_PARAM_RE = re.compile(r"\$[1-9][0-9]*")
_MULTI_STATEMENT_RE = re.compile(r";\s*\S")


def _strip_sql_literals_and_comments(sql: str) -> str:
    parts: list[str] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if char == "-" and next_char == "-":
            end = sql.find("\n", i + 2)
            if end == -1:
                break
            parts.append("\n")
            i = end + 1
            continue

        if char == "/" and next_char == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                parts.append(" ")
                break
            parts.append(" ")
            i = end + 2
            continue

        if char == "'":
            parts.append(" ")
            i += 1
            while i < len(sql):
                if sql[i] == "'":
                    if i + 1 < len(sql) and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        parts.append(char)
        i += 1

    return "".join(parts)


def _named_params(sql: str) -> set[str]:
    clean_sql = _strip_sql_literals_and_comments(sql)
    return set(_NAMED_PARAM_RE.findall(clean_sql))


def validate_sql_template(template: SqlTemplate) -> None:
    if not template.template_id.strip():
        raise ValueError("template_id must not be empty")
    if not template.query_name.strip():
        raise ValueError("query_name must not be empty")
    if not template.sql.strip():
        raise ValueError("sql must not be empty")
    if not template.allowed_params:
        raise ValueError("allowed_params must not be empty")
    if template.row_limit is None or template.row_limit <= 0:
        raise ValueError("row_limit must be greater than 0")
    if template.timeout_sec is None or template.timeout_sec <= 0:
        raise ValueError("timeout_sec must be greater than 0")

    allowed_params = set(template.allowed_params)
    if "raw_sql" in allowed_params:
        raise ValueError("allowed_params must not contain raw_sql")

    clean_sql = _strip_sql_literals_and_comments(template.sql)
    if (
        "?" in clean_sql
        or _PYFORMAT_PARAM_RE.search(clean_sql)
        or _FORMAT_PARAM_RE.search(clean_sql)
        or _DOLLAR_PARAM_RE.search(clean_sql)
    ):
        raise ValueError("SQL parameters must use named parameters like :part_no")

    sql_params = _named_params(template.sql)
    undeclared_params = sql_params - allowed_params
    if undeclared_params:
        names = ", ".join(sorted(undeclared_params))
        raise ValueError(f"SQL uses undeclared named parameters: {names}")

    if _MULTI_STATEMENT_RE.search(clean_sql):
        raise ValueError("SQL template must not contain multiple statements")

    if not _SELECT_RE.search(clean_sql):
        raise ValueError("Only SELECT SQL templates are allowed")


def _registry(items: tuple[SqlTemplate, ...]) -> dict[str, SqlTemplate]:
    templates: dict[str, SqlTemplate] = {}
    for template in items:
        validate_sql_template(template)
        if template.query_name in templates:
            raise ValueError(f"Duplicate SQL template query_name: {template.query_name}")
        templates[template.query_name] = template
    return templates


SQL_TEMPLATE_REGISTRY: dict[str, SqlTemplate] = _registry(
    (
        SqlTemplate(
            template_id="query_bom_cost:v1",
            query_name="query_bom_cost",
            version="v1",
            sql="""
SELECT
    b.part_no,
    b.component_part_no,
    b.quantity,
    c.unit_cost,
    b.quantity * c.unit_cost AS extended_cost
FROM bom_items b
JOIN component_costs c ON c.part_no = b.component_part_no
WHERE b.part_no = :part_no
ORDER BY b.component_part_no
""",
            allowed_params=("part_no",),
            row_limit=500,
            timeout_sec=10,
        ),
    )
)


def get_sql_template(query_name: str) -> SqlTemplate:
    try:
        return SQL_TEMPLATE_REGISTRY[query_name]
    except KeyError as exc:
        raise KeyError(f"SQL template not found for query_name: {query_name}") from exc
