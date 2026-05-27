from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import KnowledgeBase, User
from app.features.rag.services import qdrant_store
from app.shared.api.deps import get_current_user

router = APIRouter(prefix="/rag", tags=["rag"])


class FileTags(BaseModel):
    file_id: int
    doc_type: str | None
    intent: str | None
    tags_topic: list[str]
    chunk_count: int


@router.get("/kb/{kb_id}/file-tags", response_model=list[FileTags])
async def kb_file_tags(
    kb_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[FileTags]:
    kb = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.owner_user_id == user.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    if kb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    rows = await qdrant_store.list_file_tags(user_id=user.id, kb_id=kb_id)
    return [FileTags(**r) for r in rows]
