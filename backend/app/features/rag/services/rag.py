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
import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.features.rag.services import ingestion, qdrant_store, sparse_embed
from app.features.rag.services.model_clients import RerankClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoverageJudgment:
    status: str
    reason: str = ""
    alternate_query: str | None = None
    retry: bool = False

    def needs_retry(self) -> bool:
        return (
            self.retry
            and self.status in {"partial", "miss"}
            and bool(self.alternate_query)
        )


@dataclass(frozen=True)
class RagDiagnostics:
    deep_mode: bool = False
    coverage_status: str = "not_checked"
    coverage_reason: str = ""
    retried: bool = False
    retry_query: str | None = None
    retry_reason: str = ""

    def retrieval_note(self) -> str | None:
        if not self.deep_mode or self.coverage_status not in {"partial", "miss"}:
            return None
        return (
            "Deep mode checked whether the retrieved context directly answers "
            "the user's question and found that the available documents are "
            "incomplete. Answer only from supported evidence, and briefly tell "
            "the user when the documents do not directly answer part of the "
            "question."
        )


@dataclass(frozen=True)
class RagContextResult:
    context: str
    citations: list[dict[str, Any]]
    diagnostics: RagDiagnostics


@dataclass(frozen=True)
class _RetrievalPass:
    query: str
    candidates: list[dict[str, Any]]
    final_hits: list[dict[str, Any]]
    context: str
    citations: list[dict[str, Any]]


def _retrieval_profile(*, deep_mode: bool) -> dict[str, int]:
    """Return candidate/context sizes for normal vs deeper retrieval."""
    s = get_settings()
    if not deep_mode:
        return {
            "candidate_k": s.rag_rerank_candidate_k,
            "prefetch_limit": s.rag_hybrid_prefetch_limit,
            "final_top_k": s.rag_final_top_k,
        }
    return {
        "candidate_k": s.rag_rerank_candidate_k * 2,
        "prefetch_limit": s.rag_hybrid_prefetch_limit * 2,
        "final_top_k": s.rag_final_top_k + 3,
    }


def _build_reranker() -> RerankClient:
    s = get_settings()
    return RerankClient(
        base_url=s.rerank_base_url,
        api_key=s.rerank_api_key,
        model=s.rerank_model,
    )


