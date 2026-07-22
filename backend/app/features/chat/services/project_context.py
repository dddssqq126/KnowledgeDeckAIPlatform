"""Extract project identifiers from a user query and load matching metadata."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ProjectInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectEntities:
    customer_code: str | None = None
    customer: str | None = None
    project: str | None = None
    model_id: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any((self.customer_code, self.customer, self.project, self.model_id))


_ENTITY_HINT = re.compile(
    r"customer|client|project|model(?:\s*id)?|客戶|客户|專案|项目|型號|型号",
    re.IGNORECASE,
)
_EXTRACT_SYSTEM = """Extract identifiers explicitly mentioned in the user query.
Return JSON only, using exactly these nullable string keys:
{"customer_code": null, "customer": null, "project": null, "model_id": null}
customer_code is an explicitly labelled customer/client code, customer is a
customer/client/company name, project is a project name, and model_id is a
product/model identifier. Never infer a value that the user did not state."""

_CATALOG_FIELDS = (
    ProjectInfo.customer_code,
    ProjectInfo.customer_name,
    ProjectInfo.project_name,
    ProjectInfo.model_id,
)


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("'\"`，。,:：;；")
    return cleaned[:200] if cleaned else None


def _parse_entities(content: str) -> ProjectEntities:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("entity extractor response must be an object")
    return ProjectEntities(
        customer_code=_clean(parsed.get("customer_code")),
        customer=_clean(parsed.get("customer")),
        project=_clean(parsed.get("project")),
        model_id=_clean(parsed.get("model_id")),
    )


async def extract_project_entities(user_query: str) -> ProjectEntities:
    """Extract explicit customer/project/model values, failing closed to no lookup."""
    # Most chat turns contain no project vocabulary. Avoid an unnecessary model
    # request in that common case while supporting both English and Chinese labels.
    if not _ENTITY_HINT.search(user_query):
        return ProjectEntities()

    settings = get_settings()
    try:
        extractor = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            streaming=False,
            temperature=0,
            max_tokens=128,
        )
        result = await extractor.ainvoke(
            [SystemMessage(content=_EXTRACT_SYSTEM), HumanMessage(content=user_query)]
        )
        return _parse_entities(str(result.content or ""))
    except Exception:
        logger.exception("project_entity_extraction_failed; skipping project lookup")
        return ProjectEntities()


async def find_project_info(
    session: AsyncSession, entities: ProjectEntities
) -> list[ProjectInfo]:
    """Return one specific match, or the five newest customer-only matches."""
    if entities.customer_code:
        statement = (
            select(ProjectInfo)
            .where(
                func.lower(ProjectInfo.customer_code)
                == entities.customer_code.casefold()
            )
            .order_by(ProjectInfo.updated_at.desc(), ProjectInfo.id.desc())
            .limit(5)
        )
        return list((await session.scalars(statement)).all())

    if entities.model_id:
        statement = select(ProjectInfo).where(
            func.lower(ProjectInfo.model_id) == entities.model_id.casefold()
        )
        if entities.project:
            statement = statement.where(
                func.lower(ProjectInfo.project_name) == entities.project.casefold()
            )
        if entities.customer:
            statement = statement.where(
                func.lower(ProjectInfo.customer_name) == entities.customer.casefold()
            )
        return list(
            (
                await session.scalars(
                    statement.order_by(ProjectInfo.id.desc()).limit(1)
                )
            ).all()
        )

    if entities.project:
        statement = select(ProjectInfo).where(
            func.lower(ProjectInfo.project_name) == entities.project.casefold()
        )
        if entities.customer:
            statement = statement.where(
                func.lower(ProjectInfo.customer_name) == entities.customer.casefold()
            )
        return list(
            (
                await session.scalars(
                    statement.order_by(ProjectInfo.id.desc()).limit(1)
                )
            ).all()
        )

    if entities.customer:
        statement = (
            select(ProjectInfo)
            .where(
                func.lower(ProjectInfo.customer_name) == entities.customer.casefold()
            )
            .order_by(ProjectInfo.updated_at.desc(), ProjectInfo.id.desc())
            .limit(5)
        )
        return list((await session.scalars(statement)).all())
    return []


def _normalize_for_match(value: str) -> str:
    """Normalize case, full-width characters and separators for name matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _catalog_value_is_in_query(
    *, query: str, value: str, identifier: bool = False
) -> bool:
    if identifier:
        normalized_query = unicodedata.normalize("NFKC", query).casefold()
        normalized_value = unicodedata.normalize("NFKC", value).casefold().strip()
        if not normalized_value:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_value)}(?![a-z0-9])"
        return re.search(pattern, normalized_query) is not None
    normalized_value = _normalize_for_match(value)
    if len(normalized_value) < 2:
        return False
    return normalized_value in _normalize_for_match(query)


async def resolve_entities_from_catalog(
    session: AsyncSession, user_query: str
) -> ProjectEntities | None:
    """Resolve known DB values in the query, preferring the most specific match.

    The catalog is intentionally read from the source of truth on each request:
    roughly 2,000 narrow rows are cheap to scan and this avoids stale process-local
    caches. If equally strong values point to different entities, return ``None``
    and let the LLM fallback disambiguate instead of choosing arbitrarily.
    """
    catalog = (await session.execute(select(*_CATALOG_FIELDS))).all()
    # Model and project identify one row. Customer code/name identify a customer
    # and therefore preserve the existing five-project behavior.
    field_specs = (
        ("model_id", 4, 3),
        ("project", 3, 2),
        ("customer_code", 2, 0),
        ("customer", 1, 1),
    )
    matches: list[tuple[int, int, str, str]] = []
    for row in catalog:
        values = tuple(row)
        for entity_field, priority, column_index in field_specs:
            value = values[column_index]
            if value and _catalog_value_is_in_query(
                query=user_query,
                value=value,
                identifier=entity_field in {"model_id", "customer_code"},
            ):
                matches.append(
                    (priority, len(_normalize_for_match(value)), entity_field, value)
                )

    if not matches:
        return None
    best_score = max((priority, length) for priority, length, _, _ in matches)
    best = {
        (field, value.casefold()): value
        for priority, length, field, value in matches
        if (priority, length) == best_score
    }
    if len(best) != 1:
        return None
    (field, _), value = next(iter(best.items()))
    return ProjectEntities(**{field: value})


def format_project_context(rows: list[ProjectInfo]) -> str:
    if not rows:
        return ""
    payload = [
        {
            "customer_code": row.customer_code,
            "customer": row.customer_name,
            "project": row.project_name,
            "model_id": row.model_id,
            "project_data": row.project_data or {},
        }
        for row in rows
    ]
    return "Project information from project_info:\n" + json.dumps(
        payload, ensure_ascii=False, default=str
    )


async def load_project_context(session: AsyncSession, user_query: str) -> str:
    # Deterministic DB mapping is faster and more reliable than an LLM call for
    # known customer codes, customer names, project names and model IDs.
    catalog_entities = await resolve_entities_from_catalog(session, user_query)
    if catalog_entities is not None:
        rows = await find_project_info(session, catalog_entities)
        if rows:
            return format_project_context(rows)

    # Use the LLM only for natural-language extraction or catalog ambiguity.
    entities = await extract_project_entities(user_query)
    return format_project_context(await find_project_info(session, entities))
