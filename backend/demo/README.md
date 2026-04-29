# Demo: standalone scripts mirroring the four core pipelines

Self-contained Python scripts that re-implement the **key functions**
of KnowledgeDeck end-to-end. Each script reads top-to-bottom — no
abstraction layers, no `await rag.retrieve_context(...)` black boxes.

These scripts **do not import from `app/`**. They duplicate the
production logic so a reader can understand the full algorithm by
reading one file. The trade-off is drift: if `backend/app/features/...`
changes the pipeline, these scripts will silently fall behind.

## Files

| Script | Mirrors (production source) | Demonstrates |
|---|---|---|
| `_common.py` | `app/core/config.py` env defaults | Service URLs + `DEMO_USER_ID/KB_ID` + cleanup helper. Configuration only — no algorithms. |
| `01_kb_ingest.py` | `features/rag/services/{document_parser,text_splitter,sparse_embed,qdrant_store,ingestion}.py` | Parse (txt/md/pdf/docx/pptx/py/html/css/cs) → recursive char-aware split → dense (bge-m3) + sparse (BM25) embed → upsert to Qdrant with named-vector schema. |
| `02_rag_query.py` | `features/rag/services/{rag,qdrant_store,sparse_embed,model_clients}.py` | Dual-embed query → Qdrant hybrid prefetch + RRF fusion → cross-encoder rerank (`/v1/score`) → threshold filter → top-K context blocks. |
| `03_chat.py` | `features/chat/services/chat_service.py` + `features/rag/services/rag.py` | Multi-turn REPL: query rewriter (abbreviation expansion + pronoun resolution) → RAG retrieval → SSE streaming reply → history maintenance. |
| `04_slide.py` | `features/slides/services/{slide_chat_service,presenton_client}.py` + slide render flow in `features/slides/api/slide_sessions.py` | Multi-turn REPL with planner SYSTEM_PROMPT → RAG anchored to first user message → `[OUTLINE_READY]` marker detection → auto-render via Presenton → write PPTX to disk. |
| `main.py` | All of 01–04 — non-interactive scenario | One-command end-to-end smoke test: cleanup → ingest a built-in Kubernetes primer → RAG query → 2-turn chat (verifies rewriter + multi-turn pronoun resolution) → 2-turn slide planner → Presenton render. Prints PASS / FAIL / INCONCLUSIVE per stage. |

## Pin

All four scripts are pinned to commit **`a9ad2d5`**. Each script's
docstring lists the canonical production files it mirrors. When those
files change, sync this directory by hand — there is no auto-watch.

## Running (inside `knowledgedeck_backend`)

The compose stack must be up (`docker compose --profile gpu up -d`).
All required Python deps (`httpx`, `qdrant-client`, `fastembed`,
`pypdf`, `python-docx`, `python-pptx`, `langchain-text-splitters`)
already ship in the backend image — no extra install.

### Quick smoke test (recommended first run)

```bash
docker exec -it knowledgedeck_backend bash
cd /app/demo
python main.py
```

`main.py` is a non-interactive scenario that drives every layer of the
stack. Use it after a fresh deploy to verify all five services
(Postgres is unused here, but Qdrant + vLLM chat + vLLM embed + vLLM
rerank + Presenton are all touched) actually wire up correctly.

What it does:

1. **cleanup** – wipes any leftover `DEMO_USER_ID=999` points in Qdrant
2. **ingest** – embeds a built-in Kubernetes primer (no sample file
   needed — the doc is hard-coded in the script)
3. **query** – runs `"What is k8s?"` and asserts ≥1 citation comes back
   (this is the canary for the rewriter + rerank threshold combo)
4. **chat** – 2 scripted turns:
   - `"What is k8s?"` → expects rewriter to expand `k8s → Kubernetes`
   - `"What about its networking model?"` → expects rewriter to resolve
     `its` against turn 1, then assert turn 2 still returns citations
5. **slide** – feeds the planner a fully-specified topic and a `"yes,
   render it"` confirmation, expects `[OUTLINE_READY]` to emerge,
   parses the outline, sends it to Presenton, writes the PPTX to
   `<output-dir>/smoketest-<UTC>.pptx`

Per-stage status:

- **PASS** – stage's deterministic assertion held
- **FAIL** – stage's assertion failed (pipeline is broken — investigate)
- **INCONCLUSIVE** – external dependency unreachable (e.g. Presenton
  down, Qdrant down) or LLM didn't follow instructions on this run

Exit code is `0` if no stage **FAILED** (PASS / INCONCLUSIVE both ok),
`1` otherwise — safe to use in CI as a deployment gate.

Useful flags:

```bash
python main.py --no-slide          # skip stage 5 (no Presenton needed)
python main.py --keep-vectors      # don't drop demo vectors at the end
python main.py --output-dir ./out  # change PPTX destination
```

### Per-pipeline scripts (interactive / individual)

```bash
# 1. Ingest a file into Qdrant under DEMO_USER_ID=999.
python 01_kb_ingest.py /path/to/your.pdf --cleanup-first

# 2. Query the indexed chunks.
python 02_rag_query.py "what is in this document?"

# 3. Chat REPL (RAG on by default).
python 03_chat.py

# 4. Slide-planner REPL → auto-render PPTX.
python 04_slide.py --output-dir /app/demo/output
```

If the backend image is older than the production source you're
mirroring (e.g. you edited `backend/app/...` without rebuilding), the
demo deps are still fine — they live in `requirements.txt`, not in
the app code.

### Running outside the compose network

Set the env vars in `_common.py` to whatever's reachable from your
host:

```bash
export QDRANT_URL=http://localhost:6333
export EMBEDDING_BASE_URL=http://localhost:8001/v1
export LLM_BASE_URL=http://localhost:8000/v1
export RERANK_BASE_URL=http://localhost:8002/v1
export PRESENTON_URL=http://localhost:5001

# `04_slide.py` reads PPTX bytes off the shared volume mounted at
# /presenton_data inside the backend container. Outside the container
# you must point PRESENTON_DATA_ROOT at the host path of the
# `presenton_data` Docker volume — most users will run 04_slide.py
# inside the container instead.
```

## What the scripts do NOT do

- **No auth / no DB.** Production reads chunks via the FastAPI
  endpoints with a Bearer token. Demo scripts talk directly to Qdrant
  + vLLM + Presenton with no user table, no `KnowledgeFile` row, no
  soft-delete handling.
- **No async.** Production is async (FastAPI handlers, asyncio.gather
  for parallel embed). Demos are sync `httpx.Client` because they're
  CLI scripts and clarity wins over throughput.
- **No persistence between runs.** Chat / slide history lives in
  Python lists, not Postgres. `:reset` or `:exit` and it's gone.
- **No multi-user isolation.** Everything writes under `DEMO_USER_ID=999`.
  Use `cleanup_demo_vectors()` (or `01_kb_ingest.py --cleanup-first`)
  to wipe between iterations.

## Drift policy

When you change a production pipeline:

1. Find the matching demo script (table above).
2. Apply the same change there.
3. Update the commit-sha pin in the script's docstring + this README's
   "Pin" line to the new HEAD.

The demos are educational artifacts, not load-bearing code, so missing
a sync is not a release blocker — but a stale demo is worse than no
demo at all, so prefer fixing or deleting over leaving it stale.
