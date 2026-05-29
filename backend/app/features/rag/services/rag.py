"""Independent RAG retrieval module.

Single entry point: `retrieve_context(user_id, kb_ids, query)`. Both chat
and slide-maker call it. Anything to do with how chunks are selected,
scored, reranked, and formatted lives here.

Pipeline (each turn that opts into RAG):
  1. Embed the query in parallel: dense (bge-m3) + sparse (BM25).
  2. Qdrant hybrid_search → dense top-N + sparse top-N → RRF fusion.
  3. Cross-encoder rerank (bge-reranker-v2-m3 via vLLM `/score`).
  4. Drop anything below `rag_rerank_min_score`.
  5. Take rerank top-K and format into a `Context:` block + citation list.

The function returns ("", []) when nothing survives the threshold so
callers can cleanly fall back to general knowledge without an empty
"Context:" header confusing the LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings
from app.features.rag.services import ingestion, qdrant_store, sparse_embed
from app.features.rag.services.model_clients import RerankClient

logger = logging.getLogger(__name__)


def _build_reranker() -> RerankClient:
    s = get_settings()
    return RerankClient(
        base_url=s.rerank_base_url,
        api_key=s.rerank_api_key,
        model=s.rerank_model,
    )


def _rerank_passage(hit: dict[str, Any]) -> str:
    """Include metadata in reranker input so tag/file matches affect ranking."""
    payload = hit["payload"]
    topics = payload.get("tags_topic") or []
    metadata_parts = [
        f"filename: {payload.get('filename') or 'unknown'}",
        f"vendor: {payload.get('vendor') or 'unknown'}",
        f"platform: {payload.get('platform') or 'unknown'}",
        f"knowledge_type: {payload.get('knowledge_type') or 'unknown'}",
        f"doc_type: {payload.get('doc_type') or 'unknown'}",
    ]
    if topics:
        metadata_parts.append("topics: " + ", ".join(topics))
    return " | ".join(metadata_parts) + "\n" + str(payload.get("text") or "")


def _query_tag_value(query_tags: Any | None, field: str) -> str:
    if query_tags is None:
        return "unknown"
    if isinstance(query_tags, dict):
        value = query_tags.get(field)
    else:
        value = getattr(query_tags, field, None)
    return value if isinstance(value, str) and value else "unknown"


def _tag_match_boost(payload: dict[str, Any], query_tags: Any | None) -> float:
    """Return a soft score boost for metadata that matches query intent tags."""
    if query_tags is None:
        return 0.0
    s = get_settings()
    boost = 0.0
    for field in ("vendor", "platform", "knowledge_type"):
        wanted = _query_tag_value(query_tags, field)
        if wanted != "unknown" and (payload.get(field) or "unknown") == wanted:
            boost += s.rag_tag_match_boost
    return boost


def _select_final_hits(
    hits: list[dict[str, Any]],
    ranked: list[tuple[int, float]],
    *,
    min_score: float,
    query_tags: Any | None = None,
) -> list[dict[str, Any]]:
    """Apply rerank threshold, top-K, and per-file diversity limits."""
    s = get_settings()
    final_hits: list[dict[str, Any]] = []
    per_file_counts: dict[int, int] = {}
    per_file_limit = max(1, s.rag_per_file_context_limit)

    for orig_idx, rerank_score in ranked:
        hit = dict(hits[orig_idx])
        adjusted_score = rerank_score + _tag_match_boost(hit["payload"], query_tags)
        if adjusted_score < min_score:
            continue
        file_id = hit["payload"].get("file_id")
        if file_id is not None:
            seen_count = per_file_counts.get(file_id, 0)
            if seen_count >= per_file_limit:
                continue
            per_file_counts[file_id] = seen_count + 1
        hit["score"] = adjusted_score
        hit["rerank_score"] = rerank_score
        final_hits.append(hit)
        if len(final_hits) >= s.rag_final_top_k:
            break
    return final_hits


def _format_context(hits: list[dict[str, Any]]) -> str:
    """Render rerank-survivors into source blocks with metadata.

    The metadata line lets the answer prompt reason about vendor/platform
    applicability without using hard filters that could hurt recall.
    """
    if not hits:
        return ""
    out: list[str] = []
    for i, hit in enumerate(hits, start=1):
        payload = hit["payload"]
        page = payload.get("page_number")
        loc = f" (p.{page})" if page else ""
        topics = payload.get("tags_topic") or []
        topic_text = ",".join(topics) if topics else "unknown"
        metadata = (
            f"source_id={i} filename={payload['filename']}{loc} "
            f"vendor={payload.get('vendor') or 'unknown'} "
            f"platform={payload.get('platform') or 'unknown'} "
            f"knowledge_type={payload.get('knowledge_type') or 'unknown'} "
            f"doc_type={payload.get('doc_type') or 'unknown'} "
            f"topic={topic_text}"
        )
        out.append(f"[{i}] {metadata}\n{payload['text']}")
    return "\n\n".join(out)


async def retrieve_context(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    query_tags: Any | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Hybrid dense+sparse search → cross-encoder rerank → top-K context.

    Returns (context_block, citations). `citations` is unique by file_id
    and reflects the *post-rerank* hits (i.e., what actually went into
    the prompt).
    """
    s = get_settings()
    # Dense + sparse in parallel — they hit two different services
    # (vLLM embedding container vs in-process BM25).
    dense_vec, sparse_vec = await asyncio.gather(
        ingestion.embed_query(query),
        sparse_embed.embed_query(query),
    )
    dense_hits = await qdrant_store.hybrid_search(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        user_id=user_id,
        kb_ids=kb_ids,
        top_k=s.rag_rerank_candidate_k,
        prefetch_limit=s.rag_hybrid_prefetch_limit,
    )
    if not dense_hits:
        return "", []

    # If the reranker is down, fall back to dense order so retrieval
    # doesn't break the request — log loudly and continue.
    passages = [_rerank_passage(h) for h in dense_hits]
    try:
        ranked = await _build_reranker().score(query, passages)
    except Exception:
        logger.exception("rerank_failed; falling back to dense order")
        ranked = [(i, dense_hits[i]["score"]) for i in range(len(dense_hits))]

    final_hits = _select_final_hits(
        dense_hits,
        ranked,
        min_score=s.rag_rerank_min_score,
        query_tags=query_tags,
    )

    if not final_hits:
        return "", []

    context = _format_context(final_hits)
    seen: set[int] = set()
    citations: list[dict[str, Any]] = []
    for hit in final_hits:
        fid = hit["payload"]["file_id"]
        if fid in seen:
            continue
        seen.add(fid)
        citations.append(
            {
                "file_id": fid,
                "filename": hit["payload"]["filename"],
                "doc_type": hit["payload"].get("doc_type"),
                "tags_topic": hit["payload"].get("tags_topic") or [],
                "vendor": hit["payload"].get("vendor") or "unknown",
                "platform": hit["payload"].get("platform") or "unknown",
                "knowledge_type": hit["payload"].get("knowledge_type") or "unknown",
            }
        )
    return context, citations
