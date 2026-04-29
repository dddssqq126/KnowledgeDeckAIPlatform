"""Demo: slide-planner REPL with Presenton render.

Standalone re-implementation of the production slide-maker path. Mirrors:
  - backend/app/features/slides/services/slide_chat_service.py
    (PLANNER SYSTEM_PROMPT, OUTLINE_READY marker, RAG-anchored-to-first-msg)
  - backend/app/features/slides/services/presenton_client.py
  - backend/app/features/slides/api/slide_sessions.py
    (_extract_outline + _split_slide_blocks + render flow)
as of commit a9ad2d5. If those files diverge, sync this file by hand.

Usage:
  python 04_slide.py                       # RAG on
  python 04_slide.py --no-rag
  python 04_slide.py --output-dir ./out

REPL commands:
  :reset    clear history (and the RAG anchor message)
  :render   force-render the latest [OUTLINE_READY] outline
  :exit     quit (Ctrl-D / Ctrl-C also work)

Auto-render: when the planner emits `[OUTLINE_READY ...]` in a turn,
the script extracts the outline + marker args, sends them to Presenton,
and writes the resulting PPTX to <output-dir>/deck-<UTC-timestamp>.pptx.
Default output dir is `./output` relative to wherever the script runs.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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
)

# Production-parity knobs.
DENSE_TOP_K = 20
PREFETCH_LIMIT = 40
RERANK_THRESHOLD = 0.10
FINAL_TOP_K = 5
HISTORY_MAX = 12  # slide_chat_service.HISTORY_MAX_MESSAGES

# Presenton's :latest image ships these four built-in templates. Anything
# else (custom user-authored templates) lives behind PUT /template/all
# and would need extra plumbing — for the demo we restrict to built-ins.
BUILTIN_TEMPLATES = {"general", "modern", "standard", "swift"}

# Same regexes as backend/app/features/slides/api/slide_sessions.py.
MARKER_RE = re.compile(r"\[OUTLINE_READY(?:\s+([^\]]+))?\]")
SLIDE_BLOCK_RE = re.compile(
    r"^##\s*Slide\s+\d+\s*:.*?(?=^##\s*Slide\s+\d+\s*:|\Z)",
    re.DOTALL | re.MULTILINE,
)

PLANNER_SYSTEM = (
    "You are KnowledgeDeck Slide Planner — a focused assistant whose only "
    "job is to help the user produce a slide deck.\n\n"
    "Workflow:\n"
    "1. If the user has not yet specified them, ask clarifying questions about: "
    "target audience, total number of slides (3-15), language for the deck, "
    "tone (professional / casual / educational / sales / etc.), VISUAL "
    "TEMPLATE preference, and any specific topics that must be covered or "
    "avoided. Ask only the questions that are still missing — do not re-ask "
    "things already in scope.\n"
    "   Visual templates available in Presenton:\n"
    "     - `general`  — clean, neutral default\n"
    "     - `modern`   — bold, contemporary styling\n"
    "     - `standard` — conservative, formal corporate layout\n"
    "     - `swift`    — minimal, energetic visual rhythm\n"
    "   Use ONLY one of these four values. If the user requests something "
    "outside this list (e.g. classic / professional / playful), pick "
    "whichever of the four fits their intent best and tell them which one "
    "you chose. If unstated, default to `general`.\n"
    "2. When you have enough information, propose a draft outline. Format "
    "STRICTLY as markdown with this exact structure:\n\n"
    "## Slide 1: <Title>\n"
    "- <bullet>\n"
    "- <bullet>\n\n"
    "## Slide 2: <Title>\n"
    "- <bullet>\n\n"
    "(...etc, one ## block per slide)\n\n"
    "3. Ask the user to review the outline and tell you what to adjust. "
    "Iterate until they are satisfied.\n"
    "4. Once the user confirms (\"yes\", \"go ahead\", \"render it\", or "
    "similar), produce the FINAL version of the outline in your reply, then "
    "end the message with a marker line that includes the chosen template "
    "and language as key=value args, on its own line. Examples:\n"
    "   `[OUTLINE_READY template=modern]`\n"
    "   `[OUTLINE_READY template=general language=Spanish]`\n"
    "   `[OUTLINE_READY]`  (= template=general language=English)\n"
    "Do not emit this marker until the user has explicitly confirmed they "
    "want to render.\n\n"
    "Rules:\n"
    "- When RAG context is provided, treat it as the PRIMARY source for "
    "facts/numbers/specifics. Beyond what's in the context, you MAY draw on "
    "your own widely-known general knowledge to make the outline more "
    "substantive — definitions, common patterns, well-established best "
    "practices, illustrative real-world examples. Do NOT fabricate specific "
    "statistics, dates, quotes, named studies, or proprietary/internal data "
    "that are not in the RAG context.\n"
    "- Aim for informative bullets, not skeletal ones. Each bullet is "
    "typically one short sentence, but a second clause is welcome when it "
    "adds concrete value (a key term, a brief example, a 'why it matters'). "
    "Avoid filler phrasing.\n"
    "- Per slide, prefer 3-5 bullets unless the user requests otherwise.\n"
    "- Do not write any prose between slide blocks in the outline itself; "
    "everything outside the ## blocks belongs above or below the outline.\n"
    "- Never emit the OUTLINE_READY marker on a turn where you are still "
    "asking questions or revising the outline."
)


# --- BM25 cache + RAG primitives (same shape as 03_chat.py) --------------

_bm25_model: SparseTextEmbedding | None = None


def _bm25() -> SparseTextEmbedding:
    global _bm25_model
    if _bm25_model is None:
        _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _bm25_model


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


# --- Streaming planner reply --------------------------------------------

def stream_planner_reply(messages: list[dict]) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    full: list[str] = []
    with httpx.Client(timeout=180.0) as client:
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


# --- Outline parser (mirrors slide_sessions._extract_outline) -----------

def extract_outline(history: list[dict]) -> tuple[str, dict[str, str]] | None:
    """Walk history backwards looking for an assistant turn with the
    OUTLINE_READY marker. Returns (outline_markdown_without_marker, params)
    where params may carry `template` and `language`."""
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


def split_slide_blocks(outline_md: str) -> list[str]:
    blocks = [m.group(0).strip() for m in SLIDE_BLOCK_RE.finditer(outline_md)]
    return [b for b in blocks if b]


# --- Presenton render ---------------------------------------------------
# We submit the outline to Presenton's sync /generate endpoint and read
# the rendered PPTX off the shared volume mounted at PRESENTON_DATA_ROOT.
# Production sends `content` (joined blocks) instead of `slides_markdown`
# because the slides_markdown code path crashes inside Presenton :latest.

def render_via_presenton(
    slide_blocks: list[str], *, template: str, language: str
) -> bytes:
    if template not in BUILTIN_TEMPLATES:
        print(f"[render]    template {template!r} not built-in; falling back to general")
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
    print(f"[presenton] POST {url} (template={template}, language={language}, n={len(slide_blocks)})")
    with httpx.Client(timeout=300.0) as client:
        r = client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Presenton {r.status_code}: {r.text[:300]}")
        path = r.json().get("path")
        if not path:
            raise RuntimeError(f"Presenton response missing 'path': {r.text[:300]}")
    print(f"[presenton] artifact path={path}")

    if not path.startswith("/app_data/"):
        raise RuntimeError(f"unexpected path (not under /app_data): {path}")
    on_host = Path(PRESENTON_DATA_ROOT) / path[len("/app_data/"):]
    if not on_host.exists():
        raise RuntimeError(f"artifact not found on shared volume: {on_host}")
    return on_host.read_bytes()


def _do_render(history: list[dict], out_dir: Path) -> None:
    extracted = extract_outline(history)
    if extracted is None:
        print("[render]    no [OUTLINE_READY] outline in history yet")
        return
    outline_md, params = extracted
    blocks = split_slide_blocks(outline_md)
    if not blocks:
        print("[render]    outline has no '## Slide N: ...' blocks")
        return
    template = params.get("template", "general").strip()
    language = params.get("language", "English").strip()
    try:
        pptx = render_via_presenton(blocks, template=template, language=language)
    except Exception as exc:
        print(f"[render]    failed: {exc}")
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir / f"deck-{ts}.pptx"
    dest.write_bytes(pptx)
    print(f"[render]    wrote {dest} ({len(pptx)} bytes)")


# --- REPL ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-rag", action="store_true", help="disable retrieval")
    ap.add_argument(
        "--output-dir",
        default="output",
        help="dir for rendered PPTX files (default: ./output relative to cwd)",
    )
    args = ap.parse_args()

    use_rag = not args.no_rag
    history: list[dict] = []
    # Slide-maker anchors RAG retrieval to the FIRST user message — later
    # turns ("yes render it", "more on X") would otherwise drag retrieval
    # off-topic.
    first_user_msg: str | None = None
    qclient = QdrantClient(url=QDRANT_URL) if use_rag else None
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[slide] model={LLM_MODEL}  rag={'on' if use_rag else 'off'}  output={out_dir}")
    print("        commands: :reset | :render | :exit\n")

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
            first_user_msg = None
            print("[history cleared]")
            continue
        if user == ":render":
            _do_render(history, out_dir)
            continue

        if first_user_msg is None:
            first_user_msg = user

        # 1. RAG retrieval anchored to the first user message of the session.
        context = ""
        citations: list[dict] = []
        if use_rag:
            assert qclient is not None
            context, citations = retrieve_context(qclient, first_user_msg)
            if citations:
                print(f"[citations] {', '.join(c['filename'] for c in citations)}")

        # 2. Build planner messages.
        msgs: list[dict] = [{"role": "system", "content": PLANNER_SYSTEM}]
        for m in history[-HISTORY_MAX:]:
            msgs.append({"role": m["role"], "content": m["content"]})
        if context:
            msgs.append({"role": "system", "content": f"Context:\n{context}"})
        msgs.append({"role": "user", "content": user})

        # 3. Stream the reply, then commit both turns to history.
        print("bot> ", end="", flush=True)
        reply = stream_planner_reply(msgs)
        history.append({"role": "user", "content": user})
        history.append({"role": "assistant", "content": reply})

        # 4. Auto-render when the planner emits OUTLINE_READY this turn.
        if MARKER_RE.search(reply):
            print("\n[auto-render] OUTLINE_READY detected")
            _do_render(history, out_dir)


if __name__ == "__main__":
    sys.exit(main())
