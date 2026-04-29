"""Demo: RAG retrieval (dual-embed -> hybrid + RRF -> rerank -> threshold).

Standalone re-implementation of the production retrieval pipeline. Mirrors:
  - backend/app/features/rag/services/rag.py
  - backend/app/features/rag/services/qdrant_store.py (hybrid_search)
  - backend/app/features/rag/services/sparse_embed.py
  - backend/app/features/rag/services/model_clients.py (RerankClient)
as of commit a9ad2d5. If those files diverge, sync this file by hand.

Usage:
  python 02_rag_query.py "what is kubernetes?"
  python 02_rag_query.py "your query" --top-k 3 --threshold 0.05

Run 01_kb_ingest.py first so DEMO_USER_ID has chunks to retrieve.
"""
from __future__ import annotations

import argparse
import sys

import httpx
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from _common import (
    DEMO_USER_ID,
    DENSE_VEC,
    EMBED_API_KEY,
    EMBED_MODEL,
    EMBED_URL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RERANK_API_KEY,
    RERANK_MODEL,
    RERANK_URL,
    SPARSE_VEC,
)

# Production parity: see backend/app/core/config.py.
DENSE_TOP_K = 20         # rag_dense_top_k: candidates fetched before rerank
PREFETCH_LIMIT = 40      # qdrant prefetch per modality before RRF fuse
RERANK_THRESHOLD = 0.10  # rag_rerank_min_score
FINAL_TOP_K = 5          # rag_final_top_k: chunks that survive into prompt


# ---------------------------------------------------------------- 1. Dual embed query

def dense_embed_query(text: str) -> list[float]:
    payload = {"model": EMBED_MODEL, "input": [text]}
    headers = {"Authorization": f"Bearer {EMBED_API_KEY}"}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{EMBED_URL.rstrip('/')}/embeddings",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


def sparse_embed_query(text: str) -> tuple[list[int], list[float]]:
    model = SparseTextEmbedding(model_name="Qdrant/bm25")
    v = next(iter(model.embed([text])))
    return (
        [int(i) for i in v.indices.tolist()],
        [float(x) for x in v.values.tolist()],
    )


# ---------------------------------------------------------------- 2. Hybrid search
# Qdrant Query API: prefetch dense top-N + sparse top-N independently,
# then fuse via Reciprocal Rank Fusion. RRF is score-scale-agnostic
# (it ranks by 1/(k+rank)), which is exactly what we want when fusing
# two heterogeneous score distributions (cosine vs BM25).

def hybrid_search(
    client: QdrantClient,
    *,
    dense: list[float],
    sparse: tuple[list[int], list[float]],
    user_id: int,
    top_k: int,
) -> list[dict]:
    flt = qm.Filter(
        must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id))]
    )
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        prefetch=[
            qm.Prefetch(query=dense, using=DENSE_VEC, filter=flt, limit=PREFETCH_LIMIT),
            qm.Prefetch(
                query=qm.SparseVector(indices=sparse[0], values=sparse[1]),
                using=SPARSE_VEC,
                filter=flt,
                limit=PREFETCH_LIMIT,
            ),
        ],
        query=qm.FusionQuery(fusion=qm.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )
    return [{"score": p.score, "payload": p.payload} for p in response.points]


# ---------------------------------------------------------------- 3. Cross-encoder rerank
# vLLM in `--runner pooling --convert classify` mode exposes /v1/score.
# Body: {model, text_1, text_2}. text_1=query, text_2=list of passages.
# Returns {"data":[{"index":i,"score":f}, ...]}. Higher = more relevant.

def rerank(query: str, passages: list[str]) -> list[tuple[int, float]]:
    if not passages:
        return []
    payload = {"model": RERANK_MODEL, "text_1": query, "text_2": passages}
    headers = {"Authorization": f"Bearer {RERANK_API_KEY}"}
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{RERANK_URL.rstrip('/')}/score",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    out: list[tuple[int, float]] = []
    for i, row in enumerate(data):
        idx = int(row.get("index", i))
        score = float(row.get("score", 0.0))
        out.append((idx, score))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


# ---------------------------------------------------------------- 4. CLI driver

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=FINAL_TOP_K)
    ap.add_argument("--threshold", type=float, default=RERANK_THRESHOLD)
    args = ap.parse_args()

    print(f"[query]   {args.query!r}")
    print(f"[dense]   embedding query via {EMBED_URL}")
    dense = dense_embed_query(args.query)
    print(f"[sparse]  embedding query via fastembed Qdrant/bm25")
    sparse = sparse_embed_query(args.query)

    print(f"[qdrant]  hybrid search: prefetch={PREFETCH_LIMIT} per modality, RRF fused -> top {DENSE_TOP_K}")
    client = QdrantClient(url=QDRANT_URL)
    hits = hybrid_search(
        client, dense=dense, sparse=sparse, user_id=DEMO_USER_ID, top_k=DENSE_TOP_K
    )
    print(f"[qdrant]  {len(hits)} candidate(s)")
    if not hits:
        print("\nno hits — did you run 01_kb_ingest.py first?")
        return 0

    passages = [h["payload"]["text"] for h in hits]
    print(f"[rerank]  cross-encoder via {RERANK_URL} ({RERANK_MODEL})")
    ranked = rerank(args.query, passages)

    print(f"[filter]  threshold={args.threshold}, keep top {args.top_k}")
    final: list[dict] = []
    for orig_idx, score in ranked:
        if score < args.threshold:
            continue
        h = dict(hits[orig_idx])
        h["score"] = score
        final.append(h)
        if len(final) >= args.top_k:
            break

    if not final:
        # Production behavior: empty context -> LLM falls back to general
        # knowledge, no "Context:" header is inserted into the prompt.
        print("\nno chunks survived rerank threshold")
        print("(in production this returns ('', []) so the LLM answers from general knowledge)")
        return 0

    print(f"\n[results] {len(final)} chunk(s):\n")
    for i, h in enumerate(final, start=1):
        p = h["payload"]
        page = f" p.{p['page_number']}" if p.get("page_number") else ""
        snippet = p["text"].replace("\n", " ")
        ellipsis = "..." if len(snippet) > 200 else ""
        print(f"  [{i}] score={h['score']:.4f}  {p['filename']}{page}")
        print(f"      {snippet[:200]}{ellipsis}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
