"""Demo: multi-turn chat REPL with optional RAG (rewrite -> retrieve -> stream).

Standalone re-implementation of the production chat path. Mirrors:
  - backend/app/features/chat/services/chat_service.py
    (SYSTEM_PROMPT, REWRITE_SYSTEM, rewrite_for_retrieval, stream_answer)
  - backend/app/features/rag/services/rag.py (retrieve_context)
as of commit a9ad2d5. If those files diverge, sync this file by hand.

Usage:
  python 03_chat.py                # RAG on
  python 03_chat.py --no-rag       # plain LLM, skip retrieval

REPL commands:
  :rag on        toggle retrieval back on
  :rag off       skip retrieval for subsequent turns
  :reset         clear conversation history
  :exit          quit (Ctrl-D / Ctrl-C also work)
"""
from __future__ import annotations

import argparse
import json
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
    LLM_API_KEY,
    LLM_MODEL,
    LLM_URL,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RERANK_API_KEY,
    RERANK_MODEL,
    RERANK_URL,
    SPARSE_VEC,
)

# Production-parity knobs (see backend/app/core/config.py + chat_service.py).
DENSE_TOP_K = 20
PREFETCH_LIMIT = 40
RERANK_THRESHOLD = 0.10
FINAL_TOP_K = 5
HISTORY_MAX = 20  # chat_service.HISTORY_MAX_MESSAGES

# --- Production-parity prompts -------------------------------------------
# The chat SYSTEM_PROMPT explicitly grants the model access to history;
# this fixed a bug where Gemma refused on personal-fact recall ("I do not
# have the capability to remember") because an earlier prompt told it to
# "ground in context, avoid speculation".

CHAT_SYSTEM = (
    "You are KnowledgeDeck, a helpful conversational assistant.\n\n"
    "This is a multi-turn conversation. The messages above (if any) are the "
    "prior turns — treat them as the running context. Refer back to facts, "
    "preferences, and details the user has shared earlier in the conversation, "
    "and maintain continuity across turns.\n\n"
    "When a `Context:` section is included by the system, prefer it as the "
    "source for factual claims about the user's documents. When `Context:` is "
    "absent or irrelevant to the question, answer from your general knowledge.\n\n"
    "Be concise. Do not refuse to recall information the user has shared "
    "earlier in this conversation — the conversation history above is yours "
    "to use."
)

# The rewriter expands abbreviations (k8s -> Kubernetes) and resolves
# multi-turn pronouns. Cross-encoders score parenthetical noise badly, so
# we drop the original token instead of keeping it (k8s -> "Kubernetes",
# NOT "Kubernetes (k8s)" — the latter dropped rerank score 0.66 -> 0.04
# in our k8s-no-citation incident).
REWRITE_SYSTEM = (
    "You rewrite user questions into standalone search queries optimized "
    "for retrieval against a knowledge base, where a cross-encoder "
    "reranker scores (query, passage) pairs. Cross-encoders work best on "
    "natural-language queries with full canonical terms, not bare tokens "
    "or abbreviations.\n\n"
    "You may receive:\n"
    "- A first-turn question (no conversation history above).\n"
    "- A follow-up question that uses pronouns ('that', 'it', 'this "
    "one'), elliptical references ('and Python?'), or implicit context "
    "that only makes sense relative to the prior turns.\n\n"
    "Apply these rules in order:\n"
    "1. Resolve all pronouns / references / ellipsis against the history.\n"
    "2. Replace technical abbreviations with their full canonical form. "
    "Drop the abbreviation entirely — do NOT keep it in parentheses, "
    "because parenthetical noise lowers cross-encoder rerank scores. "
    "Examples:\n"
    "   k8s -> Kubernetes\n"
    "   aws -> Amazon Web Services\n"
    "   gpu -> graphics processing unit\n"
    "   ml  -> machine learning\n"
    "   db  -> database\n"
    "3. If the question is a single bare term (one word or one acronym), "
    "reformulate it into a natural question. Examples:\n"
    "   'Kubernetes'  -> 'What is Kubernetes?'\n"
    "   'embeddings'  -> 'What are embeddings?'\n"
    "   'k8s'         -> 'What is Kubernetes?'\n"
    "4. If the question is already a complete natural-language question "
    "with no abbreviations and no references to resolve, output it "
    "unchanged.\n\n"
    "Output: ONE LINE. The rewritten query only. No quotation marks. No "
    "'Query:' prefix. No explanation."
)


# --- BM25 model cache ----------------------------------------------------
# fastembed loads the BM25 IDF tables on first .embed() call (~tens of MB);
# cache the model so subsequent turns don't pay that cost.

_bm25_model: SparseTextEmbedding | None = None


def _bm25() -> SparseTextEmbedding:
    global _bm25_model
    if _bm25_model is None:
        _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _bm25_model


# --- Embedding / rerank / Qdrant primitives (same shape as 02_rag_query.py)

def dense_embed(text: str) -> list[float]:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{EMBED_URL.rstrip('/')}/embeddings",
            json={"model": EMBED_MODEL, "input": [text]},
            headers={"Authorization": f"Bearer {EMBED_API_KEY}"},
        )
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]


def sparse_embed(text: str) -> tuple[list[int], list[float]]:
    v = next(iter(_bm25().embed([text])))
    return (
        [int(i) for i in v.indices.tolist()],
        [float(x) for x in v.values.tolist()],
    )


def hybrid_search(
    client: QdrantClient,
    dense: list[float],
    sparse: tuple[list[int], list[float]],
) -> list[dict]:
    flt = qm.Filter(
        must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=DEMO_USER_ID))]
    )
    resp = client.query_points(
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
        limit=DENSE_TOP_K,
        with_payload=True,
    )
    return [{"score": p.score, "payload": p.payload} for p in resp.points]


