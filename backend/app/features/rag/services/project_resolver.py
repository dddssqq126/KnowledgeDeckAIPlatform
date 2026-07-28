from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectAlias

ResolutionStatus = Literal["not_found", "resolved", "ambiguous"]


class ProjectCandidate(BaseModel):
    project_id: str
    canonical_name: str
    model_codes: list[str] = Field(default_factory=list)


class ProjectResolution(BaseModel):
    status: ResolutionStatus
    input_entities: list[str] = Field(default_factory=list)
    project_id: str | None = None
    canonical_name: str | None = None
    model_codes: list[str] = Field(default_factory=list)
    summary: str | None = None
    candidates: list[ProjectCandidate] = Field(default_factory=list)
    match_type: str = "none"
    confidence: float = 0.0

    def context_block(self) -> str:
        if self.status != "resolved":
            return ""
        models = ", ".join(self.model_codes) or "unknown"
        return (
            "Resolved project metadata:\n"
            f"project_id={self.project_id}\ncanonical_name={self.canonical_name}\n"
            f"model_codes={models}\nstatus_summary={self.summary or 'unknown'}"
        )


def normalize_alias(value: str) -> str:
    return re.sub(r"[-_\s]+", " ", value.strip().casefold())


async def resolve_project(*, session: AsyncSession, user_id: int, text: str) -> ProjectResolution:
    normalized_text = f" {normalize_alias(text)} "
    rows = (await session.execute(
        select(ProjectAlias, Project)
        .join(Project, Project.id == ProjectAlias.project_pk)
        .where(Project.owner_user_id == user_id)
    )).all()
    matches: dict[int, tuple[Project, str]] = {}
    for alias, project in rows:
        needle = normalize_alias(alias.normalized_alias)
        if needle and f" {needle} " in normalized_text:
            current = matches.get(project.id)
            if current is None or len(needle) > len(current[1]):
                matches[project.id] = (project, needle)
    if not matches:
        return ProjectResolution(status="not_found")
    candidates = [ProjectCandidate(project_id=p.project_id, canonical_name=p.canonical_name, model_codes=p.model_codes or []) for p, _ in matches.values()]
    entities = sorted({needle for _, needle in matches.values()})
    if len(matches) > 1:
        return ProjectResolution(status="ambiguous", input_entities=entities, candidates=candidates, match_type="alias", confidence=0.0)
    project, _ = next(iter(matches.values()))
    return ProjectResolution(status="resolved", input_entities=entities, project_id=project.project_id, canonical_name=project.canonical_name, model_codes=project.model_codes or [], summary=project.summary, candidates=candidates, match_type="exact_alias", confidence=1.0)