def _build_coverage_judge() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        streaming=False,
        temperature=0,
        max_tokens=256,
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
    final_top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Apply rerank threshold, top-K, and per-file diversity limits."""
    s = get_settings()
    final_hits: list[dict[str, Any]] = []
    per_file_counts: dict[int, int] = {}
    per_file_limit = max(1, s.rag_per_file_context_limit)
    limit = max(1, final_top_k if final_top_k is not None else s.rag_final_top_k)

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
        if len(final_hits) >= limit:
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


def _citations_from_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    citations: list[dict[str, Any]] = []
    for hit in hits:
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
    return citations


def _hit_key(hit: dict[str, Any]) -> tuple[Any, ...]:
    payload = hit.get("payload") or {}
    file_id = payload.get("file_id")
    chunk_index = payload.get("chunk_index")
    if file_id is not None and chunk_index is not None:
        return ("chunk", file_id, chunk_index)
    return (
        "fallback",
        file_id,
        payload.get("filename"),
        str(payload.get("text") or "")[:240],
    )


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for hit in hits:
        key = _hit_key(hit)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


async def _search_candidates(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    profile: dict[str, int],
) -> list[dict[str, Any]]:
    dense_vec, sparse_vec = await asyncio.gather(
        ingestion.embed_query(query),
        sparse_embed.embed_query(query),
    )
    return await qdrant_store.hybrid_search(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        user_id=user_id,
        kb_ids=kb_ids,
        top_k=profile["candidate_k"],
        prefetch_limit=profile["prefetch_limit"],
    )


async def _rank_hits(query: str, hits: list[dict[str, Any]]) -> list[tuple[int, float]]:
    passages = [_rerank_passage(h) for h in hits]
    try:
        return await _build_reranker().score(query, passages)
    except Exception:
        logger.exception("rerank_failed; falling back to dense order")
        return [(i, hits[i]["score"]) for i in range(len(hits))]


def _result_from_final_hits(
    *,
    query: str,
    candidates: list[dict[str, Any]],
    final_hits: list[dict[str, Any]],
) -> _RetrievalPass:
    if not final_hits:
        return _RetrievalPass(
            query=query,
            candidates=candidates,
            final_hits=[],
            context="",
            citations=[],
        )
    return _RetrievalPass(
        query=query,
        candidates=candidates,
        final_hits=final_hits,
        context=_format_context(final_hits),
        citations=_citations_from_hits(final_hits),
    )


async def _retrieve_pass(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    query_tags: Any | None,
    profile: dict[str, int],
) -> _RetrievalPass:
    s = get_settings()
    candidates = await _search_candidates(
        user_id=user_id,
        kb_ids=kb_ids,
        query=query,
        profile=profile,
    )
    if not candidates:
        return _result_from_final_hits(query=query, candidates=[], final_hits=[])

    ranked = await _rank_hits(query, candidates)
    final_hits = _select_final_hits(
        candidates,
        ranked,
        min_score=s.rag_rerank_min_score,
        query_tags=query_tags,
        final_top_k=profile["final_top_k"],
    )
    return _result_from_final_hits(
        query=query,
        candidates=candidates,
        final_hits=final_hits,
    )


async def _retrieve_combined_pass(
    *,
    query: str,
    alternate_query: str,
    first_candidates: list[dict[str, Any]],
    retry_candidates: list[dict[str, Any]],
    query_tags: Any | None,
    profile: dict[str, int],
) -> _RetrievalPass:
    s = get_settings()
    candidates = _dedupe_hits([*first_candidates, *retry_candidates])
    if not candidates:
        return _result_from_final_hits(query=query, candidates=[], final_hits=[])
    rerank_query = f"{query}\n{alternate_query}"
    ranked = await _rank_hits(rerank_query, candidates)
    final_hits = _select_final_hits(
        candidates,
        ranked,
        min_score=s.rag_rerank_min_score,
        query_tags=query_tags,
        final_top_k=profile["final_top_k"],
    )
    return _result_from_final_hits(
        query=query,
        candidates=candidates,
        final_hits=final_hits,
    )


_COVERAGE_SYSTEM = """
You judge whether retrieved RAG context can answer a user's question.

Return JSON only with this shape:
{
  "status": "answered" | "partial" | "miss",
  "reason": "short reason",
  "alternate_query": "one better search query, or empty string",
  "retry": true | false
}

