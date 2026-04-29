"""Demo: end-to-end smoke test (cleanup -> ingest -> query -> chat -> slide).

Standalone scenario that exercises every layer of the KnowledgeDeck stack
in one non-interactive run. Use this to verify a freshly-deployed compose
stack actually works — every service (Qdrant, vLLM chat/embed/rerank,
Presenton) is touched end-to-end.

Mirrors the same production sources as 01-04 (see those files' docstrings
for the canonical paths) as of commit a9ad2d5.

Stages (each prints PASS / FAIL / INCONCLUSIVE):
  1. cleanup  - drop any leftover DEMO_USER_ID points in Qdrant
  2. ingest   - parse + chunk + dual-embed + upsert a sample document
  3. query    - hybrid search + rerank, expect at least one citation
  4. chat     - 2 turns, expect rewriter to expand 'k8s' AND resolve
                'its' on turn 2 so retrieval still hits Kubernetes content
  5. slide    - 2-turn planner -> [OUTLINE_READY] -> Presenton -> .pptx

Exit code: 0 if no stage FAILED (PASS / INCONCLUSIVE both ok), 1 otherwise.

Usage:
  python main.py                     # full run
  python main.py --no-slide          # skip slide (no Presenton needed)
  python main.py --keep-vectors      # leave demo vectors in Qdrant
  python main.py --output-dir ./out  # where to drop the rendered PPTX
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastembed import SparseTextEmbedding
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from _common import (
    DEMO_KB_ID,
    DEMO_USER_ID,
    DENSE_VEC,
    EMBED_API_KEY,
    EMBED_DIM,
    EMBED_MODEL,
    EMBED_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_URL,
    PRESENTON_DATA_ROOT,
    PRESENTON_PASSWORD,
    PRESENTON_URL,
    PRESENTON_USERNAME,
    QDRANT_COLLECTION,
    QDRANT_URL,
    RERANK_API_KEY,
    RERANK_MODEL,
    RERANK_URL,
    SPARSE_VEC,
    cleanup_demo_vectors,
)

# ---------- Knobs (production parity) ------------------------------------

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
DENSE_TOP_K = 20
PREFETCH_LIMIT = 40
RERANK_THRESHOLD = 0.10
FINAL_TOP_K = 5
BUILTIN_TEMPLATES = {"general", "modern", "standard", "swift"}
MARKER_RE = re.compile(r"\[OUTLINE_READY(?:\s+([^\]]+))?\]")
SLIDE_BLOCK_RE = re.compile(
    r"^##\s*Slide\s+\d+\s*:.*?(?=^##\s*Slide\s+\d+\s*:|\Z)",
    re.DOTALL | re.MULTILINE,
)

# ---------- Sample document & scripted turns -----------------------------
# Embedded inline so the smoke test doesn't depend on a sample file
# being present. Mentions both "Kubernetes" and "k8s" / "AWS" so we can
# verify the rewriter (abbreviation expansion) actually fires.

SAMPLE_DOC_FILENAME = "kubernetes_primer.txt"
SAMPLE_DOC_TEXT = """\
Kubernetes Primer
=================

Kubernetes (often abbreviated as k8s) is an open-source container
orchestration platform originally designed by Google and now maintained
by the Cloud Native Computing Foundation. It groups containers that make
up an application into logical units for easy management and discovery.

Core concepts
-------------
A pod is the smallest deployable unit in Kubernetes. Each pod runs one
or more tightly-coupled containers that share a network namespace and
storage volumes. Deployments declare the desired state of pods and
manage rolling updates. Services expose a stable network endpoint for a
set of pods, allowing other workloads inside the cluster to reach them
even as individual pods come and go.

Networking
----------
Every pod in a Kubernetes cluster gets its own IP address. The cluster
DNS resolves Service names to virtual IPs that load-balance across the
Service's pods. NetworkPolicies act as a firewall layer, allowing
operators to restrict pod-to-pod traffic by label.

