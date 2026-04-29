"""Slide-planner sessions: conversational outline + Presenton render.

Mirrors the chat session API but replaces the chat system prompt with a
slide-planner one (in slide_chat_service) and adds a /render endpoint that
calls Presenton, retrieves the PPTX from the shared volume, and stores it
in MinIO.
"""
from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.shared.api.deps import get_current_user
from app.db.base import async_session_factory, get_db
from app.db.models import SlideMessage, SlideRole, SlideSession, SlideStatus, User
from app.features.slides.services import slide_chat_service
from app.features.knowledge_bases.services.object_storage import get_storage_client
from app.features.slides.services.presenton_client import PresentonError, get_presenton_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/slide-sessions", tags=["slide-sessions"])

# Pulled from slide_chat_service for centralized parsing.
_OUTLINE_READY_MARKER = slide_chat_service.OUTLINE_READY_MARKER
# Matches the marker plus any optional `key=value` args inside the brackets.
# Examples: `[OUTLINE_READY]`, `[OUTLINE_READY template=modern]`,
# `[OUTLINE_READY template=professional language=Spanish]`.
_MARKER_RE = re.compile(r"\[OUTLINE_READY(?:\s+([^\]]+))?\]")
# Matches any "## Slide N: Title" block until the next "## Slide" or end.
_SLIDE_BLOCK_RE = re.compile(
    r"^##\s*Slide\s+\d+\s*:.*?(?=^##\s*Slide\s+\d+\s*:|\Z)",
    re.DOTALL | re.MULTILINE,
)


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AvailableTemplate(BaseModel):
    """A custom template authored in Presenton's UI."""
    id: str
    name: str


class SessionOut(BaseModel):
    id: int
    title: str
    status: str
    has_pptx: bool
    custom_template_id: str | None
    custom_template_name: str | None
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[dict[str, Any]] | None
    created_at: str


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class TemplateUpdate(BaseModel):
    """Either both fields are populated (set), or both null (clear)."""
    custom_template_id: str | None
    custom_template_name: str | None


class StreamRequest(BaseModel):
    message: str = Field(min_length=1)
    use_rag: bool = False
    kb_ids: list[int] | None = None


class RenderRequest(BaseModel):
    template: str = Field(default="general", max_length=64)
    language: str = Field(default="English", max_length=64)


class RenderResponse(BaseModel):
    session: "SessionOut"
    message: "MessageOut"


def _session_out(s: SlideSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        title=s.title,
        status=s.status.value,
        has_pptx=s.generated_pptx_key is not None,
        custom_template_id=s.custom_template_id,
        custom_template_name=s.custom_template_name,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
    )


def _message_out(m: SlideMessage) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role.value,
        content=m.content,
        citations=m.citations,
        created_at=m.created_at.isoformat(),
    )


async def _load_owned_session(
    session: AsyncSession,
    *,
    owner_user_id: int,
    session_id: int,
    with_messages: bool = False,
) -> SlideSession:
    stmt = select(SlideSession).where(
        SlideSession.id == session_id,
        SlideSession.owner_user_id == owner_user_id,
        SlideSession.deleted_at.is_(None),
    )
    if with_messages:
        stmt = stmt.options(selectinload(SlideSession.messages))
    s = await session.scalar(stmt)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session_not_found")
    return s


def _split_slide_blocks(outline_markdown: str) -> list[str]:
    """Splits an outline like:
        ## Slide 1: Intro\n- foo\n\n## Slide 2: Body\n- bar
    into per-slide markdown strings."""
    blocks = [m.group(0).strip() for m in _SLIDE_BLOCK_RE.finditer(outline_markdown)]
    return [b for b in blocks if b]


def _extract_outline(
    messages: list[SlideMessage],
) -> tuple[str, dict[str, str]] | None:
    """Find the latest assistant turn carrying the OUTLINE_READY marker,
    strip the marker, and parse any key=value args inside it.

    Returns (outline_markdown, params) — params may include `template` and
    `language`. Returns None if no marker-bearing message exists.
    """
    for m in reversed(messages):
        if m.role is not SlideRole.ASSISTANT:
            continue
        match = _MARKER_RE.search(m.content)
        if match is None:
            continue
        body = (m.content[: match.start()] + m.content[match.end():]).strip()
        params: dict[str, str] = {}
        if match.group(1):
            for pair in match.group(1).split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k.strip()] = v.strip()
        return body, params
    return None


