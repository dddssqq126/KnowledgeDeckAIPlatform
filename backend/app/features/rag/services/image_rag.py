"""Query the independent PPTX image RAG layer."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings
from app.features.rag.services import image_store, ingestion, sparse_embed
from app.features.rag.services.model_clients import RerankClient

logger = logging.getLogger(__name__)


async def retrieve_images(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    try:
        dense, sparse = await asyncio.gather(
            ingestion.embed_query(query), sparse_embed.embed_query(query)
        )
        hits = await image_store.hybrid_search(
            dense_vector=dense,
            sparse_vector=sparse,
            user_id=user_id,
            kb_ids=kb_ids,
            project_id=project_id,
            limit=settings.rag_image_final_top_k,
        )
        if not hits and project_id:
            hits = await image_store.hybrid_search(
                dense_vector=dense,
                sparse_vector=sparse,
                user_id=user_id,
                kb_ids=kb_ids,
                project_id=None,
                limit=settings.rag_image_final_top_k,
            )
    except Exception:
        # The image layer enriches an answer but must never make document RAG
        # or the chat stream unavailable.
        logger.exception("image_retrieval_failed")
        return []
    if not hits:
        return []
    passages = [
        f"{h['payload'].get('name', '')}\n"
        f"{h['payload'].get('description', '')}\n"
        f"{h['payload'].get('page_text', '')}"
        for h in hits
    ]
    try:
        reranker = RerankClient(
            base_url=settings.rerank_base_url,
            api_key=settings.rerank_api_key,
            model=settings.rerank_model,
        )
        ranked = await reranker.score(query, passages)
    except Exception:
        logger.exception("image_rerank_failed")
        ranked = [(i, hit["score"]) for i, hit in enumerate(hits)]
    related: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, score in ranked:
        if score < settings.rag_rerank_min_score:
            continue
        payload = hits[index]["payload"]
        image_id = int(payload["image_id"])
        if image_id in seen:
            continue
        seen.add(image_id)
        related.append(
            {
                "id": image_id,
                "name": payload["name"],
                "source_filename": payload["filename"],
                "page_number": int(payload["page_number"]),
                "content_url": f"/knowledge-bases/images/{image_id}/content",
            }
        )
        if len(related) >= settings.rag_image_final_top_k:
            break
    return related
