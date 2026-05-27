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


def _format_context(hits: list[dict[str, Any]]) -> str:
    """Render rerank-survivors into the `[i] filename (p.N)\\n<text>` blocks
    we paste into the prompt."""
    if not hits:
        return ""
    out: list[str] = []
    for i, hit in enumerate(hits, start=1):
        payload = hit["payload"]
        page = payload.get("page_number")
        loc = f" (p.{page})" if page else ""
        out.append(f"[{i}] {payload['filename']}{loc}\n{payload['text']}")
    return "\n\n".join(out)


async def retrieve_context(
    *, user_id: int, kb_ids: list[int] | None, query: str
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
        top_k=s.rag_dense_top_k,
    )
    if not dense_hits:
        return "", []

    # If the reranker is down, fall back to dense order so retrieval
    # doesn't break the request — log loudly and continue.
    passages = [h["payload"]["text"] for h in dense_hits]
    try:
        ranked = await _build_reranker().score(query, passages)
    except Exception:
        logger.exception("rerank_failed; falling back to dense order")
        ranked = [(i, dense_hits[i]["score"]) for i in range(len(dense_hits))]

    final_hits: list[dict[str, Any]] = []
    for orig_idx, rerank_score in ranked:
        if rerank_score < s.rag_rerank_min_score:
            continue
        hit = dict(dense_hits[orig_idx])
        hit["score"] = rerank_score  # overwrite cosine with rerank score
        final_hits.append(hit)
        if len(final_hits) >= s.rag_final_top_k:
            break

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
            }
        )
    return context, citations
