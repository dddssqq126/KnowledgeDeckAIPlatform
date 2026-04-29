import io
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.deps import get_current_user
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import FileStatus, KnowledgeBase, KnowledgeFile, User
from app.features.knowledge_bases.services import file_service
from app.features.rag.services import ingestion
from app.features.knowledge_bases.services.object_storage import get_storage_client

router = APIRouter(prefix="/knowledge-bases", tags=["files"])

# Module-level so tests can monkeypatch a smaller value.
MAX_UPLOAD_BYTES = get_settings().max_upload_bytes


class FileOut(BaseModel):
    id: int
    knowledge_base_id: int
    filename: str
    extension: str
    size_bytes: int
    status: str
    status_error: str | None = None
    created_at: str


def _content_type_for(extension: str) -> str:
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "cs": "text/x-csharp; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "py": "text/x-python; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        "pptx": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
    }
    # Falls back to a binary safe default; defensive in case a new extension
    # is added to ALLOWED_EXTENSIONS without updating this map.
    return mapping.get(extension, "application/octet-stream")


async def _load_owned_kb(
    session: AsyncSession, *, owner_user_id: int, kb_id: int
) -> KnowledgeBase:
    kb = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.owner_user_id == owner_user_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    if kb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    return kb


def _file_out(r: KnowledgeFile) -> FileOut:
    return FileOut(
        id=r.id,
        knowledge_base_id=r.knowledge_base_id,
        filename=r.filename,
        extension=r.extension,
        size_bytes=r.size_bytes,
        status=r.status.value,
        status_error=r.status_error,
        created_at=r.created_at.isoformat(),
    )


@router.post(
    "/{kb_id}/files", response_model=FileOut, status_code=status.HTTP_201_CREATED
)
async def upload_file(
    kb_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> FileOut:
    kb = await _load_owned_kb(session, owner_user_id=user.id, kb_id=kb_id)

    try:
        extension = file_service.validate_extension(file.filename or "")
    except file_service.ValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=e.code)

    try:
        data, sha256, size = await file_service.stream_into_buffer(
            file, MAX_UPLOAD_BYTES
        )
    except file_service.ValidationError as e:
        # `stream_into_buffer` only raises file_too_large.
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=e.code)

    try:
        file_service.validate_content(extension, data[:1024])
    except file_service.ValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=e.code)

    duplicate = await session.scalar(
        select(KnowledgeFile.id).where(
            KnowledgeFile.knowledge_base_id == kb.id,
            KnowledgeFile.filename == file.filename,
            KnowledgeFile.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="duplicate_filename")

    row = KnowledgeFile(
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        filename=file.filename,
        extension=extension,
        size_bytes=size,
        content_sha256=sha256,
        storage_key="",  # placeholder — updated after we know the id
        status=FileStatus.UPLOADED,
    )
    session.add(row)
    await session.flush()
    row.storage_key = f"kb/{kb.id}/files/{row.id}/original.{extension}"

    try:
        await get_storage_client().put_object(
            row.storage_key,
            io.BytesIO(data),
            size,
            _content_type_for(extension),
        )
    except Exception:
        await session.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_error"
        )

    await session.commit()
    await session.refresh(row)

    # Synchronous ingestion: parse → chunk → embed → Qdrant. On failure the
    # row is marked status=failed (with status_error) but the upload itself
    # still returns 201 — the user sees the failure in the file list.
    await ingestion.ingest_file(session=session, file_row=row, data=data)
    await session.refresh(row)

    return _file_out(row)


@router.get("/{kb_id}/files", response_model=list[FileOut])
async def list_files(
    kb_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[FileOut]:
    await _load_owned_kb(session, owner_user_id=user.id, kb_id=kb_id)
    rows = await session.scalars(
        select(KnowledgeFile)
        .where(
            KnowledgeFile.knowledge_base_id == kb_id,
            KnowledgeFile.deleted_at.is_(None),
        )
        .order_by(KnowledgeFile.created_at.desc())
    )
    return [_file_out(r) for r in rows.all()]


@router.delete("/{kb_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    kb_id: int,
    file_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await _load_owned_kb(session, owner_user_id=user.id, kb_id=kb_id)
    row = await session.scalar(
        select(KnowledgeFile).where(
            KnowledgeFile.id == file_id,
            KnowledgeFile.knowledge_base_id == kb_id,
            KnowledgeFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_not_found")
    row.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    # Best-effort Qdrant cleanup; failures are logged and ignored.
    await ingestion.cleanup_file_vectors(file_id=file_id)