Rules:
- answered: context directly supports the important parts of the question.
- partial: context supports some parts but misses important details.
- miss: context is empty, off-topic, or does not answer the question.
- Set retry=true only for partial/miss when a different retrieval query may help.
- The alternate_query must be a single natural-language search query.
- Preserve exact code symbols, product names, vendor names, platforms, and errors.
""".strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_coverage_judgment(text: str) -> CoverageJudgment | None:
    parsed = _extract_json_object(text)
    if parsed is None:
        return None

    status = str(parsed.get("status") or "").strip().lower()
    if status not in {"answered", "partial", "miss"}:
        return None

    reason = str(parsed.get("reason") or "").strip()
    alternate_query = str(parsed.get("alternate_query") or "").strip()
    if "\n" in alternate_query:
        alternate_query = " ".join(alternate_query.split())
    if len(alternate_query) > 500:
        alternate_query = alternate_query[:500].strip()

    retry_value = parsed.get("retry")
    retry = retry_value is True or (
        isinstance(retry_value, str) and retry_value.strip().lower() == "true"
    )

    return CoverageJudgment(
        status=status,
        reason=reason[:500],
        alternate_query=alternate_query or None,
        retry=retry,
    )


async def _judge_coverage(
    *,
    user_message: str,
    retrieval_query: str,
    context: str,
) -> CoverageJudgment | None:
    prompt = (
        f"User question:\n{user_message}\n\n"
        f"Retrieval query:\n{retrieval_query}\n\n"
        "Retrieved context:\n"
        f"{context if context else '[no retrieved context]'}"
    )
    try:
        result = await _build_coverage_judge().ainvoke(
            [SystemMessage(content=_COVERAGE_SYSTEM), HumanMessage(content=prompt)]
        )
    except Exception:
        logger.exception("coverage_judge_failed; keeping first retrieval pass")
        return None
    return _parse_coverage_judgment(str(result.content or ""))


def _same_query(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


async def retrieve_context(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    query_tags: Any | None = None,
    deep_mode: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    """Hybrid dense+sparse search → cross-encoder rerank → top-K context.

    Returns (context_block, citations). `citations` is unique by file_id
    and reflects the *post-rerank* hits (i.e., what actually went into
    the prompt).
    """
    s = get_settings()
    profile = _retrieval_profile(deep_mode=deep_mode)
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
        top_k=profile["candidate_k"],
        prefetch_limit=profile["prefetch_limit"],
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
        final_top_k=profile["final_top_k"],
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


async def retrieve_context_checked(
    *,
    user_id: int,
    kb_ids: list[int] | None,
    query: str,
    user_message: str,
    query_tags: Any | None = None,
    deep_mode: bool = False,
) -> RagContextResult:
    """Chat-focused retrieval with optional deep coverage critique.

    Normal mode behaves like `retrieve_context`. Deep mode first retrieves with
    the wider profile, asks a coverage judge whether the context answers the
    user, and retries once with an alternate query when the first pass is
    partial or off-topic. Judge failures degrade to the first retrieval pass.
    """
    first_profile = _retrieval_profile(deep_mode=deep_mode)
    first = await _retrieve_pass(
        user_id=user_id,
        kb_ids=kb_ids,
        query=query,
        query_tags=query_tags,
        profile=first_profile,
    )

    if not deep_mode:
        return RagContextResult(
            context=first.context,
            citations=first.citations,
            diagnostics=RagDiagnostics(deep_mode=False),
        )

    first_judgment = await _judge_coverage(
        user_message=user_message,
        retrieval_query=query,
        context=first.context,
    )
    if first_judgment is None:
        return RagContextResult(
            context=first.context,
            citations=first.citations,
            diagnostics=RagDiagnostics(deep_mode=True),
        )

    diagnostics = RagDiagnostics(
        deep_mode=True,
        coverage_status=first_judgment.status,
        coverage_reason=first_judgment.reason,
    )
    if (
        not first_judgment.needs_retry()
        or _same_query(first_judgment.alternate_query, query)
    ):
        return RagContextResult(
            context=first.context,
            citations=first.citations,
            diagnostics=diagnostics,
        )

    retry_query = first_judgment.alternate_query or query
    try:
        retry_candidates = await _search_candidates(
            user_id=user_id,
            kb_ids=kb_ids,
            query=retry_query,
            profile=_retrieval_profile(deep_mode=False),
        )
        combined = await _retrieve_combined_pass(
            query=query,
            alternate_query=retry_query,
            first_candidates=first.candidates,
            retry_candidates=retry_candidates,
            query_tags=query_tags,
            profile=first_profile,
        )
    except Exception:
        logger.exception("coverage_retry_failed; keeping first retrieval pass")
        return RagContextResult(
            context=first.context,
            citations=first.citations,
            diagnostics=RagDiagnostics(
                deep_mode=True,
                coverage_status=first_judgment.status,
                coverage_reason=first_judgment.reason,
                retried=True,
                retry_query=retry_query,
                retry_reason="retry_failed",
            ),
        )

    final_judgment = await _judge_coverage(
        user_message=user_message,
        retrieval_query=f"{query}\n{retry_query}",
        context=combined.context,
    )
    if final_judgment is None:
        final_status = "not_checked"
        final_reason = ""
    else:
        final_status = final_judgment.status
        final_reason = final_judgment.reason

    return RagContextResult(
        context=combined.context,
        citations=combined.citations,
        diagnostics=RagDiagnostics(
            deep_mode=True,
            coverage_status=final_status,
            coverage_reason=final_reason,
            retried=True,
            retry_query=retry_query,
            retry_reason=first_judgment.reason,
        ),
    )