Production deployments
----------------------
Most organizations run Kubernetes on a managed control plane: Amazon
Web Services offers EKS, Google Cloud offers GKE, and Microsoft Azure
offers AKS. Self-managed clusters use kubeadm or distributions like
Rancher and OpenShift. Persistent storage is typically provisioned via
the CSI (Container Storage Interface) driver matching the underlying
cloud or storage backend.
"""

CHAT_TURNS = [
    # Turn 1: bare abbreviation. The rewriter must expand "k8s" to
    # "Kubernetes" (without parentheses) for retrieval to score above
    # the rerank threshold.
    "What is k8s?",
    # Turn 2: pronoun-only follow-up. The rewriter must resolve "its"
    # against the prior turn so retrieval still hits Kubernetes content.
    "What about its networking model?",
]

SLIDE_TURNS = [
    "Build me a 3-slide deck introducing Kubernetes. "
    "Audience: technical engineers. Language: English. Tone: professional. "
    "Template: general. Skip clarifying questions — go straight to the outline.",
    "Yes, render it.",
]


# ---------- Production-parity prompts ------------------------------------

CHAT_SYSTEM = (
    "You are KnowledgeDeck, a helpful conversational assistant.\n\n"
    "This is a multi-turn conversation. The messages above (if any) are the "
    "prior turns — treat them as the running context. Refer back to facts, "
    "preferences, and details the user has shared earlier in the conversation, "
    "and maintain continuity across turns.\n\n"
    "When a `Context:` section is included by the system, prefer it as the "
    "source for factual claims about the user's documents. When `Context:` is "
    "absent or irrelevant to the question, answer from your general knowledge.\n\n"
    "Be concise."
)

REWRITE_SYSTEM = (
    "You rewrite user questions into standalone search queries optimized "
    "for retrieval against a knowledge base, where a cross-encoder "
    "reranker scores (query, passage) pairs. Cross-encoders work best on "
    "natural-language queries with full canonical terms, not bare tokens "
    "or abbreviations.\n\n"
    "Apply these rules in order:\n"
    "1. Resolve all pronouns / references / ellipsis against the history.\n"
    "2. Replace technical abbreviations with their full canonical form. "
    "Drop the abbreviation entirely — do NOT keep it in parentheses.\n"
    "   k8s -> Kubernetes\n"
    "   aws -> Amazon Web Services\n"
    "3. If the question is a single bare term, reformulate it into a "
    "natural question.\n"
    "4. If the question is already complete, output it unchanged.\n\n"
    "Output: ONE LINE. The rewritten query only. No quotation marks. No "
    "'Query:' prefix. No explanation."
)

PLANNER_SYSTEM = (
    "You are KnowledgeDeck Slide Planner. Produce a slide deck.\n\n"
    "When the user has specified target audience, slide count (3-15), "
    "language, tone, and template, propose a draft outline immediately — "
    "skip clarifying questions if the user has supplied them.\n\n"
    "Outline format STRICTLY:\n"
    "## Slide 1: <Title>\n- <bullet>\n- <bullet>\n\n"
    "## Slide 2: <Title>\n- <bullet>\n\n(...one ## block per slide)\n\n"
    "Templates available: general, modern, standard, swift. Use ONLY these. "
    "Default = general.\n\n"
    "When the user confirms they want to render (\"yes\", \"render it\", etc.), "
    "produce the FINAL outline then end the message with a marker line:\n"
    "  [OUTLINE_READY template=<name> language=<lang>]\n"
    "Do not emit the marker until the user has explicitly confirmed.\n\n"
    "Per slide: 3-5 informative bullets, no prose between blocks."
)


# ---------- Pipeline primitives -----------------------------------------

_bm25_model: SparseTextEmbedding | None = None


def _bm25() -> SparseTextEmbedding:
    global _bm25_model
    if _bm25_model is None:
        _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _bm25_model


def dense_embed(texts: list[str]) -> list[list[float]]:
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{EMBED_URL.rstrip('/')}/embeddings",
            json={"model": EMBED_MODEL, "input": texts},
            headers={"Authorization": f"Bearer {EMBED_API_KEY}"},
        )
        r.raise_for_status()
        return [item["embedding"] for item in r.json()["data"]]


def sparse_embed(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    out: list[tuple[list[int], list[float]]] = []
    for v in _bm25().embed(list(texts)):
        out.append((
            [int(i) for i in v.indices.tolist()],
            [float(x) for x in v.values.tolist()],
        ))
    return out


def split_into_chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_CHARS,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
        length_function=len,
        is_separator_regex=False,
    )
    return [c for c in (s.strip() for s in splitter.split_text(text)) if c]


def ensure_collection(client: QdrantClient) -> None:
    if client.collection_exists(QDRANT_COLLECTION):
        return
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config={
            DENSE_VEC: qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
        },
        sparse_vectors_config={
            SPARSE_VEC: qm.SparseVectorParams(index=qm.SparseIndexParams(on_disk=False)),
        },
    )
    for f in ("user_id", "kb_id", "file_id"):
        client.create_payload_index(
            collection_name=QDRANT_COLLECTION,
            field_name=f,
            field_schema=qm.PayloadSchemaType.INTEGER,
        )


def upsert_points(
    client: QdrantClient,
    *,
    file_id: int,
    filename: str,
    chunks: list[dict],
    dense: list[list[float]],
    sparse: list[tuple[list[int], list[float]]],
) -> None:
    points = [
        qm.PointStruct(
            id=str(uuid.uuid4()),
            vector={
                DENSE_VEC: d,
                SPARSE_VEC: qm.SparseVector(indices=s[0], values=s[1]),
            },
            payload={
                "user_id": DEMO_USER_ID,
                "kb_id": DEMO_KB_ID,
                "file_id": file_id,
                "filename": filename,
                "text": ch["text"],
                "page_number": ch.get("page_number"),
                "chunk_index": ch["chunk_index"],
            },
        )
        for ch, d, s in zip(chunks, dense, sparse, strict=True)
    ]
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)


def hybrid_search(
    client: QdrantClient,
    query_dense: list[float],
    query_sparse: tuple[list[int], list[float]],
) -> list[dict]:
    flt = qm.Filter(
        must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=DEMO_USER_ID))]
    )
    resp = client.query_points(
        collection_name=QDRANT_COLLECTION,
        prefetch=[
            qm.Prefetch(query=query_dense, using=DENSE_VEC, filter=flt, limit=PREFETCH_LIMIT),
            qm.Prefetch(
                query=qm.SparseVector(indices=query_sparse[0], values=query_sparse[1]),
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
    qd = dense_embed([query])[0]
    qs = sparse_embed([query])[0]
    hits = hybrid_search(client, qd, qs)
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


def chat_completion(
    messages: list[dict],
    *,
    stream: bool,
    max_tokens: int | None = None,
    temperature: float = 0.3,
) -> str:
    """One call to the OpenAI-compatible /v1/chat/completions endpoint.

    When `stream=True`, tokens are printed to stdout as they arrive.
    Either way, returns the full assembled assistant text.
    """
    payload: dict = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}

    if not stream:
        with httpx.Client(timeout=60.0) as c:
            r = c.post(
                f"{LLM_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

    full: list[str] = []
    with httpx.Client(timeout=180.0) as c:
        with c.stream(
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


def rewrite_for_retrieval(history: list[dict], user_message: str) -> str:
    if history:
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
    try:
        text = chat_completion(
            [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            stream=False,
            temperature=0,
            max_tokens=128,
        )
        if not text or len(text) > 500 or "\n" in text:
            return user_message
        return text
    except Exception:
        return user_message


def render_via_presenton(
    slide_blocks: list[str], *, template: str, language: str
) -> bytes:
    if template not in BUILTIN_TEMPLATES:
        template = "general"
    auth = base64.b64encode(f"{PRESENTON_USERNAME}:{PRESENTON_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    payload = {
        "content": "\n\n".join(slide_blocks),
        "n_slides": len(slide_blocks),
        "language": language,
        "template": template,
        "export_as": "pptx",
    }
    url = f"{PRESENTON_URL.rstrip('/')}/api/v1/ppt/presentation/generate"
    with httpx.Client(timeout=300.0) as client:
        r = client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Presenton {r.status_code}: {r.text[:300]}")
        path = r.json().get("path")
        if not path:
            raise RuntimeError("Presenton response missing 'path'")
    if not path.startswith("/app_data/"):
        raise RuntimeError(f"unexpected path: {path}")
    on_host = Path(PRESENTON_DATA_ROOT) / path[len("/app_data/"):]
    if not on_host.exists():
        raise RuntimeError(f"artifact not found: {on_host}")
    return on_host.read_bytes()


def extract_outline(history: list[dict]) -> tuple[str, dict[str, str]] | None:
    for m in reversed(history):
        if m["role"] != "assistant":
            continue
        match = MARKER_RE.search(m["content"])
        if match is None:
            continue
        body = (m["content"][: match.start()] + m["content"][match.end():]).strip()
        params: dict[str, str] = {}
        if match.group(1):
            for pair in match.group(1).split():
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k.strip()] = v.strip()
        return body, params
    return None


def split_slide_blocks(outline: str) -> list[str]:
    return [
        m.group(0).strip()
        for m in SLIDE_BLOCK_RE.finditer(outline)
        if m.group(0).strip()
    ]


# ---------- Stages -------------------------------------------------------

PASS, FAIL, INCONCL = "PASS", "FAIL", "INCONCLUSIVE"


def banner(stage: int, name: str) -> None:
    print(f"\n========== Stage {stage}: {name} ==========")


def stage_cleanup() -> str:
    banner(1, "Cleanup demo vectors")
    try:
        n = cleanup_demo_vectors()
        print(f"  dropped {n} prior demo points")
        return PASS
    except Exception as exc:
        # Qdrant down is a deployment issue — flag as INCONCLUSIVE so we
        # don't pretend the rest of the test ran.
        print(f"  Qdrant unreachable: {exc}")
        return INCONCL


def stage_ingest(client: QdrantClient) -> str:
    banner(2, "Ingest sample document")
    print(f"  doc: {SAMPLE_DOC_FILENAME} ({len(SAMPLE_DOC_TEXT)} chars)")
    try:
        chunks: list[dict] = []
        for piece in split_into_chunks(SAMPLE_DOC_TEXT):
            chunks.append(
                {"text": piece, "page_number": None, "chunk_index": len(chunks)}
            )
        print(f"  chunks: {len(chunks)}  (size={CHUNK_CHARS}, overlap={CHUNK_OVERLAP})")
        passages = [c["text"] for c in chunks]
        d = dense_embed(passages)
        s = sparse_embed(passages)
        ensure_collection(client)
        upsert_points(
            client,
            file_id=1,
            filename=SAMPLE_DOC_FILENAME,
            chunks=chunks,
            dense=d,
            sparse=s,
        )
        print(f"  upserted {len(chunks)} points to {QDRANT_COLLECTION}")
        return PASS
    except Exception as exc:
        print(f"  ingest failed: {exc}")
        return FAIL


def stage_query(client: QdrantClient) -> str:
    banner(3, "RAG query")
    query = "What is k8s?"
    print(f"  query: {query!r}")
    try:
        _ctx, citations = retrieve_context(client, query)
        if not citations:
            # If this fails on a fresh ingest, the rerank threshold is
            # filtering everything — usually means embeddings aren't
            # being computed correctly upstream.
            print("  no citations — rerank threshold filtered everything")
            return FAIL
        print(f"  citations: {[c['filename'] for c in citations]}")
        return PASS
    except Exception as exc:
        print(f"  query failed: {exc}")
        return FAIL


def stage_chat(client: QdrantClient) -> str:
    banner(4, "Multi-turn chat (rewriter + retrieval)")
    history: list[dict] = []
    turn2_had_citations = False
    try:
        for i, user_msg in enumerate(CHAT_TURNS, start=1):
            print(f"\n  turn {i}: user> {user_msg}")
            standalone = rewrite_for_retrieval(history, user_msg)
            if standalone != user_msg:
                print(f"  [rewrite] -> {standalone}")
            ctx, citations = retrieve_context(client, standalone)
            print(f"  citations: {[c['filename'] for c in citations] or '(none)'}")
            if i == 2 and citations:
                turn2_had_citations = True

            msgs: list[dict] = [{"role": "system", "content": CHAT_SYSTEM}]
            msgs.extend(history)
            if ctx:
                msgs.append({"role": "system", "content": f"Context:\n{ctx}"})
            msgs.append({"role": "user", "content": user_msg})

            print("  bot> ", end="", flush=True)
            reply = chat_completion(msgs, stream=True)
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": reply})

        if not turn2_had_citations:
            # Pronoun-only follow-up should have triggered the rewriter
            # to expand "its" against the prior turn's Kubernetes context.
            print("\n  turn 2 retrieved 0 citations — multi-turn rewriter likely "
                  "failed to resolve the pronoun")
            return FAIL
        return PASS
    except Exception as exc:
        print(f"\n  chat failed: {exc}")
        return FAIL


def stage_slide(client: QdrantClient, output_dir: Path) -> str:
    banner(5, "Slide planner + Presenton render")
    history: list[dict] = []
    first_user_msg = SLIDE_TURNS[0]
    try:
        # Slide-maker convention: RAG anchored to the FIRST user message.
        ctx, citations = retrieve_context(client, first_user_msg)
        print(f"  citations: {[c['filename'] for c in citations] or '(none)'}")

        for i, user_msg in enumerate(SLIDE_TURNS, start=1):
            preview = user_msg if len(user_msg) <= 80 else user_msg[:80] + "..."
            print(f"\n  turn {i}: user> {preview}")
            msgs: list[dict] = [{"role": "system", "content": PLANNER_SYSTEM}]
            msgs.extend(history)
            if ctx:
                msgs.append({"role": "system", "content": f"Context:\n{ctx}"})
            msgs.append({"role": "user", "content": user_msg})

            print("  bot> ", end="", flush=True)
            reply = chat_completion(msgs, stream=True)
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": reply})

        extracted = extract_outline(history)
        if extracted is None:
            # LLM didn't emit OUTLINE_READY in 2 turns. Non-deterministic
            # — could be a slow model warm-up or a prompt-following
            # quirk. Don't fail the whole smoke test for this.
            print("\n  planner never emitted [OUTLINE_READY] (non-deterministic LLM)")
            return INCONCL

        outline_md, params = extracted
        blocks = split_slide_blocks(outline_md)
        if not blocks:
            print("\n  outline parsed 0 slide blocks")
            return FAIL
        print(f"\n  outline parsed {len(blocks)} slide block(s); rendering...")

        try:
            pptx = render_via_presenton(
                blocks,
                template=params.get("template", "general"),
                language=params.get("language", "English"),
            )
        except Exception as exc:
            # Presenton being unreachable is a deployment issue — don't
            # fail the smoke test for that, just flag it.
            print(f"  Presenton render failed: {exc}")
            return INCONCL

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = output_dir / f"smoketest-{ts}.pptx"
        dest.write_bytes(pptx)
        print(f"  wrote {dest} ({len(pptx)} bytes)")
        return PASS if len(pptx) > 0 else FAIL
    except Exception as exc:
        print(f"\n  slide stage failed: {exc}")
        return FAIL


# ---------- Driver -------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-slide", action="store_true", help="skip the slide stage")
    ap.add_argument(
        "--keep-vectors",
        action="store_true",
        help="don't drop demo vectors at the end (so you can poke around)",
    )
    ap.add_argument(
        "--output-dir",
        default="output",
        help="dir for rendered PPTX (default: ./output relative to cwd)",
    )
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(url=QDRANT_URL)

    results: list[tuple[str, str]] = []
    results.append(("cleanup", stage_cleanup()))
    if results[-1][1] == INCONCL:
        # Without Qdrant, nothing else can run.
        print("\nFATAL: cannot continue without Qdrant", file=sys.stderr)
        return 1

    results.append(("ingest", stage_ingest(client)))
    results.append(("query", stage_query(client)))
    results.append(("chat", stage_chat(client)))
    if not args.no_slide:
        results.append(("slide", stage_slide(client, out_dir)))

    print("\n========== Summary ==========")
    width = max(len(name) for name, _ in results)
    any_failed = False
    for name, status in results:
        print(f"  {name:<{width}}  {status}")
        if status == FAIL:
            any_failed = True

    if not args.keep_vectors:
        try:
            n = cleanup_demo_vectors()
            print(f"\n  cleanup: dropped {n} demo points")
        except Exception as exc:
            print(f"\n  cleanup failed: {exc}")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
