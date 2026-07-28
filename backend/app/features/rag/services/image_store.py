"""Separate hybrid Qdrant collection for PPTX image metadata."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from qdrant_client.http import models as qm

from app.core.config import get_settings
from app.features.rag.services import qdrant_store
from app.features.rag.services.sparse_embed import SparseVec


async def ensure_collection() -> None:
    settings = get_settings()

    def _impl() -> None:
        client = qdrant_store._get_client()
        if client.collection_exists(settings.qdrant_image_collection):
            return
        client.create_collection(
            collection_name=settings.qdrant_image_collection,
            vectors_config={
                qdrant_store.DENSE_VEC: qm.VectorParams(
                    size=settings.embedding_dim, distance=qm.Distance.COSINE
                )
            },
            sparse_vectors_config={
                qdrant_store.SPARSE_VEC: qm.SparseVectorParams(
                    index=qm.SparseIndexParams(on_disk=False),
                    modifier=qm.Modifier.IDF,
                )
            },
        )
        for field in ("user_id", "kb_id", "file_id", "image_id"):
            client.create_payload_index(
                collection_name=settings.qdrant_image_collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.INTEGER,
            )
        client.create_payload_index(
            collection_name=settings.qdrant_image_collection,
            field_name="project_id",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )

    await asyncio.to_thread(_impl)


async def rebuild_collection() -> None:
    settings = get_settings()

    def _impl() -> None:
        client = qdrant_store._get_client()
        if client.collection_exists(settings.qdrant_image_collection):
            client.delete_collection(settings.qdrant_image_collection)

    await asyncio.to_thread(_impl)
    await ensure_collection()


async def upsert_image(
    *,
    image_id: int,
    user_id: int,
    kb_id: int,
    file_id: int,
    filename: str,
    name: str,
    description: str,
    page_text: str,
    page_number: int,
    project_id: str | None,
    dense_vector: list[float],
    sparse_vector: SparseVec,
) -> None:
    settings = get_settings()
    payload = {
        "image_id": image_id,
        "user_id": user_id,
        "kb_id": kb_id,
        "file_id": file_id,
        "filename": filename,
        "name": name,
        "description": description,
        "page_text": page_text,
        "page_number": page_number,
        "project_id": project_id,
    }

    def _impl() -> None:
        qdrant_store._get_client().upsert(
            collection_name=settings.qdrant_image_collection,
            points=[
                qm.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        qdrant_store.DENSE_VEC: dense_vector,
                        qdrant_store.SPARSE_VEC: qm.SparseVector(
                            indices=sparse_vector.indices,
                            values=sparse_vector.values,
                        ),
                    },
                    payload=payload,
                )
            ],
        )

    await asyncio.to_thread(_impl)


async def delete_by_file(*, file_id: int) -> None:
    settings = get_settings()

    def _impl() -> None:
        client = qdrant_store._get_client()
        if not client.collection_exists(settings.qdrant_image_collection):
            return
        client.delete(
            collection_name=settings.qdrant_image_collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="file_id", match=qm.MatchValue(value=file_id)
                        )
                    ]
                )
            ),
        )

    await asyncio.to_thread(_impl)


async def hybrid_search(
    *,
    dense_vector: list[float],
    sparse_vector: SparseVec,
    user_id: int,
    kb_ids: list[int] | None,
    project_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    settings = get_settings()

    def _impl() -> list[dict[str, Any]]:
        client = qdrant_store._get_client()
        if not client.collection_exists(settings.qdrant_image_collection):
            return []
        must = [
            qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))
        ]
        if kb_ids:
            must.append(
                qm.FieldCondition(key="kb_id", match=qm.MatchAny(any=kb_ids))
            )
        if project_id:
            must.append(
                qm.FieldCondition(
                    key="project_id", match=qm.MatchValue(value=project_id)
                )
            )
        image_filter = qm.Filter(must=must)
        result = client.query_points(
            collection_name=settings.qdrant_image_collection,
            prefetch=[
                qm.Prefetch(
                    query=dense_vector,
                    using=qdrant_store.DENSE_VEC,
                    filter=image_filter,
                    limit=max(20, limit * 4),
                ),
                qm.Prefetch(
                    query=qm.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                    using=qdrant_store.SPARSE_VEC,
                    filter=image_filter,
                    limit=max(20, limit * 4),
                ),
            ],
            query=qm.FusionQuery(fusion=qm.Fusion.RRF),
            limit=max(20, limit * 4),
            with_payload=True,
        )
        return [
            {"score": point.score, "payload": point.payload}
            for point in result.points
        ]

    return await asyncio.to_thread(_impl)
