"""Extract project identifiers from a user query and load matching metadata."""

from __future__ import annotations

import json
import logging
import re
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

# Candidate identifiers are resolved against the database before calling the LLM.
# This lets terse queries such as "給我111的產品資訊" work without requiring the
# user to label 111 as a customer code. Boundaries prevent matching 111 inside 1112.
_IDENTIFIER_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9._-])[A-Za-z0-9][A-Za-z0-9._-]{0,199}"
    r"(?![A-Za-z0-9._-])"
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
    # Resolve every compact token against customer_code first. Customer codes are
    # authoritative DB values, so an unlabeled code does not need an LLM guess.
    candidates = list(dict.fromkeys(_IDENTIFIER_CANDIDATE.findall(user_query)))
    if candidates:
        normalized = [candidate.casefold() for candidate in candidates]
        statement = (
            select(ProjectInfo)
            .where(func.lower(ProjectInfo.customer_code).in_(normalized))
            .order_by(ProjectInfo.updated_at.desc(), ProjectInfo.id.desc())
            .limit(5)
        )
        rows = list((await session.scalars(statement)).all())
        if rows:
            return format_project_context(rows)

    entities = await extract_project_entities(user_query)
    return format_project_context(await find_project_info(session, entities))
