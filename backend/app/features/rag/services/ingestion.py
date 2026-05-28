"""End-to-end synchronous ingestion: parse → chunk → embed → write Qdrant.

Called inline from the upload endpoint after the MinIO PUT succeeds. Synchronous
processing keeps the MVP simple — no Redis/RQ/worker. The trade-off is that
upload requests block for a few seconds while embeddings are computed.

Status transitions A drives:
  uploaded -> indexed (success)
  uploaded -> failed  (any exception during ingestion)
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import FileStatus, KnowledgeFile
from app.features.rag.services import (
    document_parser,
    qdrant_store,
    sparse_embed,
    tagger,
    text_splitter,
)
from app.features.rag.services.model_clients import EmbeddingClient

logger = logging.getLogger(__name__)


def _build_embedding_client() -> EmbeddingClient:
    s = get_settings()
    return EmbeddingClient(
        base_url=s.embedding_base_url, api_key=s.embedding_api_key, model=s.embedding_model
    )


def _build_chunks(segments: list[document_parser.ParsedSegment]) -> list[dict[str, Any]]:
    """Flatten parser output into chunk dicts ready for upsert."""
    s = get_settings()
    out: list[dict[str, Any]] = []
    chunk_index = 0
    for segment in segments:
        for piece in text_splitter.split_text(
            segment.text, chunk_chars=s.chunk_chars, chunk_overlap=s.chunk_overlap
        ):
            out.append(
                {"text": piece, "page_number": segment.page_number, "chunk_index": chunk_index}
            )
            chunk_index += 1
    return out


async def _embed(texts: list[str]) -> list[list[float]]:
    client = _build_embedding_client()
    response = await client.create_embeddings(texts)
    # OpenAI-compatible embedding response: {"data": [{"embedding": [...]}], ...}
    return [item["embedding"] for item in response["data"]]


async def ingest_file(
    *,
    session: AsyncSession,
    file_row: KnowledgeFile,
    data: bytes,
) -> None:
    """Parse + chunk + embed + index + update file_row status.

    Commits the status update on its own transaction (the upload endpoint has
    already committed the file row). On failure, sets status=FAILED and stores
    a short error message; never re-raises (the upload is considered successful
    even if ingestion fails — the user can retry by re-uploading).
    """
    try:
        segments = document_parser.parse(file_row.extension, data)
        if not segments:
            file_row.status = FileStatus.FAILED
            file_row.status_error = "no extractable text"
            await session.commit()
            return

        chunks = _build_chunks(segments)
        if not chunks:
            file_row.status = FileStatus.FAILED
            file_row.status_error = "no chunks produced"
            await session.commit()
            return

        s = get_settings()
        if s.rag_tagging_enabled:
            full_text = "\n".join(seg.text for seg in segments)[: s.rag_tag_max_chars]
            tags = await tagger.generate_doc_tags(full_text, file_row.filename)
        else:
            tags = tagger.DocTags.empty()
        tags = tags.with_overrides(
            vendor=file_row.tag_vendor,
            platform=file_row.tag_platform,
            knowledge_type=file_row.tag_knowledge_type,
        )
        file_row.tag_vendor = tags.vendor
        file_row.tag_platform = tags.platform
        file_row.tag_knowledge_type = tags.knowledge_type

        await qdrant_store.ensure_collection()
        raw_texts = [c["text"] for c in chunks]
        embed_texts = [tagger.enrich_text_for_embedding(t, tags) for t in raw_texts]
        dense_vectors = await _embed(embed_texts)
        sparse_vectors = await sparse_embed.embed_passages(embed_texts)
        await qdrant_store.upsert_chunks(
            user_id=file_row.owner_user_id,
            kb_id=file_row.knowledge_base_id,
            file_id=file_row.id,
            filename=file_row.filename,
            chunks=chunks,
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
            tags=tags,
        )

        file_row.status = FileStatus.INDEXED
        file_row.status_error = None
        await session.commit()
        logger.info(
            "ingest_complete file_id=%s chunks=%s", file_row.id, len(chunks)
        )
    except Exception as exc:  # pragma: no cover - prototype error path
        logger.exception("ingest_failed file_id=%s", file_row.id)
        file_row.status = FileStatus.FAILED
        file_row.status_error = str(exc)[:500]
        await session.commit()


# Used by the file delete endpoint to clean Qdrant on soft-delete.
async def cleanup_file_vectors(*, file_id: int) -> None:
    try:
        await qdrant_store.delete_by_file(file_id=file_id)
    except Exception:
        # Cleanup failures are tolerable for soft-delete; vectors will be
        # filtered out by the deleted_at check on the file row anyway, but
        # this keeps Qdrant tidy.
        logger.exception("qdrant_cleanup_failed file_id=%s", file_id)


# Convenience for chat-side: embed a single query into a vector.
async def embed_query(text: str) -> list[float]:
    vectors = await _embed([text])
    return vectors[0]
