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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import FileStatus, KnowledgeFile, User
from app.features.rag.services import ingestion, qdrant_store
from app.features.knowledge_bases.services.object_storage import get_storage_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class ReindexResult(BaseModel):
    reindexed: int
    failed: int
    skipped: int
    failed_files: list[dict[str, str | int]]


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
            failed_files.append({"id": f.id, "filename": f.filename, "error": str(exc)[:200]})
            continue
        # ingest_file owns the status transition + commit. On success it
        # leaves status=INDEXED; on failure it sets FAILED.
        await ingestion.ingest_file(session=session, file_row=f, data=data)
        if f.status is FileStatus.INDEXED:
            reindexed += 1
        else:
            failed += 1
            failed_files.append(
                {"id": f.id, "filename": f.filename, "error": f.status_error or "unknown"}
            )

    return ReindexResult(
        reindexed=reindexed,
        failed=failed,
        skipped=skipped,
        failed_files=failed_files,
    )
