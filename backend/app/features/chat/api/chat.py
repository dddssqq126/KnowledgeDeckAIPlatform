"""Chat sessions + streaming endpoint.

GET/POST/DELETE /chat/sessions for session management; POST /chat/stream for
the actual SSE streaming response. Auth via the existing get_current_user
dependency. Sessions are user-scoped — cross-user access returns 404.
"""

from __future__ import annotations

import io
import json
import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.base import async_session_factory, get_db
from app.db.models import (
    ChatFeedbackType,
    ChatMessage,
    ChatMessageAttachment,
    ChatMessageFeedback,
    ChatRole,
    ChatSession,
    ChatSessionShare,
    User,
)
from app.features.chat.services import chat_service
from app.features.knowledge_bases.services import file_service
from app.features.knowledge_bases.services.object_storage import get_storage_client
from app.features.rag.services import document_parser, rag
from app.shared.api.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

MAX_CHAT_ATTACHMENTS = 5
CHAT_ATTACHMENT_CONTEXT_CHARS = 30_000


def _content_type_for(extension: str) -> str:
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "cs": "text/x-csharp; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "py": "text/x-python; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return mapping.get(extension, "application/octet-stream")


def _attachment_headers(filename: str, size_bytes: int) -> dict[str, str]:
    safe_filename = filename.replace("\\", "_").replace("/", "_").replace('"', "'")
    return {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Content-Length": str(size_bytes),
    }


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[dict[str, Any]] | None
    created_at: str
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class SessionDetail(SessionOut):
    messages: list[MessageOut]


class ShareOut(BaseModel):
    token: str
    url_path: str


class StreamRequest(BaseModel):
    session_id: int
    message: str = ""
    use_rag: bool = False
    kb_ids: list[int] | None = None
    deep_mode: bool = False


class MessageFeedbackIn(BaseModel):
    feedback: ChatFeedbackType
    comment: str | None = Field(default=None, max_length=2000)


class MessageFeedbackOut(BaseModel):
    message_id: int
    feedback: str
    content: str
    comment: str | None = None
    updated_at: str


@dataclass(slots=True)
class ParsedChatAttachment:
    filename: str
    extension: str
    size_bytes: int
    content_sha256: str
    data: bytes
    context_block: str


def _detect_code_assist_intent(message: str) -> str | None:
    """Return a short intent label when the request looks code-related."""
    text = message.lower()
    code_markers = (
        "```",
        "`",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        "function",
        "class",
        "method",
        "api endpoint",
        "stack trace",
        "traceback",
        "exception",
        "程式碼",
        "代码",
        "函式",
        "函数",
        "類別",
        "类",
    )
    code_actions = (
        "explain",
        "review",
        "fix",
        "debug",
        "refactor",
        "implement",
        "modify",
        "change",
        "update",
        "write",
        "generate",
        "test",
        "說明",
        "解释",
        "修復",
        "修复",
        "除錯",
        "调试",
        "重構",
        "重构",
        "實作",
        "实现",
        "修改",
        "更新",
        "撰寫",
        "生成",
        "測試",
        "测试",
    )
    if not any(marker in text for marker in code_markers):
        return None
    if "debug" in text or "traceback" in text or "exception" in text or "除錯" in text:
        return "debug or fix code"
    if "refactor" in text or "重構" in text or "重构" in text:
        return "refactor code"
    if any(
        action in text
        for action in ("implement", "write", "generate", "實作", "实现", "撰寫", "生成")
    ):
        return "implement code"
    if any(action in text for action in ("review", "explain", "說明", "解释")):
        return "explain or review code"
    if any(action in text for action in code_actions):
        return "modify code"
    return "general code assistance"


def _session_out(s: ChatSession) -> SessionOut:
    return SessionOut(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
    )


def _attachment_out(a: ChatMessageAttachment) -> dict[str, Any]:
    return {
        "id": a.id,
        "filename": a.filename,
        "extension": a.extension,
        "size_bytes": a.size_bytes,
        "created_at": a.created_at.isoformat(),
    }


def _message_out(m: ChatMessage) -> MessageOut:
    return MessageOut(
        id=m.id,
        role=m.role.value,
        content=m.content,
        citations=m.citations,
        created_at=m.created_at.isoformat(),
        attachments=[_attachment_out(a) for a in m.attachments],
    )


async def _load_owned_session(
    session: AsyncSession,
    *,
    owner_user_id: int,
    session_id: int,
    with_messages: bool = False,
) -> ChatSession:
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.owner_user_id == owner_user_id,
        ChatSession.deleted_at.is_(None),
    )
    if with_messages:
        stmt = stmt.options(
            selectinload(ChatSession.messages).selectinload(ChatMessage.attachments)
        )
    s = await session.scalar(stmt)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session_not_found")
    return s


