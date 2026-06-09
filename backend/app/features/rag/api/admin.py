"""Admin / maintenance endpoints.

`POST /admin/rag-reindex` is destructive: it drops the Qdrant collection
and reindexes every non-deleted KnowledgeFile from the bytes still in
configured object storage (MinIO or local filesystem). Used to migrate
existing data after a vector-pipeline change
(e.g., adding sparse vectors for hybrid search).

Auth-only (any logged-in user) for MVP. In a real deployment this should
gate on an admin role.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.shared.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import ChatMessage, ChatSession, FileStatus, KnowledgeFile, User
from app.features.rag.services import ingestion, qdrant_store
from app.features.knowledge_bases.services.object_storage import get_storage_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserRow(BaseModel):
    id: int
    username: str
    password: str
    created_at: str
    chat_session_count: int
    chat_message_count: int


class AdminChatMessageRow(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class AdminChatSessionRow(BaseModel):
    id: int
    owner_user_id: int
    owner_username: str
    title: str
    created_at: str
    updated_at: str
    deleted_at: str | None
    message_count: int
    messages: list[AdminChatMessageRow]


class AdminDatabaseOverview(BaseModel):
    users: list[AdminUserRow]
    chat_sessions: list[AdminChatSessionRow]
    totals: dict[str, int]


class ReindexResult(BaseModel):
    reindexed: int
    failed: int
    skipped: int
    failed_files: list[dict[str, str | int]]


@router.get("/database-overview", response_model=AdminDatabaseOverview)
async def database_overview(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AdminDatabaseOverview:
    """Return login (users) and conversation database rows for the admin UI.

    Auth-only (any logged-in user) for MVP, matching the existing admin routes.
    The login table currently stores plaintext passwords, so this endpoint only
    serves authenticated requests and the frontend masks values by default.
    """
    user_rows = (
        await session.execute(
            select(
                User,
                func.count(func.distinct(ChatSession.id)).label("session_count"),
                func.count(ChatMessage.id).label("message_count"),
            )
            .outerjoin(ChatSession, ChatSession.owner_user_id == User.id)
            .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
            .group_by(User.id)
            .order_by(User.id)
        )
    ).all()

    users = [
        AdminUserRow(
            id=user.id,
            username=user.username,
            password=user.password,
            created_at=user.created_at.isoformat(),
            chat_session_count=session_count,
            chat_message_count=message_count,
        )
        for user, session_count, message_count in user_rows
    ]

    chat_rows = (
        await session.scalars(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
    ).all()
    usernames = {row.id: row.username for row, _, _ in user_rows}
    chat_sessions = [
        AdminChatSessionRow(
            id=chat.id,
            owner_user_id=chat.owner_user_id,
            owner_username=usernames.get(chat.owner_user_id, "Unknown user"),
            title=chat.title,
            created_at=chat.created_at.isoformat(),
            updated_at=chat.updated_at.isoformat(),
            deleted_at=chat.deleted_at.isoformat() if chat.deleted_at else None,
            message_count=len(chat.messages),
            messages=[
                AdminChatMessageRow(
                    id=message.id,
                    role=message.role.value,
                    content=message.content,
                    created_at=message.created_at.isoformat(),
                )
                for message in chat.messages
            ],
        )
        for chat in chat_rows
    ]

    return AdminDatabaseOverview(
        users=users,
        chat_sessions=chat_sessions,
        totals={
            "users": len(users),
            "chat_sessions": len(chat_sessions),
            "chat_messages": sum(row.message_count for row in chat_sessions),
        },
    )


@router.post("/rag-reindex", response_model=ReindexResult)
async def rag_reindex(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReindexResult:
    """Drops the Qdrant collection and re-ingests every non-deleted file.

    Steps per file: fetch original bytes from object storage -> parse -> chunk ->
    dense embed (vLLM) -> sparse embed (BM25) -> upsert into the freshly
    rebuilt collection. Files already in FAILED state are skipped.
    """
    # 1. Drop + recreate with hybrid schema.
    await qdrant_store.rebuild_collection()

    # 2. Iterate every non-deleted file.
    rows = await session.scalars(
        select(KnowledgeFile)
        .where(KnowledgeFile.deleted_at.is_(None))
        .order_by(KnowledgeFile.id)
    )
    storage = get_storage_client()
    reindexed = 0
    failed = 0
    skipped = 0
    failed_files: list[dict[str, str | int]] = []
    for f in rows.all():
        if f.status is FileStatus.FAILED:
            skipped += 1
            continue
        try:
            data = await storage.get_object(f.storage_key)
        except Exception as exc:
            logger.exception(
                "reindex_storage_fetch_failed file_id=%s key=%s", f.id, f.storage_key
            )
            failed += 1
            failed_files.append(
                {"id": f.id, "filename": f.filename, "error": str(exc)[:200]}
            )
            continue
        # ingest_file owns the status transition + commit. On success it
        # leaves status=INDEXED; on failure it sets FAILED.
        await ingestion.ingest_file(session=session, file_row=f, data=data)
        if f.status is FileStatus.INDEXED:
            reindexed += 1
        else:
            failed += 1
            failed_files.append(
                {
                    "id": f.id,
                    "filename": f.filename,
                    "error": f.status_error or "unknown",
                }
            )

    return ReindexResult(
        reindexed=reindexed,
        failed=failed,
        skipped=skipped,
        failed_files=failed_files,
    )