# --- Sessions CRUD ---


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionOut:
    s = SlideSession(owner_user_id=user.id, title=body.title or "New deck")
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return _session_out(s)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[SessionOut]:
    rows = await session.scalars(
        select(SlideSession)
        .where(
            SlideSession.owner_user_id == user.id,
            SlideSession.deleted_at.is_(None),
        )
        .order_by(SlideSession.updated_at.desc())
    )
    return [_session_out(s) for s in rows.all()]


# Static path declared before /{session_id} so FastAPI doesn't match
# "available-templates" as a session id.
@router.get("/available-templates", response_model=list[AvailableTemplate])
async def list_available_templates(
    _user: User = Depends(get_current_user),
) -> list[AvailableTemplate]:
    """Proxy to Presenton's /template/all (excludes built-ins). Frontend
    calls this to populate the picker after the user authors a new
    template via Presenton's /custom-template page."""
    presenton = get_presenton_client()
    try:
        items = await presenton.list_custom_templates()
    except PresentonError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"presenton_unavailable: {exc}"
        )
    out: list[AvailableTemplate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tid = item.get("id") or item.get("template_id")
        name = item.get("name") or tid or "Untitled"
        if tid:
            out.append(AvailableTemplate(id=str(tid), name=str(name)))
    return out


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionDetail:
    s = await _load_owned_session(
        session, owner_user_id=user.id, session_id=session_id, with_messages=True
    )
    return SessionDetail(
        id=s.id,
        title=s.title,
        status=s.status.value,
        has_pptx=s.generated_pptx_key is not None,
        custom_template_id=s.custom_template_id,
        custom_template_name=s.custom_template_name,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
        messages=[_message_out(m) for m in s.messages],
    )


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: int,
    body: SessionUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionOut:
    s = await _load_owned_session(session, owner_user_id=user.id, session_id=session_id)
    s.title = body.title
    await session.commit()
    await session.refresh(s)
    return _session_out(s)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    s = await _load_owned_session(session, owner_user_id=user.id, session_id=session_id)
    s.deleted_at = datetime.now(timezone.utc)
    await session.commit()


# --- Visual templates (custom PPTX-derived templates authored in Presenton's UI) ---
# (PATCH /{session_id}/template lives here, but the static-path GET is
# declared above the dynamic /{session_id} routes to win FastAPI's route
# matching priority.)


@router.patch("/{session_id}/template", response_model=SessionOut)
async def set_session_template(
    session_id: int,
    body: TemplateUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionOut:
    """Bind a Presenton-authored visual template to this session, or clear
    it (pass both fields as null). Render falls back to the marker /
    default chain when this is null."""
    s = await _load_owned_session(session, owner_user_id=user.id, session_id=session_id)
    s.custom_template_id = body.custom_template_id or None
    s.custom_template_name = body.custom_template_name or None
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return _session_out(s)


# --- Streaming chat ---


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{session_id}/stream")
async def stream_session(
    session_id: int,
    body: StreamRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    s = await _load_owned_session(
        session, owner_user_id=user.id, session_id=session_id, with_messages=True
    )
    history = list(s.messages)

    user_msg = SlideMessage(
        session_id=s.id, role=SlideRole.USER, content=body.message, citations=None
    )
    session.add(user_msg)
    if not history:
        # Auto-title from first user message.
        first_line = body.message.strip().splitlines()[0]
        s.title = (first_line[:50] + "...") if len(first_line) > 50 else first_line
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()

    user_id = user.id
    sid = s.id
    user_message = body.message
    use_rag = body.use_rag
    kb_ids = body.kb_ids

    async def generator() -> AsyncIterator[str]:
        try:
            token_stream, citations = await slide_chat_service.stream_planner(
                history=history,
                user_message=user_message,
                user_id=user_id,
                use_rag=use_rag,
                kb_ids=kb_ids,
            )
            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield _sse("token", {"text": token})

            content = "".join(collected)
            # Detect with the regex so marker variants like
            # `[OUTLINE_READY template=modern]` count too.
            outline_ready = _MARKER_RE.search(content) is not None

            factory = async_session_factory()
            async with factory() as save_session:
                save_session.add(
                    SlideMessage(
                        session_id=sid,
                        role=SlideRole.ASSISTANT,
                        content=content,
                        citations=citations or None,
                    )
                )
                touched = await save_session.scalar(
                    select(SlideSession).where(SlideSession.id == sid)
                )
                if touched is not None:
                    touched.updated_at = datetime.now(timezone.utc)
                await save_session.commit()

            yield _sse("citations", {"items": citations})
            yield _sse("done", {"outline_ready": outline_ready})
        except Exception as exc:  # pragma: no cover - prototype
            logger.exception("slide_stream_failed session=%s", sid)
            yield _sse("error", {"message": str(exc)[:300]})

    return StreamingResponse(generator(), media_type="text/event-stream")


# --- Render via Presenton ---


@router.post("/{session_id}/render", response_model=RenderResponse)
async def render_session(
    session_id: int,
    body: RenderRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RenderResponse:
    """Render the latest confirmed outline via Presenton.

    Always returns 200 — both success and Presenton-side failure produce a
    persisted assistant message in the conversation. Only true 4xx
    (no outline yet, unparseable) raise HTTPException. Frontend appends the
    returned `message` directly to its local message list, then on later
    page loads the persisted row reappears in the natural history order.
    """
    started = datetime.now(timezone.utc)
    s = await _load_owned_session(
        session, owner_user_id=user.id, session_id=session_id, with_messages=True
    )
    extracted = _extract_outline(list(s.messages))
    if extracted is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="no_outline_ready")
    outline_md, marker_params = extracted
    slide_blocks = _split_slide_blocks(outline_md)
    if not slide_blocks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="outline_unparsable")

    # Template precedence: session.custom_template_id (user pinned this
    # session to a Presenton-authored visual template) > marker > body >
    # default. Built-in fallback to general for unrecognised LLM markers
    # since Presenton 400s on missing template names.
    language = marker_params.get("language") or body.language
    if s.custom_template_id:
        template = s.custom_template_id
    else:
        requested_template = (marker_params.get("template") or body.template).strip()
        _BUILTIN_TEMPLATES = {"general", "modern", "standard", "swift"}
        if requested_template in _BUILTIN_TEMPLATES:
            template = requested_template
        else:
            logger.info(
                "slide_render template_fallback session=%s requested=%s -> general",
                session_id,
                requested_template,
            )
            template = "general"

    s.status = SlideStatus.RENDERING
    s.updated_at = started
    await session.commit()

    presenton = get_presenton_client()
    try:
        result = await presenton.generate(
            slides_markdown=slide_blocks,
            n_slides=len(slide_blocks),
            language=language,
            template=template,
            export_as="pptx",
        )
        path = result.get("path")
        if not path:
            raise PresentonError("presenton response missing 'path'")
        pptx_bytes = presenton.read_artifact(path)
    except Exception as exc:
        elapsed = max(1, int((datetime.now(timezone.utc) - started).total_seconds()))
        logger.exception("presenton_render_failed session=%s", session_id)
        s.status = SlideStatus.FAILED
        s.updated_at = datetime.now(timezone.utc)
        # Persist the failure as an assistant turn so the user sees it in the
        # conversation log instead of as a transient banner.
        msg_row = SlideMessage(
            session_id=session_id,
            role=SlideRole.ASSISTANT,
            content=f"[RENDER_FAILED:{elapsed}] {str(exc)[:300]}",
            citations=None,
        )
        session.add(msg_row)
        await session.commit()
        await session.refresh(s)
        await session.refresh(msg_row)
        return RenderResponse(session=_session_out(s), message=_message_out(msg_row))

    # Persist the PPTX in configured object storage under a stable key per
    # session. New renders overwrite, matching the file upload key layout.
    storage = get_storage_client()
    key = f"slide-sessions/{session_id}/latest.pptx"
    await storage.put_object(
        key,
        io.BytesIO(pptx_bytes),
        len(pptx_bytes),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    elapsed = max(1, int((datetime.now(timezone.utc) - started).total_seconds()))
    s.status = SlideStatus.RENDERED
    s.generated_pptx_key = key
    s.updated_at = datetime.now(timezone.utc)
    msg_row = SlideMessage(
        session_id=session_id,
        role=SlideRole.ASSISTANT,
        content=f"[RENDERED:{elapsed}] Your presentation is ready.",
        citations=None,
    )
    session.add(msg_row)
    await session.commit()
    await session.refresh(s)
    await session.refresh(msg_row)
    return RenderResponse(session=_session_out(s), message=_message_out(msg_row))


@router.get("/{session_id}/download")
async def download_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    s = await _load_owned_session(
        session, owner_user_id=user.id, session_id=session_id
    )
    if s.generated_pptx_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_rendered_yet")

    storage = get_storage_client()
    pptx_bytes = await storage.get_object(s.generated_pptx_key)
    safe_title = s.title.replace('"', "'").strip() or f"deck-{s.id}"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_title}.pptx"',
    }
    return StreamingResponse(
        io.BytesIO(pptx_bytes),
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers=headers,
    )