def rerank(query: str, passages: list[str]) -> list[tuple[int, float]]:
    if not passages:
        return []
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{RERANK_URL.rstrip('/')}/score",
            json={"model": RERANK_MODEL, "text_1": query, "text_2": passages},
            headers={"Authorization": f"Bearer {RERANK_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json().get("data", [])
    out = [
        (int(row.get("index", i)), float(row.get("score", 0.0)))
        for i, row in enumerate(data)
    ]
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def retrieve_context(client: QdrantClient, query: str) -> tuple[str, list[dict]]:
    """Full retrieval pipeline: dual embed -> RRF -> rerank -> threshold ->
    format as the `Context:` block we paste into the prompt + a citation
    list (deduped by file_id)."""
    hits = hybrid_search(client, dense_embed(query), sparse_embed(query))
    if not hits:
        return "", []
    passages = [h["payload"]["text"] for h in hits]
    ranked = rerank(query, passages)

    final: list[dict] = []
    for idx, score in ranked:
        if score < RERANK_THRESHOLD:
            continue
        h = dict(hits[idx])
        h["score"] = score
        final.append(h)
        if len(final) >= FINAL_TOP_K:
            break
    if not final:
        return "", []

    blocks: list[str] = []
    for i, h in enumerate(final, start=1):
        p = h["payload"]
        loc = f" (p.{p['page_number']})" if p.get("page_number") else ""
        blocks.append(f"[{i}] {p['filename']}{loc}\n{p['text']}")

    citations: list[dict] = []
    seen: set[int] = set()
    for h in final:
        fid = h["payload"]["file_id"]
        if fid in seen:
            continue
        seen.add(fid)
        citations.append({"file_id": fid, "filename": h["payload"]["filename"]})

    return "\n\n".join(blocks), citations


# --- Rewriter (one non-streamed LLM call) --------------------------------

def rewrite_for_retrieval(history: list[dict], user_message: str) -> str:
    """On any LLM error or off-rails output, fall back to the raw user
    message so retrieval still runs."""
    if history:
        # Multi-turn: feed last 6 turns so the rewriter can resolve
        # pronouns. Long assistant turns are clipped because only the
        # gist matters for reference resolution.
        recent = history[-6:]
        lines: list[str] = []
        for m in recent:
            role = "User" if m["role"] == "user" else "Assistant"
            body = m["content"] if len(m["content"]) <= 400 else m["content"][:400] + "..."
            lines.append(f"{role}: {body}")
        prompt = (
            "Conversation history:\n"
            + "\n".join(lines)
            + f"\n\nMost recent question:\n{user_message}\n\nStandalone query:"
        )
    else:
        prompt = f"Question:\n{user_message}\n\nStandalone search query:"

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 128,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                f"{LLM_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
        # Defensive: bail if model went off the rails (multiline,
        # too-long, or empty output).
        if not text or len(text) > 500 or "\n" in text:
            return user_message
        return text
    except Exception as exc:
        print(f"[rewrite-failed] {exc}; using raw query", file=sys.stderr)
        return user_message


# --- Streaming reply (SSE) -----------------------------------------------

def stream_reply(messages: list[dict]) -> str:
    """Stream tokens to stdout, return the full assembled text."""
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    full: list[str] = []
    with httpx.Client(timeout=120.0) as client:
        with client.stream(
            "POST",
            f"{LLM_URL.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = chunk["choices"][0].get("delta", {}).get("content")
                if delta:
                    print(delta, end="", flush=True)
                    full.append(delta)
    print()
    return "".join(full)


# --- REPL ----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-rag", action="store_true", help="disable retrieval")
    args = ap.parse_args()

    use_rag = not args.no_rag
    history: list[dict] = []
    qclient = QdrantClient(url=QDRANT_URL) if use_rag else None
    print(f"[chat] model={LLM_MODEL}  rag={'on' if use_rag else 'off'}")
    print("       commands: :rag on | :rag off | :reset | :exit\n")

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        if user in (":exit", ":quit"):
            return 0
        if user == ":reset":
            history.clear()
            print("[history cleared]")
            continue
        if user == ":rag on":
            use_rag = True
            qclient = qclient or QdrantClient(url=QDRANT_URL)
            print("[rag on]")
            continue
        if user == ":rag off":
            use_rag = False
            print("[rag off]")
            continue

        # 1. RAG retrieval (rewrite -> dual embed -> RRF -> rerank -> threshold).
        context = ""
        citations: list[dict] = []
        if use_rag:
            assert qclient is not None
            standalone = rewrite_for_retrieval(history, user)
            if standalone != user:
                print(f"[rewrite]   {standalone}")
            context, citations = retrieve_context(qclient, standalone)
            if citations:
                print(f"[citations] {', '.join(c['filename'] for c in citations)}")
            else:
                print("[citations] (none — answering from general knowledge)")

        # 2. Build messages: SYSTEM_PROMPT + history (up to HISTORY_MAX) +
        #    optional "Context:" system note + current user turn.
        msgs: list[dict] = [{"role": "system", "content": CHAT_SYSTEM}]
        for m in history[-HISTORY_MAX:]:
            msgs.append({"role": m["role"], "content": m["content"]})
        if context:
            msgs.append({"role": "system", "content": f"Context:\n{context}"})
        msgs.append({"role": "user", "content": user})

        # 3. Stream the reply, then commit both turns to history.
        print("bot> ", end="", flush=True)
        reply = stream_reply(msgs)
        history.append({"role": "user", "content": user})
        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    sys.exit(main())
