# Architecture

A deep-dive into how KnowledgeDeck is built — read this when you want to understand *why* the code is shaped the way it is, or when you want to extract one feature for use in another project. For a quickstart that just gets you running, see [README.md](../README.md). For endpoint-level reference, see [API.md](API.md).

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Repository Layout](#repository-layout)
3. [Feature Boundaries](#feature-boundaries)
4. [Knowledge Base — Ingest Pipeline](#knowledge-base--ingest-pipeline)
5. [RAG — Retrieval Pipeline](#rag--retrieval-pipeline)
6. [Chat](#chat)
7. [Slide Maker](#slide-maker)
8. [Auth + Shared Platform](#auth--shared-platform)
9. [Frontend Architecture](#frontend-architecture)
10. [Configuration](#configuration)
11. [Deployment](#deployment)
12. [Test Strategy](#test-strategy)
13. [Design Decisions Worth Knowing](#design-decisions-worth-knowing)

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Browser (Next.js 15 SPA)                      │
│  ┌────────┐ ┌────────────┐ ┌─────┐ ┌──────────────┐              │
│  │ Login  │ │ KnowledgeBs│ │ Chat│ │ Slide Maker  │              │
│  └────────┘ └────────────┘ └─────┘ └──────────────┘              │
└─────────────────────────┬────────────────────────────────────────┘
                          │ HTTPS / SSE (Bearer u_<id>)
┌─────────────────────────▼────────────────────────────────────────┐
│                    FastAPI (port 8080)                           │
│  shared/api: auth, health, llm_info                              │
│  features/{rag,knowledge_bases,chat,slides}/api/                 │
└──┬──────────────────┬─────────────┬───────────┬──────────────────┘
   │                  │             │           │
   │     ┌────────────┼─────────────┼───────────┘
   │     │            │             │
   ▼     ▼            ▼             ▼
┌──────────┐  ┌───────────┐  ┌───────────┐  ┌─────────────────┐
│ Postgres │  │   MinIO   │  │  Qdrant   │  │   Presenton     │
│ (ORM)    │  │ (objects) │  │ (vectors) │  │  (PPTX render)  │
└──────────┘  └───────────┘  └───────────┘  └─────────────────┘
                                                  │
                                                  │ vLLM /chat /embed /score
                                                  ▼
                                        ┌────────────────────────┐
                                        │ vLLM × 3 on one GPU:   │
                                        │   chat   (Gemma 4 E4B) │
                                        │   embed  (bge-m3)      │
                                        │   rerank (bge-reranker)│
                                        └────────────────────────┘
```

Six runtime services, all in `docker-compose.yml`:

| Container | Image | Port (host:container) | Purpose |
|---|---|---|---|
| `knowledgedeck_backend` | (built) | 8080:8080 | FastAPI app |
| `knowledgedeck_frontend` | (built) | 3000:3000 | Next.js dev server |
| `knowledgedeck_postgres` | postgres:16 | 5432 (internal) | Metadata: users, KBs, files, chat/slide sessions |
| `knowledgedeck_backend` local volume | named volume | mounted at `/var/lib/knowledgedeck-storage` | Object store: original uploads + rendered PPTX |
| `knowledgedeck_qdrant` | qdrant:1.12 | 6333 (internal) | Vector store: dense + sparse named vectors |
| `knowledgedeck_presenton` | ghcr.io/presenton/presenton | 5001 (internal) | PPTX rendering service |
| `knowledgedeck_vllm_chat` | vllm:0.19.1 | 8000:8000 | Chat LLM (default Gemma 4 E4B) |
| `knowledgedeck_vllm_embedding` | vllm:0.19.1 | 8001:8000 | Embedding model (bge-m3) |
| `knowledgedeck_vllm_rerank` | vllm:0.19.1 | 8002:8000 | Cross-encoder reranker (bge-reranker-v2-m3) |

The three vLLM containers default to sharing GPU 0 with utilization budgets (chat 0.70 / embed 0.08 / rerank 0.08, total ~0.86 of 24 GB). Override `VLLM_*_GPU_DEVICE` in `.env` to spread across multiple GPUs.

---

## Repository Layout

```
backend/
├── app/
│   ├── core/                      # Pydantic Settings + global config
│   │   └── config.py
│   ├── db/                        # SQLAlchemy 2.0 async + Alembic
│   │   ├── base.py
│   │   ├── models.py
│   │   └── migrations/versions/
│   ├── shared/                    # Cross-feature platform code
│   │   ├── api/
│   │   │   ├── auth.py            # POST /auth/login, GET /auth/me
│   │   │   ├── deps.py            # FastAPI dependencies (get_current_user)
│   │   │   ├── health.py          # GET /health, /ready
│   │   │   └── llm_info.py        # GET /llm/info
│   │   └── services/
│   │       └── auth_service.py    # password verification (plaintext for MVP)
│   ├── features/
│   │   ├── rag/                   # ⬛ shared by KB+Chat+Slide
│   │   │   ├── api/admin.py       # POST /admin/rag-reindex
│   │   │   └── services/
│   │   │       ├── rag.py             # retrieve_context() — single entry point
│   │   │       ├── ingestion.py       # parse → chunk → embed → upsert
│   │   │       ├── document_parser.py # txt/cs/md/pdf/docx/pptx parsers
│   │   │       ├── text_splitter.py   # LangChain RecursiveCharacterTextSplitter
│   │   │       ├── qdrant_store.py    # named-vector schema + hybrid_search
│   │   │       ├── sparse_embed.py    # BM25-style hashing sparse wrapper
│   │   │       └── model_clients.py   # EmbeddingClient + RerankClient
│   │   ├── knowledge_bases/       # 🗂️ KB management
│   │   │   ├── api/
│   │   │   │   ├── knowledge_bases.py # CRUD on KBs
│   │   │   │   └── files.py           # upload/list/delete files
│   │   │   └── services/
│   │   │       ├── knowledge_base_service.py
│   │   │       ├── file_service.py    # extension + magic-byte validation
│   │   │       └── object_storage.py  # MinIO async wrapper
│   │   ├── chat/                  # 💬 Chat
│   │   │   ├── api/chat.py        # sessions + SSE stream
│   │   │   └── services/chat_service.py # rewriter + stream_answer
│   │   └── slides/                # 🎯 Slide Maker
│   │       ├── api/slide_sessions.py     # sessions + stream + render + download
│   │       └── services/
│   │           ├── slide_chat_service.py # planner system prompt + stream_planner
│   │           └── presenton_client.py   # /v1/ppt/* HTTP wrapper
│   ├── main.py                    # FastAPI app factory + router registration
│   ├── startup.py                 # lifespan: ensure MinIO bucket, run migrations
│   └── cli.py                     # typer: create-user, list-users
├── tests/                         # pytest + testcontainers
│   ├── conftest.py
│   ├── test_auth_*.py
│   ├── test_files_*.py
│   ├── test_knowledge_bases.py
│   └── ...
└── requirements.txt

frontend/
├── app/
│   ├── login/page.tsx
│   ├── (protected)/
│   │   ├── layout.tsx                  # auth gate + AppSidebar
│   │   ├── page.tsx                    # ← Chat (root of authed area)
│   │   ├── knowledge-bases/
│   │   │   ├── page.tsx                # KB list
│   │   │   └── [id]/page.tsx           # KB detail (files, upload, sort)
│   │   ├── slides/
│   │   │   ├── page.tsx                # Slide deck list
│   │   │   └── [id]/page.tsx           # Slide planner conversation
│   │   └── dashboard/page.tsx
│   └── layout.tsx
├── components/
│   ├── AppSidebar.tsx                  # context-aware sidebar
│   ├── SidebarItemList.tsx
│   ├── AuthGuard.tsx
│   ├── ChatInput.tsx                   # used by both Chat and Slide Maker
│   └── DropUpload.tsx                  # KB file upload widget
└── lib/
    ├── api.ts                          # axios instance + bearer + 401 redirect
    ├── auth-store.ts                   # Zustand auth store
    ├── chat-store.ts / chat.ts         # Chat-specific
    ├── kb-store.ts / knowledge-bases.ts # KB-specific
    ├── slide-store.ts / slides.ts      # Slide-specific
    └── llm-info.ts                     # model label fetch
```

---

## Feature Boundaries

> "I only want feature X. What do I need to take?"

| If you want… | Take backend | Take frontend |
|---|---|---|
| **Just KB + RAG ingest** (file upload to vector store, no chat UI) | `app/shared/`, `app/features/rag/`, `app/features/knowledge_bases/`, `app/db/` (full models — strip Chat/Slide tables if you want) | `app/(protected)/knowledge-bases/`, `lib/{kb-store,knowledge-bases,api,auth-store}.ts`, `components/{DropUpload,AuthGuard,AppSidebar,SidebarItemList}.tsx` |
| **KB + RAG + Chat** (no Slide Maker) | drop `app/features/slides/`; remove its router from `app/main.py`; drop slide migrations 0004-0007 | drop `app/(protected)/slides/` and `lib/slide-store.ts` + `lib/slides.ts` |
| **Just Slide Maker** (without KB UI but still using RAG against pre-existing data) | needs everything except `app/features/knowledge_bases/api/files.py` UI is optional but you'll still want the upload route to seed KB | drop the `knowledge-bases/` route directory; keep `lib/knowledge-bases.ts` because slide RAG still uses KB selection |
| **Just RAG as a library** (no UI) | only `app/features/rag/`, `app/core/`, `app/db/` (KnowledgeBase + KnowledgeFile models) | none |

The cleanest extraction is `app/features/rag/` — it has no upward dependencies on KB/Chat/Slide. Both KB ingestion and chat retrieval use it as a black-box `retrieve_context(user_id, kb_ids, query) → (context, citations)` and `ingest_file(session, file_row, data)`.

---

## Knowledge Base — Ingest Pipeline

### What gets stored where

```
User uploads file.docx via POST /knowledge-bases/{kb_id}/files
                          │
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  files.py (router)                                   │
   │   1. validate_extension(filename) → {txt,pdf,cs,md,  │
   │      docx,pptx}                                      │
   │   2. stream_into_buffer (sha256 + 50 MB cap)         │
   │   3. validate_content (head bytes — magic / utf-8)   │
   │   4. INSERT files row (status=UPLOADED)              │
   │   5. Generate storage_key kb/{kb_id}/files/{file_id}/│
   │      original.{ext} (now that file_id exists)        │
   │   6. PUT to MinIO                                    │
   │   7. ingest_file(session, row, data)  ← inline       │
   └──────────────────────────────────────────────────────┘

   ingest_file (rag/services/ingestion.py)
   ┌──────────────────────────────────────────────────────┐
   │ document_parser.parse(ext, bytes)                    │
   │   txt/cs/md → 1 segment, page_number=None            │
   │   pdf       → 1 segment per page, page_number=N      │
   │   docx      → paragraphs+tables flattened, page=None │
   │   pptx      → 1 segment per slide, page_number=slide#│
   │                  ▼                                   │
   │ text_splitter.split_text                             │
   │   RecursiveCharacterTextSplitter                     │
   │   separators: \n\n → \n → ". " → "?,!,;,," → " " → ""│
   │   chunk_chars=1200, overlap=150                      │
   │                  ▼                                   │
   │ Two parallel embeds:                                 │
   │   bge-m3 dense (1024-d cosine)                       │
   │   BM25-style sparse + Qdrant IDF (in-process)        │
   │                  ▼                                   │
   │ qdrant_store.upsert_chunks                           │
   │   point.vector = {dense: [...], sparse: SparseVector}│
   │   payload = {user_id, kb_id, file_id, filename,      │
   │              text, page_number, chunk_index}         │
   │                  ▼                                   │
   │ UPDATE files SET status='indexed' (or 'failed')      │
   └──────────────────────────────────────────────────────┘
```

**File status state machine**: `UPLOADED → INDEXED` on success, `UPLOADED → FAILED` on any pipeline exception. The user sees the final status synchronously in the upload response — there is no background worker.

**Trade-off**: synchronous ingest blocks the upload request for ~1-3 seconds depending on file size. We accepted that for MVP simplicity. To make it async, replace the inline `ingest_file()` call with an enqueue (Redis/RQ) and add a status poll endpoint.

### Format handling specifics

| Ext | Parser | Magic check | Page numbers | Notes |
|---|---|---|---|---|
| `txt` | `data.decode("utf-8")` | UTF-8 + null-byte | none | |
| `md` | same as txt | UTF-8 + null-byte | none | Markdown source |
| `cs` | same as txt | UTF-8 + null-byte | none | C# source code |
| `py` | same as txt | UTF-8 + null-byte | none | Python source code |
| `html` | same as txt | UTF-8 + null-byte | none | Tags kept as-is — embedding handles them |
| `css` | same as txt | UTF-8 + null-byte | none | |
| `pdf` | `pypdf.PdfReader` | `%PDF` | per page | |
| `docx` | `python-docx` paragraphs + tables | `PK\x03\x04` (ZIP) | none | Tables joined with `\| ` |
| `pptx` | `python-pptx` per-slide shapes | `PK\x03\x04` (ZIP) | per slide | Speaker notes excluded |

The ZIP magic check is loose by design — any zip file passes the validator, then the parser does the strict OOXML check inside.

### Cleanup paths

- `DELETE /knowledge-bases/{kb_id}/files/{file_id}` → soft-delete file row + `qdrant_store.delete_by_file()` removes vectors. MinIO object stays (cheap to keep, costly to recover if needed).
- `DELETE /knowledge-bases/{kb_id}` → cascading soft-delete: KB row + every file row + every file's vectors.
- `POST /admin/rag-reindex` → drops the entire Qdrant collection and re-runs ingestion for every non-deleted file. Use after schema changes (e.g., when we added the sparse vector dimension).

---

## RAG — Retrieval Pipeline

[`features/rag/services/rag.py`](../backend/app/features/rag/services/rag.py) exposes one entry point used by both chat and slide:

```python
async def retrieve_context(*, user_id: int, kb_ids: list[int] | None, query: str
) -> tuple[str, list[dict[str, Any]]]:
    # returns (context_block, citations)
```

### Pipeline (each turn that opts in)

```
Step 1. Embed query in parallel
        ┌────────────────────────────┐
        │ bge-m3 dense (1024-d)      │ via vLLM /embeddings
        │ BM25-style sparse + IDF    │ in-process
        └────────────────────────────┘

Step 2. Qdrant Query API hybrid search
        prefetch:
          [Prefetch(query=dense_vec,  using="dense",  limit=40),
           Prefetch(query=sparse_vec, using="sparse", limit=40)]
        filter: must user_id == current_user
                must kb_id  IN selected
        fusion: RRF
        limit:  rag_dense_top_k (default 20)

Step 3. Cross-encoder rerank
        POST {rerank_base_url}/score
          { model: bge-reranker-v2-m3,
            text_1: query,
            text_2: [chunk1.text, chunk2.text, ...] }
        → returns float ∈ [0, 1] per (query, chunk)
        We sort by rerank score desc.

Step 4. Threshold filter + take top-K
        if rerank_score < rag_rerank_min_score: drop
        keep first rag_final_top_k (default 5)

Step 5. Format into "Context:" block + citations
        [1] react_hooks.txt (p.3)
        Hooks let you opt into React's state...

        [2] kubernetes_basics.txt
        A Pod is a unit of deployment...
```

### Why hybrid + rerank instead of just dense?

- **Dense alone** misses keyword-sensitive queries. "Kubernetes pod" vs "component lifecycle" can score similarly to dense embedding. The fix is sparse (lexical match catches "Kubernetes").
- **Pre-rerank** dense+sparse ranking is noisy — bge-m3 scores can swing ~0.05 between near-duplicate queries, so the top-5 order isn't stable. Cross-encoder reads the (query, passage) pair and returns a relevance score that's robust to rephrasings.
- **Threshold** lets us return `("", [])` when nothing is relevant. Otherwise the LLM gets unrelated context and tries to ground answers in it — strictly worse than letting the LLM use general knowledge.

### Query rewriting (chat-only, every RAG-enabled turn)

`chat_service.rewrite_for_retrieval(history, user_message)` runs on every chat request that has `use_rag=true`. It does three jobs:

**1. Multi-turn reference resolution**

```
turn 1: "Tell me about Kubernetes pods"
turn 2: "And what about deployments?"   ← needs turn 1 to make sense

→ "What about Kubernetes deployments? How do they relate to pods?"
```

**2. Abbreviation expansion** — without this, cross-encoder rerank scores `"k8s"` against Kubernetes documents at ~0.0005 (well below the 0.10 threshold), producing zero citations even when hybrid search clearly surfaces the right file:

```
"k8s"              →  "What is Kubernetes?"
"aws"              →  "What is Amazon Web Services?"
"ml"               →  "What is machine learning?"
"gpu"              →  "What is a graphics processing unit?"
```

We deliberately *do not* keep the abbreviation in parentheses. Tested empirically:
- `"What is Kubernetes?"`        → rerank 0.66
- `"What is Kubernetes (k8s)?"`  → rerank 0.04 ← parenthetical noise tanks the score

**3. Bare-term reformulation** — single-word / single-acronym queries get reshaped into natural questions:

```
"Kubernetes"   →  "What is Kubernetes?"
"embeddings"   →  "What are embeddings?"
```

If the user already typed a complete natural-language question, the rewriter passes it through unchanged.

**Cost**: one extra LLM call per RAG-enabled chat turn (~200-400ms with `temperature=0`, `max_tokens=128`). Falls back to the raw user message on any rewriter failure or off-rails output.

**Slide Maker does NOT use the rewriter.** Slide planner conversations have a stable topic anchor — the deck's first user message (`"3 slides about Kubernetes basics"`). Subsequent turns are clarifying questions / iteration tweaks ("yes render", "more about networking") that should re-retrieve against the original topic, not the literal turn message.

### Multi-turn behavior

A common question: *"In a multi-turn chat, does RAG run every turn, or just the first?"*

**Answer**: every turn that has `use_rag=true` re-runs the full pipeline. There is no cross-turn caching, no "last citations stay sticky", and no "RAG only on the first turn" optimization. Each request is a fresh retrieve against the current rewritten query.

**What the rewriter does in multi-turn** (the cases that fail without it):

| User types (turn N) | History | Rewriter output | Why it matters |
|---|---|---|---|
| `"k8s"` | empty | `"What is Kubernetes?"` | Cold-start abbreviation expansion |
| `"and what about deployments?"` | turn 1 about Kubernetes | `"What are deployments in Kubernetes?"` | Without "Kubernetes" in the query, retrieval drifts |
| `"compare them"` | 4 prior msgs about Pods + Deployments | `"Compare Pods and Deployments in Kubernetes"` | Resolves both pronouns from history |

**What the LLM actually sees** (this is the non-obvious part):

```
[SystemMessage]   chat SYSTEM_PROMPT
[HumanMessage]    turn 1 user (raw, NOT rewritten)
[AIMessage]       turn 1 assistant
[HumanMessage]    turn 2 user (raw)
[AIMessage]       turn 2 assistant
... up to HISTORY_MAX_MESSAGES = 20 ...
[SystemMessage]   "Context:\n[1] file.txt\n<chunk text>\n..."  ← ONLY current turn's hits
[HumanMessage]    current turn user message (raw, NOT rewritten)
```

Three properties to internalize:

1. **The rewriter only steers retrieval**, never the LLM. The HumanMessage at the bottom is always the literal user message. So if the rewriter mangles a statement (e.g., "My favourite color is teal" → "What is my favourite color?"), it just produces empty citations — the LLM still sees the original statement and replies correctly.

2. **Past citations don't accumulate.** The `Context:` block contains only the chunks that retrieval returned for *this* turn. If turn 1 cited `pods.txt` and turn 2 cited `deployments.txt`, turn 3 sees neither in its `Context:` block — turn 3 retrieval runs from scratch. The LLM still has secondary memory through the *assistant text* of past turns sitting in history, but the original chunk text from earlier turns is gone.

3. **History sliding window**: `HISTORY_MAX_MESSAGES = 20` (chat) caps how many user/assistant turns get re-injected into each prompt. The 11th turn forward starts dropping the oldest turn pair. The rewriter looks at an even narrower window (last 6 messages) — full history is overkill for reference resolution.

**Verified by repro** (on this codebase):

```
Turn 1: 'k8s'                            → 4 citations (kubernetes_basics × 3, test.md)
Turn 2: 'and what about deployments?'    → 3 citations (kubernetes_basics × 3)
Turn 3: 'compare them'                   → 3 citations (kubernetes_basics × 3)
Turn 4: 'My favourite color is teal'     → 0 citations (KB has no color content)
        — LLM still answers correctly via original-message visibility
```

**Slide Maker is different**. Multi-turn slide-planner conversations *don't* re-rewrite per turn. Retrieval is anchored to the session's first user message (the deck topic). Iteration turns ("yes render it", "more about networking") would not benefit from being treated as fresh search queries.

---

## Chat

```
POST /chat/sessions                ← create empty session, default title
POST /chat/stream                  ← SSE: {token | citations | done}
GET  /chat/sessions                ← list (newest updated first)
GET  /chat/sessions/{id}           ← detail with messages
PATCH /chat/sessions/{id}          ← rename
DELETE /chat/sessions/{id}         ← soft-delete
```

### Streaming

```
Frontend opens SSE via `fetch(POST)` (not EventSource — we need to attach
the Bearer header).

Backend `stream_chat()`:
  1. Load session + history (ChatMessage rows ordered by id).
  2. Persist the new user message in the *same* request transaction.
     Commit. Now history snapshot in memory still excludes this turn,
     so passing it to the LLM doesn't double up.
  3. Optional: rewrite_for_retrieval(history, message) → rag_query
                rag.retrieve_context(...) → (context, citations)
  4. chat_service.stream_answer(history=snapshot, user_message=raw,
                                  context=ctx) yields tokens.
     Tokens are SSE "token" events.
  5. After token stream ends, persist the assistant message in a *new*
     async session (the request session has already returned to the
     pool). Send a "citations" event then "done".
  6. On any exception inside the generator, send a single "error"
     event and close.

Two SSE event types per turn (in order):
  event: token         { text: "..." }     (many)
  event: citations     { items: [...] }    (once)
  event: done          { }                 (once)
  event: error         { message: "..." }  (only on failure)
```

### Multi-turn history

`HISTORY_MAX_MESSAGES = 20` user/assistant turns are concatenated into the LLM prompt. Older turns fall off (we don't summarize). The system prompt explicitly grants permission to recall earlier turns — without it, Gemma 4 E4B refuses on personal-fact requests ("I do not have the capability to remember preferences").

The prompt structure sent to vLLM:

```
SystemMessage   ← chat SYSTEM_PROMPT (recall is OK, RAG context is preferred when present)
HumanMessage    ← turn 1 user
AIMessage       ← turn 1 assistant
HumanMessage    ← turn 2 user
... up to HISTORY_MAX_MESSAGES ...
SystemMessage   ← "Context: [chunks]" only if RAG ran AND had hits
HumanMessage    ← current turn
```

---

## Slide Maker

```
POST /slide-sessions/{id}/stream       ← planner SSE (same shape as chat)
POST /slide-sessions/{id}/render       ← build PPTX, persist marker message
GET  /slide-sessions/{id}/download     ← stream the .pptx blob
```

### Conversation flow

```
turn 1  user: "5 slides about Postgres indexing for backend devs"
        assistant: "What audience? What template? ..."

turn 2  user: "junior devs, modern style, English"
        assistant: [draft outline as markdown]
                  "## Slide 1: ..." etc.
                  "Let me know if you'd like changes."

turn 3  user: "make slide 3 punchier"
        assistant: [revised outline]

turn 4  user: "ok render it"
        assistant: [final outline]
                  + "[OUTLINE_READY template=modern language=English]"
                  ↑ marker triggers /render automatically (frontend
                    sees `outline_ready: true` on the SSE done event)
```

### `[OUTLINE_READY ...]` marker

The marker is the planner's commitment signal: "this is the version to render". Args after the marker are key=value pairs (`template=modern`, `language=Spanish`). Backend's [`_extract_outline()`](../backend/app/features/slides/api/slide_sessions.py) finds the latest assistant turn carrying it, strips the marker, and parses args.

The visible message in the chat (frontend strips the marker via `stripOutlineReady()` before display) reads naturally. The marker is the only piece of structured state we extract from a free-form LLM turn.

### Render

```
POST /slide-sessions/{id}/render
  1. Find latest [OUTLINE_READY] message → outline markdown + args
  2. Split outline into per-slide blocks ## Slide N: ...
  3. Determine template:
       a. session.custom_template_id (if set; currently unused — see
          note-todo.md for the deferred PPTX-upload-as-template flow)
       b. marker arg `template=...` (must be in {general, modern,
          standard, swift} — the four Presenton actually accepts)
       c. body.template (request override)
       d. fallback "general"
  4. Set status=RENDERING, commit
  5. PresentonClient.generate(slides_markdown=blocks, template=tpl, ...)
     This is a sync HTTP call to Presenton's /api/v1/ppt/presentation/
     generate. We pass the outline as `content` (single blob) because
     the per-slide `slides_markdown` array crashes inside Presenton's
     internal helper at this version.
  6. Read the resulting .pptx from the shared volume mount
     /presenton_data/<presentation_id>.pptx
  7. PUT to local object storage at slide-sessions/{id}/latest.pptx (overwrites)
  8. Persist a [RENDERED:N seconds] marker message in the chat
     OR a [RENDER_FAILED:N seconds] message on Presenton failure
  9. Return both updated session + the new message; frontend appends
     it to the chat scroll
```

The `[RENDERED]` / `[RENDER_FAILED]` markers are parsed by `parseRenderMarker()` on the frontend and rendered as a special bubble (Download button or error banner) inside the chat history. So the user can iterate ("can we change slide 2 more?") and the previous render bubble stays visible above.

### Presenton integration

Presenton is a separate container. We use it ONLY for rendering — its outline LLM is bypassed because we already have the user-confirmed outline. Two communication channels:

| Channel | Used for |
|---|---|
| HTTP `/api/v1/ppt/presentation/generate` | Sync render call. Returns `{path: "/app_data/exports/...pptx"}`. |
| Shared docker volume `presenton_data` | We mount the same volume on the backend (`presenton_data_root=/presenton_data`) read-only and read the .pptx without proxying through HTTP. |

Visual templates: 4 ship with Presenton (`general` / `modern` / `standard` / `swift`). The 8 other directories in Presenton's image (`neo-*`, `Code`, `Education`, `ProductOverview`, `Report`) exist on disk but the `/generate` endpoint rejects them as of `presenton:latest` Apr 2026.

---

## Auth + Shared Platform

### Auth (MVP-grade)

[`shared/services/auth_service.py`](../backend/app/shared/services/auth_service.py): plaintext password compare against the `users` table. Tokens are `u_<id>` strings — opaque but trivially decodable. **This is acceptable only because the platform is internal-network**. Production should swap to bcrypt + JWT.

`POST /auth/login` returns `{token, user}`. The frontend stores the token in Zustand (in-memory only — localStorage is intentionally avoided to limit XSS risk; refresh = re-login). All authed endpoints depend on `get_current_user` which parses `u_<id>`, looks up the user, attaches it to the request.

### Health

`GET /health` returns 200 immediately (liveness). `GET /ready` checks Postgres + local object storage (readiness). Used by docker compose healthchecks.

### LLM info

`GET /llm/info` → `{label, model_id}`. Frontend renders `Model: <label>` in chat / slide headers. Decoupled from the actual `LLM_MODEL` ID so deployers can show "Gemma 4 E4B" while sending `google/gemma-4-E4B-it` to vLLM.

---

## Frontend Architecture

### Routes (Next.js 15 App Router)

```
/login                           public login page
/                                Chat (root of authed area, defaults to most recent session)
/?sid=N                          Chat with session N pre-selected
/dashboard                       Stats + module cards
/knowledge-bases                 KB list (master-detail in sidebar)
/knowledge-bases/[id]            KB detail (files, upload, sort)
/slides                          Slide deck list
/slides/[id]                     Slide planner conversation
```

`(protected)/layout.tsx` wraps all authed routes with `<AuthGuard>` (redirects to /login if no token) and the shared `<AppSidebar>`.

### State management

Zustand stores per feature, all in `frontend/lib/`:

- `auth-store` — token + user; persists nothing (refresh → re-login)
- `chat-store` — chat sessions cache, refresh, rename, soft-delete
- `kb-store` — KBs cache
- `slide-store` — slide sessions cache
- `llm-info` — single fetch of model label, cached for the session

`api.ts` is the axios instance with the bearer interceptor and a 401 → redirect-to-login response interceptor. All `lib/<feature>.ts` API helpers go through it.

### Sidebar context

`AppSidebar` watches the active route and shows a different list below the fixed top nav:

| Top nav | Bottom list |
|---|---|
| Dashboard | (empty) |
| Knowledge Bases | KB list |
| Chat | session history |
| Slide Maker | slide-deck list |

Each list supports new / rename / delete inline.

### Streaming on the frontend

`fetch(POST /chat/stream)` returns a `ReadableStream`; we read chunks and split on `\n\n` (SSE frame delimiter), then parse `event: ...\ndata: ...\n` to dispatch to the right handler. Same shape for slide-maker stream. EventSource isn't used because it can't attach the Bearer header.

---

## Configuration

All config lives in `.env`. Settings are loaded once at startup via Pydantic; runtime mutation is not supported. To change a value, edit `.env` and restart the affected container.

**Grouping** (see [README.md](../README.md#configuration) for tables):

| Group | Vars |
|---|---|
| Auth bootstrap | `INITIAL_USER_USERNAME`, `INITIAL_USER_PASSWORD` |
| CORS | `CORS_ORIGINS` (comma-separated) |
| LLM | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_MODEL_LABEL`, `LLM_API_KEY` + `VLLM_CHAT_*` |
| Embedding | `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL` + `VLLM_EMBEDDING_*` |
| Reranker | `RERANK_BASE_URL`, `RERANK_MODEL` + `VLLM_RERANK_*` |
| RAG knobs | `RAG_DENSE_TOP_K`, `RAG_FINAL_TOP_K`, `RAG_MIN_SCORE`, `RAG_RERANK_MIN_SCORE` |
| Chunking | `CHUNK_CHARS`, `CHUNK_OVERLAP` |
| Storage | `LOCAL_STORAGE_ROOT`, `STORAGE_BUCKET`, `MAX_UPLOAD_BYTES` |
| Vectors | `QDRANT_PATH` (or `QDRANT_URL`), `QDRANT_COLLECTION`, `EMBEDDING_DIM` |
| Slide rendering | `PRESENTON_URL`, `PRESENTON_USERNAME`, `PRESENTON_PASSWORD`, `PRESENTON_DATA_ROOT` |
| Database | `DATABASE_URL` |
| GPU placement | `GPU_DEVICE`, `VLLM_RERANK_GPU_DEVICE` |

---

## Deployment

```
docker compose --profile gpu up -d        # starts everything
docker compose --profile gpu up --build   # rebuild after code changes
```

The `gpu` profile gates the three vLLM services so devs without GPU can still iterate on Postgres / MinIO / backend / frontend (chat / RAG / render won't work, but the rest of the API does).

**First-run model downloads** (cached in the `hf_cache` volume):

| Model | Size |
|---|---|
| `google/gemma-4-E4B-it` | ~8 GB |
| `BAAI/bge-m3` | ~2 GB |
| `BAAI/bge-reranker-v2-m3` | ~570 MB |

**Image rebuilds**: backend and frontend Dockerfiles are simple `pip install` / `npm install` + `COPY .` images. There's no volume mount for code, so editing source on the host requires `docker compose up -d --build <service>` to take effect. (Adding a dev volume mount + `next dev` HMR is on the roadmap.)

**Multi-GPU split**: change `VLLM_*_GPU_DEVICE` per service. Defaults co-locate everything on GPU 0.

---

## Test Strategy

`backend/tests/` runs against real services using `testcontainers`:
- Postgres for DB tests (real migrations, real ORM)
- MinIO for object-store tests
- Mocked HTTP for vLLM / Qdrant / Presenton (via `httpx_mock` or in-process FakeQdrant)

Tests are NOT shipped in the production backend image (Dockerfile only copies `app/`). Run them by:

```bash
# From the host, requires the compose stack to be running
docker run --rm \
  --network knowledgedeck_default \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/backend:/work \
  -w /work \
  --env-file .env \
  knowledgedeck-backend \
  sh -c "pip install -r requirements-dev.txt && python -m pytest -v"
```

(The `docker.sock` mount is for testcontainers to spin up its own Postgres / MinIO containers; the existing compose Postgres is not used by tests.)

**Frontend tests** are vitest + tsc:

```bash
cd frontend
npm test
npm run typecheck
```

---

## Design Decisions Worth Knowing

These are choices that aren't obvious from the code, listed for the next person to touch them.

1. **Single Qdrant collection, payload-filter isolation.** Per-user/KB isolation is enforced at query time via Qdrant payload filters, not separate collections. Pros: easy multi-KB search, easy to scale. Cons: hot collection at large scale (millions of points). For MVP-scale this is fine.

2. **Synchronous ingestion.** `POST /knowledge-bases/{id}/files` blocks until the file is parsed, embedded, and indexed. We accepted the 1-3s upload latency to skip Redis/RQ. Async ingestion is on the roadmap.

3. **Plaintext passwords.** Per-MVP scope; only acceptable on internal networks. Replace `auth_service.authenticate()` + add a hashing migration when you take this beyond the lab.

4. **Single Qdrant collection for hybrid.** Dense (1024-d cosine) + sparse (BM25) live as named vectors on the same point. Reindex via `POST /admin/rag-reindex` when the schema changes (e.g., when sparse was added).

5. **vLLM `--runner pooling --convert classify` for the reranker.** vLLM 0.19 dropped `--task` in favor of `--runner` + `--convert`. This combination tells vLLM to run BAAI/bge-reranker-v2-m3 as a cross-encoder and expose `/v1/score`.

6. **All vLLM containers on a single GPU by default.** Three services share GPU 0 with chat at 0.70 utilization, embedding+rerank at 0.08 each. Override `VLLM_*_GPU_DEVICE` to split. The `device_ids` reservation in `docker-compose.yml` (rather than `count: 1`) is what makes the per-service GPU pinning actually work.

7. **`features/rag/` is the single retrieval module.** Both chat and slide maker import `rag.retrieve_context`. Slide maker doesn't import `chat_service`. This reflects the post-refactor shape — earlier `retrieve_context` lived in `chat_service.py` and slide had to import chat, which was confusing.

8. **`[OUTLINE_READY ...]` and `[RENDERED:N]` markers in chat content.** These are the only structured signals embedded in free-form LLM messages. Stripped before display, parsed by the frontend / backend for control flow. Avoids needing a separate side channel for "is the outline ready?" / "render finished, here's the file".

9. **Presenton runs Presenton.** We do not generate PPTX ourselves. The outline → final deck step uses Presenton's `/api/v1/ppt/presentation/generate`. Their LLM is told to use ours (`CUSTOM_LLM_URL=${LLM_BASE_URL}`), so the model behind the deck is the same Gemma we use for chat.

10. **Dead routes for visual-template upload.** `GET /slide-sessions/available-templates` and `PATCH /slide-sessions/{id}/template` are wired but not invoked from the UI. They exist for the "upload PPTX as visual template" feature that's deferred to a self-hosted UI flow (see [note-todo.md](../note-todo.md)).
