"""Thin async-friendly wrapper around qdrant-client.

Single collection (`qdrant_collection`) for the whole app. Per-user / per-KB
isolation is enforced via payload filters at query time, not via separate
collections.

Hybrid search: each point carries a named `dense` vector (bge-m3 1024-d
cosine) and a named `sparse` vector (BM25-style hashed lexical
features, with Qdrant IDF modifier). At retrieval we prefetch top-N
from each, then RRF-fuse with Qdrant's Query API.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import get_settings
from app.features.rag.services.sparse_embed import SparseVec


_client: QdrantClient | None = None

DENSE_VEC = "dense"
SPARSE_VEC = "sparse"


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = QdrantClient(url=s.qdrant_url)
    return _client


def _is_hybrid(client: QdrantClient, collection: str) -> bool:
    """Returns True iff the existing collection already has the hybrid
    (named dense + sparse) schema. Used so a fresh deploy lazily creates
    the right schema, while existing single-vector deploys stay readable
    until the user runs the reindex endpoint to migrate."""
    info = client.get_collection(collection)
    vectors_config = info.config.params.vectors
    sparse_config = info.config.params.sparse_vectors
    has_named_dense = isinstance(vectors_config, dict) and DENSE_VEC in vectors_config
    has_sparse = bool(sparse_config) and SPARSE_VEC in sparse_config
    return has_named_dense and has_sparse


async def ensure_collection() -> None:
    """Idempotent. Creates a hybrid (named-vector) collection if absent.

    Does NOT migrate an existing legacy collection — call rebuild_collection()
    via the reindex endpoint to do that explicitly.
    """
    s = get_settings()

    def _impl() -> None:
        client = _get_client()
        if client.collection_exists(s.qdrant_collection):
            return
        client.create_collection(
            collection_name=s.qdrant_collection,
            vectors_config={
                DENSE_VEC: qm.VectorParams(
                    size=s.embedding_dim, distance=qm.Distance.COSINE
                )
            },
            sparse_vectors_config={
                SPARSE_VEC: qm.SparseVectorParams(
                    index=qm.SparseIndexParams(on_disk=False),
                    modifier=qm.Modifier.IDF,
                )
            },
        )
        for field in ("user_id", "kb_id", "file_id"):
            client.create_payload_index(
                collection_name=s.qdrant_collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.INTEGER,
            )

    await asyncio.to_thread(_impl)


async def rebuild_collection() -> None:
    """Drops + recreates the collection with the hybrid schema. Used by
    the reindex endpoint. Caller must re-upsert all chunks afterwards."""
    s = get_settings()

    def _impl() -> None:
        client = _get_client()
        if client.collection_exists(s.qdrant_collection):
            client.delete_collection(s.qdrant_collection)

    await asyncio.to_thread(_impl)
    await ensure_collection()


async def upsert_chunks(
    *,
    user_id: int,
    kb_id: int,
    file_id: int,
    filename: str,
    chunks: list[dict[str, Any]],
    dense_vectors: list[list[float]],
    sparse_vectors: list[SparseVec],
) -> None:
    """`chunks` is a list of {text, page_number?, chunk_index} dicts. The
    three vector lists must be the same length as chunks."""
    s = get_settings()
    if not (len(chunks) == len(dense_vectors) == len(sparse_vectors)):
        raise ValueError(
            f"upsert length mismatch: chunks={len(chunks)} "
            f"dense={len(dense_vectors)} sparse={len(sparse_vectors)}"
        )

    def _impl() -> None:
        points = [
            qm.PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    DENSE_VEC: dense,
                    SPARSE_VEC: qm.SparseVector(
                        indices=sparse.indices, values=sparse.values
                    ),
                },
                payload={
                    "user_id": user_id,
                    "kb_id": kb_id,
                    "file_id": file_id,
                    "filename": filename,
                    "text": chunk["text"],
                    "page_number": chunk.get("page_number"),
                    "chunk_index": chunk["chunk_index"],
                },
            )
            for chunk, dense, sparse in zip(
                chunks, dense_vectors, sparse_vectors, strict=True
            )
        ]
        _get_client().upsert(collection_name=s.qdrant_collection, points=points)

    await asyncio.to_thread(_impl)


async def delete_by_file(*, file_id: int) -> None:
    s = get_settings()

    def _impl() -> None:
        _get_client().delete(
            collection_name=s.qdrant_collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[qm.FieldCondition(key="file_id", match=qm.MatchValue(value=file_id))]
                )
            ),
        )

    await asyncio.to_thread(_impl)


async def hybrid_search(
    *,
    dense_vector: list[float],
    sparse_vector: SparseVec,
    user_id: int,
    kb_ids: list[int] | None = None,
    top_k: int = 20,
    prefetch_limit: int = 40,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Dense + sparse prefetch -> RRF fusion. Returns top_k {score,payload}.

    `min_score` filters the fused score (an RRF score, not cosine — it lives
    on a different scale, typically 0..1). The dense-only `min_score` from
    the legacy path no longer applies cleanly to fused scores, so callers
    should pass a relaxed threshold here (rerank does the real filtering
    downstream).
    """
    s = get_settings()

    def _impl() -> list[dict[str, Any]]:
        must: list[qm.FieldCondition] = [
            qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))
        ]
        if kb_ids:
            must.append(
                qm.FieldCondition(key="kb_id", match=qm.MatchAny(any=kb_ids))
            )
        flt = qm.Filter(must=must)
        response = _get_client().query_points(
            collection_name=s.qdrant_collection,
            prefetch=[
                qm.Prefetch(
                    query=dense_vector,
                    using=DENSE_VEC,
                    filter=flt,
                    limit=prefetch_limit,
                ),
                qm.Prefetch(
                    query=qm.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                    using=SPARSE_VEC,
                    filter=flt,
                    limit=prefetch_limit,
                ),
            ],
            query=qm.FusionQuery(fusion=qm.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
        out: list[dict[str, Any]] = []
        for p in response.points:
            if p.score < min_score:
                continue
            out.append({"score": p.score, "payload": p.payload})
        return out

    return await asyncio.to_thread(_impl)
