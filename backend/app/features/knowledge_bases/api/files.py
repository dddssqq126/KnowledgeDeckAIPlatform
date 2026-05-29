import io
from datetime import datetime, timezone
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.api.deps import get_current_user
from app.core.config import get_settings
from app.db.base import get_db
from app.db.models import FileStatus, KnowledgeBase, KnowledgeFile, User
from app.features.knowledge_bases.services import file_service
from app.features.rag.services import qdrant_store, tagger
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


class FileTagPatch(BaseModel):
    vendor: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=64)
    knowledge_type: str = Field(min_length=1, max_length=64)

    @field_validator("vendor", "platform", "knowledge_type")
    @classmethod
    def tag_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tag must not be blank")
        return value


class FileTagOut(BaseModel):
    file_id: int
    doc_type: str | None = None
    intent: str | None = None
    tags_topic: list[str] = Field(default_factory=list)
    vendor: str
    platform: str
    knowledge_type: str
    chunk_count: int


def _content_type_for(extension: str) -> str:
    mapping = {
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "cs": "text/x-csharp; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "py": "text/x-python; charset=utf-8",
        "html": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "csv": "text/csv; charset=utf-8",
        "tsv": "text/tab-separated-values; charset=utf-8",
        "docx": (
            "application/vnd.openxmlformats-officedocument." "wordprocessingml.document"
        ),
        "pptx": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation"
        ),
        "xlsx": (
            "application/vnd.openxmlformats-officedocument." "spreadsheetml.sheet"
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


async def _load_owned_file(
    session: AsyncSession, *, kb_id: int, file_id: int
) -> KnowledgeFile:
    row = await session.scalar(
        select(KnowledgeFile).where(
            KnowledgeFile.id == file_id,
            KnowledgeFile.knowledge_base_id == kb_id,
            KnowledgeFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_not_found")
    return row


async def _file_tag_out(row: KnowledgeFile) -> FileTagOut:
    rows = await qdrant_store.list_file_tags(
        user_id=row.owner_user_id,
        kb_id=row.knowledge_base_id,
    )
    qdrant_tags = next((r for r in rows if r.get("file_id") == row.id), {})
    return FileTagOut(
        file_id=row.id,
        doc_type=qdrant_tags.get("doc_type"),
        intent=qdrant_tags.get("intent"),
        tags_topic=qdrant_tags.get("tags_topic") or [],
        vendor=row.tag_vendor or qdrant_tags.get("vendor") or "unknown",
        platform=row.tag_platform or qdrant_tags.get("platform") or "unknown",
        knowledge_type=(
            row.tag_knowledge_type or qdrant_tags.get("knowledge_type") or "unknown"
        ),
        chunk_count=int(qdrant_tags.get("chunk_count") or 0),
    )


def _attachment_headers(filename: str, size_bytes: int) -> dict[str, str]:
    safe_filename = filename.replace("\\", "_").replace("/", "_").replace('"', "'")
    return {
        "Content-Disposition": f'attachment; filename="{safe_filename}"',
        "Content-Length": str(size_bytes),
    }


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


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    row = await session.scalar(
        select(KnowledgeFile).where(
            KnowledgeFile.id == file_id,
            KnowledgeFile.owner_user_id == user.id,
            KnowledgeFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_not_found")

    try:
        data = await get_storage_client().get_object(row.storage_key)
    except Exception:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_error"
        )

    return Response(
        content=data,
        media_type=_content_type_for(row.extension),
        headers=_attachment_headers(row.filename, len(data)),
    )


@router.patch("/{kb_id}/files/{file_id}/tags", response_model=FileTagOut)
async def update_file_tags(
    kb_id: int,
    file_id: int,
    patch: FileTagPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> FileTagOut:
    await _load_owned_kb(session, owner_user_id=user.id, kb_id=kb_id)
    row = await _load_owned_file(session, kb_id=kb_id, file_id=file_id)
    if row.owner_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file_not_found")

    row.tag_vendor = tagger.normalize_vendor(patch.vendor)
    row.tag_platform = tagger.normalize_platform(patch.platform)
    row.tag_knowledge_type = tagger.normalize_knowledge_type(patch.knowledge_type)
    row.status = FileStatus.UPLOADED
    row.status_error = None
    await session.commit()
    await session.refresh(row)

    try:
        data = await get_storage_client().get_object(row.storage_key)
    except Exception:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="storage_error"
        )

    await ingestion.cleanup_file_vectors(file_id=row.id)
    await ingestion.ingest_file(session=session, file_row=row, data=data)
    await session.refresh(row)
    return await _file_tag_out(row)


@router.delete("/{kb_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    kb_id: int,
    file_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await _load_owned_kb(session, owner_user_id=user.id, kb_id=kb_id)
    row = await _load_owned_file(session, kb_id=kb_id, file_id=file_id)
    row.deleted_at = datetime.now(timezone.utc)
    await session.commit()
    # Best-effort Qdrant cleanup; failures are logged and ignored.
    await ingestion.cleanup_file_vectors(file_id=file_id)