@router.post(
    "/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED
)
async def create_session(
    body: SessionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionOut:
    s = ChatSession(owner_user_id=user.id, title=body.title or "New Chat")
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return _session_out(s)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[SessionOut]:
    rows = await session.scalars(
        select(ChatSession)
        .where(
            ChatSession.owner_user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
        .order_by(ChatSession.updated_at.desc())
    )
    return [_session_out(s) for s in rows.all()]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
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
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
        messages=[_message_out(m) for m in s.messages],
    )


@router.post("/sessions/{session_id}/share", response_model=ShareOut)
async def share_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ShareOut:
    s = await _load_owned_session(session, owner_user_id=user.id, session_id=session_id)
    existing = await session.scalar(
        select(ChatSessionShare).where(
            ChatSessionShare.session_id == s.id,
            ChatSessionShare.revoked_at.is_(None),
        )
    )
    if existing is None:
        existing = ChatSessionShare(
            session_id=s.id,
            owner_user_id=user.id,
            token=secrets.token_urlsafe(24),
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
    return ShareOut(token=existing.token, url_path=f"/shared-chat/{existing.token}")


@router.get("/shares/{token}", response_model=SessionDetail)
async def get_shared_session(
    token: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SessionDetail:
    share = await session.scalar(
        select(ChatSessionShare)
        .where(
            ChatSessionShare.token == token,
            ChatSessionShare.revoked_at.is_(None),
        )
        .options(
            selectinload(ChatSessionShare.session)
            .selectinload(ChatSession.messages)
            .selectinload(ChatMessage.attachments)
        )
    )
    if share is None or share.session is None or share.session.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="share_not_found")

    s = share.session
    return SessionDetail(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat(),
        updated_at=s.updated_at.isoformat(),
        messages=[_message_out(m) for m in s.messages],
    )


@router.patch("/sessions/{session_id}", response_model=SessionOut)
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


@router.post("/messages/{message_id}/feedback", response_model=MessageFeedbackOut)
async def upsert_message_feedback(
    message_id: int,
    body: MessageFeedbackIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> MessageFeedbackOut:
    message = await session.scalar(
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(
            ChatMessage.id == message_id,
            ChatMessage.role == ChatRole.ASSISTANT,
            ChatSession.owner_user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="message_not_found")

    row = await session.scalar(
        select(ChatMessageFeedback).where(
            ChatMessageFeedback.message_id == message_id,
            ChatMessageFeedback.owner_user_id == user.id,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = ChatMessageFeedback(
            message_id=message_id,
            owner_user_id=user.id,
            feedback=body.feedback,
            content=message.content,
            comment=body.comment.strip() if body.comment else None,
            updated_at=now,
        )
        session.add(row)
    else:
        row.feedback = body.feedback
        row.content = message.content
        row.comment = body.comment.strip() if body.comment else None
        row.updated_at = now

    await session.commit()
    await session.refresh(row)
    return MessageFeedbackOut(
        message_id=row.message_id,
        feedback=row.feedback.value,
        content=row.content,
        comment=row.comment,
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    s = await _load_owned_session(session, owner_user_id=user.id, session_id=session_id)
    s.deleted_at = datetime.now(timezone.utc)
    await session.commit()


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    attachment_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    row = await session.scalar(
        select(ChatMessageAttachment)
        .join(ChatMessage, ChatMessage.id == ChatMessageAttachment.message_id)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(
            ChatMessageAttachment.id == attachment_id,
            ChatMessageAttachment.owner_user_id == user.id,
            ChatSession.owner_user_id == user.id,
            ChatSession.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="attachment_not_found")

    try:
        data = await get_storage_client().get_object(row.storage_key)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_error"
        ) from exc

    return Response(
        content=data,
        media_type=_content_type_for(row.extension),
        headers=_attachment_headers(row.filename, len(data)),
    )


def _parse_bool_field(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_kb_ids_field(value: Any) -> list[int] | None:
    if value in (None, "", "null", "undefined"):
        return None
    if isinstance(value, list):
        return [int(v) for v in value]
    parsed = json.loads(str(value))
    if parsed is None:
        return None
    if not isinstance(parsed, list):
        raise ValueError("kb_ids must be a list")
    return [int(v) for v in parsed]


def _parse_form_payload(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise ValueError("payload must be an object")
    return parsed


def _form_or_payload(form: Any, payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = form.get(name)
        if value not in (None, ""):
            return value
    for name in names:
        if name in payload:
            return payload[name]
    return None


async def _parse_stream_request(request: Request) -> tuple[StreamRequest, list[Any]]:
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        try:
            payload = _parse_form_payload(form.get("payload"))
            body = StreamRequest.model_validate(
                {
                    "session_id": _form_or_payload(
                        form, payload, "session_id", "sessionId"
                    ),
                    "message": _form_or_payload(form, payload, "message"),
                    "use_rag": _parse_bool_field(
                        _form_or_payload(form, payload, "use_rag", "useRag")
                    ),
                    "kb_ids": _parse_kb_ids_field(
                        _form_or_payload(form, payload, "kb_ids", "kbIds")
                    ),
                    "deep_mode": _parse_bool_field(
                        _form_or_payload(form, payload, "deep_mode", "deepMode")
                    ),
                }
            )
        except Exception as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_stream_request"
            ) from exc
        uploads = []
        for field_name in ("files", "attachments", "file"):
            uploads.extend(
                item for item in form.getlist(field_name) if hasattr(item, "filename")
            )
        uploads = uploads[:MAX_CHAT_ATTACHMENTS]
        if not body.message.strip() and not uploads:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_message"
            )
        return body, uploads

    try:
        body = StreamRequest.model_validate(await request.json())
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_stream_request"
        ) from exc
    if not body.message.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty_message"
        )
    return body, []


async def _parse_chat_attachments(uploads: list[Any]) -> list[ParsedChatAttachment]:
    if not uploads:
        return []

    settings = get_settings()
    parsed_uploads: list[ParsedChatAttachment] = []
    remaining_chars = CHAT_ATTACHMENT_CONTEXT_CHARS

    for index, upload in enumerate(uploads, start=1):
        filename = upload.filename or f"attachment-{index}"
        try:
            extension = file_service.validate_extension(filename)
            data, sha256, size = await file_service.stream_into_buffer(
                upload, settings.max_upload_bytes
            )
            file_service.validate_content(extension, data[:1024])
            segments = document_parser.parse(extension, data)
        except file_service.ValidationError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail=f"{filename}: {exc.code}"
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail=f"{filename}: parse_failed"
            ) from exc

        if not segments:
            parsed_uploads.append(
                ParsedChatAttachment(
                    filename=filename,
                    extension=extension,
                    size_bytes=size,
                    content_sha256=sha256,
                    data=data,
                    context_block=(
                        f"[Attachment {index}] {filename} ({size} bytes): "
                        "no extractable text"
                    ),
                )
            )
            continue

        parts: list[str] = []
        for segment in segments:
            label = (
                f"page {segment.page_number}"
                if segment.page_number is not None
                else "content"
            )
            parts.append(f"--- {label} ---\n{segment.text.strip()}")
        text = "\n\n".join(parts).strip()
        if remaining_chars <= 0:
            parsed_uploads.append(
                ParsedChatAttachment(
                    filename=filename,
                    extension=extension,
                    size_bytes=size,
                    content_sha256=sha256,
                    data=data,
                    context_block=(
                        f"[Attachment {index}] {filename}: omitted because "
                        "attachment context limit was reached"
                    ),
                )
            )
            continue
        if len(text) > remaining_chars:
            text = (
                text[:remaining_chars].rstrip()
                + "\n[truncated due to attachment context limit]"
            )
            remaining_chars = 0
        else:
            remaining_chars -= len(text)
        parsed_uploads.append(
            ParsedChatAttachment(
                filename=filename,
                extension=extension,
                size_bytes=size,
                content_sha256=sha256,
                data=data,
                context_block=f"[Attachment {index}] {filename}\n{text}",
            )
        )

    return parsed_uploads


def _attachment_context(attachments: list[ParsedChatAttachment]) -> str:
    if not attachments:
        return ""
    return "\n\n".join(
        ["User-uploaded files for this chat turn:"]
        + [attachment.context_block for attachment in attachments]
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a single Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def stream_chat(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    body, uploads = await _parse_stream_request(request)
    parsed_attachments = await _parse_chat_attachments(uploads)
    attachment_context = _attachment_context(parsed_attachments)
    # Load session + history + persist user message in the request session so
    # the streaming generator (which opens its own session) sees them.
    s = await _load_owned_session(
        session, owner_user_id=user.id, session_id=body.session_id, with_messages=True
    )
    history = list(s.messages)
    user_content = body.message.strip()
    user_msg = ChatMessage(
        session_id=s.id, role=ChatRole.USER, content=user_content, citations=None
    )
    session.add(user_msg)
    await session.flush()

    storage_client = get_storage_client()
    attachment_rows: list[ChatMessageAttachment] = []
    for index, attachment in enumerate(parsed_attachments, start=1):
        row = ChatMessageAttachment(
            message_id=user_msg.id,
            owner_user_id=user.id,
            filename=attachment.filename,
            extension=attachment.extension,
            size_bytes=attachment.size_bytes,
            content_sha256=attachment.content_sha256,
            storage_key=(
                f"chat/{s.id}/messages/{user_msg.id}/attachments/"
                f"{index}/original.{attachment.extension}"
            ),
        )
        session.add(row)
        attachment_rows.append(row)
        try:
            await storage_client.put_object(
                row.storage_key,
                io.BytesIO(attachment.data),
                attachment.size_bytes,
                _content_type_for(attachment.extension),
            )
        except Exception as exc:
            await session.rollback()
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_error"
            ) from exc
    await session.flush()
    user_message_done = {
        "id": user_msg.id,
        "role": user_msg.role.value,
        "content": user_msg.content,
        "citations": user_msg.citations,
        "created_at": user_msg.created_at.isoformat(),
        "attachments": [_attachment_out(row) for row in attachment_rows],
    }

    # Auto-title from first user message (within ~50 chars, single line).
    if not history:
        first_line = (
            user_content.splitlines()[0]
            if user_content
            else f"Attached: {parsed_attachments[0].filename}"
        )
        s.title = (first_line[:50] + "...") if len(first_line) > 50 else first_line
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()

    user_id = user.id
    session_id = s.id
    user_message = user_content
    llm_user_message = user_message or (
        "Please read the attached file content and respond with a useful "
        "summary or answer based on it."
    )
    use_rag = body.use_rag
    kb_ids = body.kb_ids
    deep_mode = body.deep_mode

    async def generator() -> AsyncIterator[str]:
        try:
            citations: list[dict[str, Any]] = []
            context = ""
            retrieval_note: str | None = None
            rag_query: str | None = None
            code_assist_intent: str | None = None
            query_tags: chat_service.QueryTags | None = None
            if use_rag:
                # Multi-turn follow-ups ("and Python?", "what about that one?")
                # are not standalone — embedding them directly drags retrieval
                # off-topic. Rewriter resolves references against history into
                # a self-contained query before we hit the vector store.
                code_assist_intent = _detect_code_assist_intent(llm_user_message)
                code_intent = chat_service.detect_code_assist_intent(llm_user_message)
                if code_intent is not None:
                    # Code queries must keep identifiers, import paths, and
                    # error messages intact, so use the deterministic
                    # code-aware rewriter instead of the natural-language
                    # document rewriter.
                    rag_query = chat_service.rewrite_for_code_retrieval(
                        history=history,
                        user_message=llm_user_message,
                        intent=code_intent,
                    )
                else:
                    # Multi-turn follow-ups ("and Python?", "what about that one?")
                    # are not standalone — embedding them directly drags retrieval
                    # off-topic. Rewriter resolves references against history into
                    # a self-contained query before we hit the vector store.
                    rag_query = await chat_service.rewrite_for_retrieval(
                        history=history, user_message=llm_user_message
                    )
                query_tags = chat_service.detect_query_tags(llm_user_message, rag_query)
                if deep_mode:
                    rag_result = await rag.retrieve_context_checked(
                        user_id=user_id,
                        kb_ids=kb_ids,
                        query=rag_query,
                        user_message=llm_user_message,
                        query_tags=query_tags,
                        deep_mode=True,
                    )
                    context = rag_result.context
                    citations = rag_result.citations
                    retrieval_note = rag_result.diagnostics.retrieval_note()
                else:
                    context, citations = await rag.retrieve_context(
                        user_id=user_id,
                        kb_ids=kb_ids,
                        query=rag_query,
                        query_tags=query_tags,
                        deep_mode=False,
                    )

            if attachment_context:
                context = (
                    f"{context}\n\n{attachment_context}"
                    if context
                    else attachment_context
                )

            collected: list[str] = []
            async for token in chat_service.stream_answer(
                history=history,
                user_message=llm_user_message,
                context=context,
                rag_query=rag_query,
                code_assist_intent=code_assist_intent,
                query_tags=query_tags,
                retrieval_note=retrieval_note,
            ):
                collected.append(token)
                yield _sse("token", {"text": token})

            # Persist the assistant turn in a fresh session — request session
            # already returned to the pool when the response started streaming.
            factory = async_session_factory()
            assistant_message_id: int | None = None
            async with factory() as save_session:
                assistant_message = ChatMessage(
                    session_id=session_id,
                    role=ChatRole.ASSISTANT,
                    content="".join(collected),
                    citations=citations or None,
                )
                save_session.add(assistant_message)
                await save_session.flush()
                assistant_message_id = assistant_message.id
                touched = await save_session.scalar(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                if touched is not None:
                    touched.updated_at = datetime.now(timezone.utc)
                await save_session.commit()

            yield _sse("citations", {"items": citations})
            yield _sse(
                "done",
                {
                    "message_id": assistant_message_id,
                    "user_message": user_message_done,
                },
            )
        except Exception as exc:  # pragma: no cover - prototype
            logger.exception("chat_stream_failed session=%s", session_id)
            yield _sse("error", {"message": str(exc)[:300]})

    return StreamingResponse(generator(), media_type="text/event-stream")
