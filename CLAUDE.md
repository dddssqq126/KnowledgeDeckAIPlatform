# CLAUDE.md

Project conventions for KnowledgeDeck AI Platform contributors (human or AI). Read these alongside the docs listed below before changing the code.

## Where to look first

- [README.md](README.md) — quickstart, Feature Boundaries ("I only want feature X, take these files"), RAG Strategy summary.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — full system design, per-feature deep dives, design decisions worth knowing.
- [docs/API.md](docs/API.md) — endpoint reference + curl recipes.
- [note-todo.md](note-todo.md) — running TODO list (deferred features, known limitations).

## Code Structure

**Backend is feature-based** under `backend/app/`:

| Path | Purpose |
|---|---|
| `core/` | Pydantic Settings (`config.py`) |
| `db/` | SQLAlchemy 2.0 async models + Alembic migrations |
| `shared/api/` | Cross-feature platform routes: `auth`, `deps`, `health`, `llm_info` |
| `shared/services/` | Cross-feature services: `auth_service` |
| `features/rag/` | Hybrid retrieval + reranker + reindex endpoint (shared by KB, chat, slides) |
| `features/knowledge_bases/` | KB CRUD + file upload + SQLite object storage |
| `features/chat/` | Chat sessions + SSE stream + multi-turn rewriter |
| `features/slides/` | Slide-planner + Presenton render |

Each `features/<feature>/` has its own `api/` (FastAPI routers) and `services/` (business logic). When adding a new endpoint or service, drop it under the owning feature — **do not recreate the old flat `app/api/` or `app/services/` directories**.

**Frontend is route-based** under `frontend/app/(protected)/`. Per-feature stores + clients live in `frontend/lib/<feature>-store.ts` and `frontend/lib/<feature>.ts`.

## Branching Workflow

- `main` — stable.
- `dev` — active development.
- Feature work branches from `dev`.
- Do not commit directly to `main` unless the user explicitly requests it.

## Development Rules

- Use TDD for feature and bugfix work.
- Write or update tests before implementation when behavior changes.
- Keep changes scoped to the requested feature or fix.
- Prefer existing project patterns over introducing new abstractions.
- Do not add unrelated refactors.

## RAG — don't reinvent the pipeline

[`backend/app/features/rag/services/rag.py`](backend/app/features/rag/services/rag.py) is the single retrieval entry point used by both chat and slide maker. The pipeline is: hybrid (dense bge-m3 + sparse BM25 → RRF fusion) → cross-encoder rerank → threshold filter → top-K context. Chat additionally runs `chat_service.rewrite_for_retrieval` on every RAG-enabled turn (resolves abbreviations like `k8s`, bare terms, and multi-turn pronouns).

If you think you need a new retrieval code path, read [ARCHITECTURE.md § RAG](docs/ARCHITECTURE.md#rag--retrieval-pipeline) first — there's a fair chance the existing module already covers your case.

## Verification

- Run relevant tests before claiming work is complete. Tests are NOT shipped in the production backend image; see [ARCHITECTURE.md § Test Strategy](docs/ARCHITECTURE.md#test-strategy) for the run command.
- For Docker or vLLM service changes, include the validation command in the commit message.
- Backend code changes require `docker compose up -d --build backend` to take effect — there is no dev-mode volume mount on `backend/`.

## Secret + API Key Safety

- Never commit API keys, tokens, passwords, private keys, `.env`, model credentials, or service secrets.
- Use `.env.example` for documented configuration values, with placeholder values only (e.g., `local-dev-key`, `change-me`).
- Before committing, scan staged diffs for secrets or sensitive host-specific paths.
- If a secret is accidentally committed, stop and report it immediately instead of continuing.

## AI Code Review

- Treat AI review comments as review feedback, not automatic truth.
- Verify review suggestions against the codebase before applying them.
- Do not blindly implement review feedback that conflicts with project architecture.

## Git Hygiene

- Keep commits focused and descriptive.
- Do not rewrite shared history unless explicitly requested.
- Do not revert user changes unless explicitly asked.
