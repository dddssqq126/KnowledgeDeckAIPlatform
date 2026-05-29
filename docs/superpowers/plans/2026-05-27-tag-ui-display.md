# Tag visibility in the UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the existing Qdrant document tags read-only in two places — chat citations (doc_type + topics) and the RAG Databases inspector (per-file doc_type/intent/topics + real chunk count).

**Architecture:** Tags already live in the Qdrant payload. B2 passes the tag fields through the existing citation pipeline (no new endpoint). B1 adds `qdrant_store.list_file_tags()` + a read-only `GET /rag/kb/{kb_id}/file-tags` endpoint, and the inspector page renders it. No SQL schema change.

**Tech Stack:** FastAPI, qdrant-client, pytest+testcontainers (backend); Next.js/React, vitest, axios (frontend).

**Design spec:** [docs/superpowers/specs/2026-05-27-tag-ui-display-design.md](../specs/2026-05-27-tag-ui-display-design.md)

---

## Test runners

**BACKEND_TEST `<args>`** — from repo root (timeout 600000ms):
```bash
docker run --rm --network knowledgedeck_net \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/backend:/work" -w /work --env-file .env \
  knowledgedeck-backend \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest -v <args>"
```

**FRONTEND_TEST `<args>`** — from repo root (timeout 300000ms; preserves the image's alpine node_modules):
```bash
docker run --rm -v "$(pwd)/frontend:/app" -v /app/node_modules -w /app \
  knowledgedeck-frontend sh -c "node_modules/.bin/<args>"
```
e.g. `FRONTEND_TEST "vitest run components/CitationList.test.tsx"` or `FRONTEND_TEST "tsc --noEmit"`.

## File structure

| File | Responsibility |
|---|---|
| `backend/app/features/rag/services/rag.py` (modify) | citation dict gains `doc_type` + `tags_topic` |
| `backend/app/features/rag/services/qdrant_store.py` (modify) | `list_file_tags()` aggregation read |
| `backend/app/features/rag/api/inspect.py` (new) | `GET /rag/kb/{kb_id}/file-tags` + `FileTags` model |
| `backend/app/main.py` (modify) | register inspect router |
| `frontend/lib/chat.ts` (modify) | `Citation` gains optional tag fields |
| `frontend/components/CitationList.tsx` (new) | render citations + tag chips (extracted from ChatWorkspace) |
| `frontend/components/ChatWorkspace.tsx` (modify) | use `<CitationList>` |
| `frontend/lib/knowledge-bases.ts` (modify) | `FileTags` type + `listFileTags()` |
| `frontend/app/(protected)/rag-databases/page.tsx` (modify) | real chunk count + tag chips |

---

## Task 1 (B2 backend): citations carry doc_type + tags_topic

**Files:** Modify `backend/app/features/rag/services/rag.py`; new test `backend/tests/test_rag_citation_tags.py`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_citation_tags.py`:
```python
import pytest

from app.features.rag.services import rag
from app.features.rag.services.sparse_embed import SparseVec


@pytest.mark.asyncio
async def test_citations_include_tag_fields(monkeypatch) -> None:
    hit = {
        "score": 0.9,
        "payload": {
            "file_id": 7,
            "filename": "k8s.txt",
            "text": "body",
            "doc_type": "guide",
            "tags_topic": ["kubernetes", "hpa"],
            "intent": "how_to",
        },
    }

    async def fake_embed_query(_q):
        return [0.0] * 4

    async def fake_sparse_query(_q):
        return SparseVec(indices=[1], values=[1.0])

    async def fake_hybrid(**_kwargs):
        return [hit]

    class _FakeReranker:
        async def score(self, _q, _passages):
            return [(0, 0.9)]

    monkeypatch.setattr(rag.ingestion, "embed_query", fake_embed_query)
    monkeypatch.setattr(rag.sparse_embed, "embed_query", fake_sparse_query)
    monkeypatch.setattr(rag.qdrant_store, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(rag, "_build_reranker", lambda: _FakeReranker())

    _context, citations = await rag.retrieve_context(user_id=1, kb_ids=None, query="hpa?")

    assert citations == [
        {
            "file_id": 7,
            "filename": "k8s.txt",
            "doc_type": "guide",
            "tags_topic": ["kubernetes", "hpa"],
        }
    ]
```

- [ ] **Step 2: Run test, verify it FAILS**

BACKEND_TEST `tests/test_rag_citation_tags.py`
Expected: FAIL — citations only contain `file_id` + `filename` (assert mismatch).

- [ ] **Step 3: Add the tag fields to the citation dict**

In `backend/app/features/rag/services/rag.py`, the citation-building loop currently ends with:
```python
        citations.append({"file_id": fid, "filename": hit["payload"]["filename"]})
```
Replace that line with:
```python
        citations.append(
            {
                "file_id": fid,
                "filename": hit["payload"]["filename"],
                "doc_type": hit["payload"].get("doc_type"),
                "tags_topic": hit["payload"].get("tags_topic") or [],
            }
        )
```

- [ ] **Step 4: Run test, verify it PASSES**

BACKEND_TEST `tests/test_rag_citation_tags.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/rag/services/rag.py backend/tests/test_rag_citation_tags.py
git commit -m "feat(rag): include doc_type + topics in citations"
```

---

## Task 2 (B2 frontend): Citation type + CitationList component

**Files:** Modify `frontend/lib/chat.ts`; create `frontend/components/CitationList.tsx` + `frontend/components/CitationList.test.tsx`; modify `frontend/components/ChatWorkspace.tsx`.

- [ ] **Step 1: Extend the Citation type**

In `frontend/lib/chat.ts`, the current type is:
```typescript
export type Citation = { file_id: number; filename: string };
```
Replace with:
```typescript
export type Citation = {
  file_id: number;
  filename: string;
  doc_type?: string | null;
  tags_topic?: string[];
};
```

- [ ] **Step 2: Write the failing test for CitationList**

Create `frontend/components/CitationList.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CitationList } from "./CitationList";

describe("CitationList", () => {
  it("renders filename, doc_type chip, and topic chips", () => {
    render(
      <CitationList
        citations={[
          { file_id: 1, filename: "k8s.txt", doc_type: "guide", tags_topic: ["kubernetes", "hpa"] },
        ]}
      />,
    );
    expect(screen.getByText("k8s.txt")).toBeInTheDocument();
    expect(screen.getByText("guide")).toBeInTheDocument();
    expect(screen.getByText("#kubernetes")).toBeInTheDocument();
    expect(screen.getByText("#hpa")).toBeInTheDocument();
  });

  it("renders just the filename when no tags (back-compat)", () => {
    render(<CitationList citations={[{ file_id: 2, filename: "old.txt" }]} />);
    expect(screen.getByText("old.txt")).toBeInTheDocument();
    expect(screen.queryByText("guide")).not.toBeInTheDocument();
  });

  it("renders nothing when empty", () => {
    const { container } = render(<CitationList citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 3: Run test, verify it FAILS**

FRONTEND_TEST `vitest run components/CitationList.test.tsx`
Expected: FAIL — cannot find module `./CitationList`.

- [ ] **Step 4: Create the CitationList component**

Create `frontend/components/CitationList.tsx`:
```tsx
import type { Citation } from "../lib/chat";

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-2 border-t border-zinc-700 pt-2 text-xs text-zinc-400">
      Sources:{" "}
      {citations.map((c, i) => (
        <span key={c.file_id}>
          {i > 0 ? ", " : ""}
          {c.filename}
          {c.doc_type ? (
            <span className="ml-1 rounded bg-zinc-700 px-1 text-[10px] text-zinc-200">
              {c.doc_type}
            </span>
          ) : null}
          {(c.tags_topic ?? []).map((t) => (
            <span key={t} className="ml-1 text-[10px] text-zinc-500">
              #{t}
            </span>
          ))}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run test, verify it PASSES**

FRONTEND_TEST `vitest run components/CitationList.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 6: Use CitationList in ChatWorkspace**

In `frontend/components/ChatWorkspace.tsx`, add the import near the other component imports:
```tsx
import { CitationList } from "./CitationList";
```
Then replace the inline citation block (currently):
```tsx
          {message.citations && message.citations.length > 0 ? (
            <div className="mt-2 border-t border-zinc-700 pt-2 text-xs text-zinc-400">
              Sources:{" "}
              {message.citations.map((c, i) => (
                <span key={c.file_id}>
                  {i > 0 ? ", " : ""}
                  {c.filename}
                </span>
              ))}
            </div>
          ) : null}
```
with:
```tsx
          {message.citations ? (
            <CitationList citations={message.citations} />
          ) : null}
```

- [ ] **Step 7: Verify nothing regressed + typecheck**

FRONTEND_TEST `vitest run`
Expected: all pass (existing + 3 new).
FRONTEND_TEST `tsc --noEmit`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/chat.ts frontend/components/CitationList.tsx frontend/components/CitationList.test.tsx frontend/components/ChatWorkspace.tsx
git commit -m "feat(chat): show doc_type + topics in citation list"
```

---

## Task 3 (B1 backend): qdrant_store.list_file_tags

**Files:** Modify `backend/app/features/rag/services/qdrant_store.py`; new test `backend/tests/test_qdrant_list_file_tags.py`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_qdrant_list_file_tags.py`:
```python
import pytest

from app.features.rag.services import qdrant_store


class _FakePoint:
    def __init__(self, payload):
        self.payload = payload


class _ScrollClient:
    def __init__(self, points):
        self._points = points

    def collection_exists(self, name):  # noqa: ARG002
        return True

    def scroll(self, *, collection_name, scroll_filter, with_payload, with_vectors, limit, offset):  # noqa: ANN001, ARG002
        return self._points, None  # single page


@pytest.mark.asyncio
async def test_list_file_tags_aggregates_by_file(monkeypatch) -> None:
    points = [
        _FakePoint({"file_id": 7, "doc_type": "guide", "intent": "how_to", "tags_topic": ["k8s"]}),
        _FakePoint({"file_id": 7, "doc_type": "guide", "intent": "how_to", "tags_topic": ["k8s"]}),
        _FakePoint({"file_id": 9, "doc_type": "code", "intent": "conceptual", "tags_topic": ["rag"]}),
    ]
    monkeypatch.setattr(qdrant_store, "_client", _ScrollClient(points), raising=False)

    rows = await qdrant_store.list_file_tags(user_id=1, kb_id=2)
    by_id = {r["file_id"]: r for r in rows}

    assert by_id[7] == {"file_id": 7, "doc_type": "guide", "intent": "how_to", "tags_topic": ["k8s"], "chunk_count": 2}
    assert by_id[9]["chunk_count"] == 1


@pytest.mark.asyncio
async def test_list_file_tags_empty_when_collection_missing(monkeypatch) -> None:
    class _NoColl:
        def collection_exists(self, name):  # noqa: ARG002
            return False

    monkeypatch.setattr(qdrant_store, "_client", _NoColl(), raising=False)
    assert await qdrant_store.list_file_tags(user_id=1, kb_id=2) == []
```

- [ ] **Step 2: Run test, verify it FAILS**

BACKEND_TEST `tests/test_qdrant_list_file_tags.py`
Expected: FAIL — `module ... has no attribute 'list_file_tags'`.

- [ ] **Step 3: Implement list_file_tags**

Append to `backend/app/features/rag/services/qdrant_store.py`:
```python
async def list_file_tags(*, user_id: int, kb_id: int) -> list[dict[str, Any]]:
    """Per-file tag summary for one KB, read from the Qdrant payload.

    Returns one dict per file_id: {file_id, doc_type, intent, tags_topic,
    chunk_count}. Tags are per-document, so they're taken from the first point
    seen for each file; chunk_count counts that file's points. Returns [] when
    the collection does not exist yet.
    """
    s = get_settings()

    def _impl() -> list[dict[str, Any]]:
        client = _get_client()
        if not client.collection_exists(s.qdrant_collection):
            return []
        flt = qm.Filter(
            must=[
                qm.FieldCondition(key="user_id", match=qm.MatchValue(value=user_id)),
                qm.FieldCondition(key="kb_id", match=qm.MatchValue(value=kb_id)),
            ]
        )
        agg: dict[int, dict[str, Any]] = {}
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=s.qdrant_collection,
                scroll_filter=flt,
                with_payload=True,
                with_vectors=False,
                limit=256,
                offset=offset,
            )
            for p in points:
                pl = p.payload or {}
                fid = pl.get("file_id")
                if fid is None:
                    continue
                entry = agg.get(fid)
                if entry is None:
                    agg[fid] = {
                        "file_id": fid,
                        "doc_type": pl.get("doc_type"),
                        "intent": pl.get("intent"),
                        "tags_topic": pl.get("tags_topic") or [],
                        "chunk_count": 1,
                    }
                else:
                    entry["chunk_count"] += 1
            if offset is None:
                break
        return list(agg.values())

    return await asyncio.to_thread(_impl)
```

- [ ] **Step 4: Run test, verify it PASSES**

BACKEND_TEST `tests/test_qdrant_list_file_tags.py`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/rag/services/qdrant_store.py backend/tests/test_qdrant_list_file_tags.py
git commit -m "feat(rag): list_file_tags — per-file tag summary from Qdrant"
```

---

## Task 4 (B1 backend): GET /rag/kb/{kb_id}/file-tags endpoint

**Files:** Create `backend/app/features/rag/api/inspect.py`; modify `backend/app/main.py`; new test `backend/tests/test_rag_file_tags_endpoint.py`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_file_tags_endpoint.py`:
```python
import pytest

from app.db.models import KnowledgeBase, User
from app.features.rag.services import qdrant_store


@pytest.fixture()
async def two_users_kb(db_session):
    alice = User(username="alice_ft", password="x")
    bob = User(username="bob_ft", password="x")
    db_session.add_all([alice, bob])
    await db_session.flush()
    kb = KnowledgeBase(owner_user_id=alice.id, name="alice-kb")
    db_session.add(kb)
    await db_session.commit()
    await db_session.refresh(alice)
    await db_session.refresh(bob)
    await db_session.refresh(kb)
    return alice, bob, kb


@pytest.mark.asyncio
async def test_file_tags_returns_tags_for_owner(http_client, two_users_kb, monkeypatch):
    alice, _bob, kb = two_users_kb
    rows = [{"file_id": 7, "doc_type": "guide", "intent": "how_to", "tags_topic": ["k8s"], "chunk_count": 3}]

    async def fake_list(*, user_id, kb_id):
        assert user_id == alice.id and kb_id == kb.id
        return rows

    monkeypatch.setattr(qdrant_store, "list_file_tags", fake_list)

    res = await http_client.get(f"/rag/kb/{kb.id}/file-tags", headers={"Authorization": f"Bearer u_{alice.id}"})
    assert res.status_code == 200
    assert res.json() == rows


@pytest.mark.asyncio
async def test_file_tags_404_for_non_owner(http_client, two_users_kb):
    _alice, bob, kb = two_users_kb
    res = await http_client.get(f"/rag/kb/{kb.id}/file-tags", headers={"Authorization": f"Bearer u_{bob.id}"})
    assert res.status_code == 404
```

- [ ] **Step 2: Run test, verify it FAILS**

BACKEND_TEST `tests/test_rag_file_tags_endpoint.py`
Expected: FAIL — `404` for both (route doesn't exist).

- [ ] **Step 3: Create the inspect router**

Create `backend/app/features/rag/api/inspect.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.models import KnowledgeBase, User
from app.features.rag.services import qdrant_store
from app.shared.api.deps import get_current_user

router = APIRouter(prefix="/rag", tags=["rag"])


class FileTags(BaseModel):
    file_id: int
    doc_type: str | None
    intent: str | None
    tags_topic: list[str]
    chunk_count: int


@router.get("/kb/{kb_id}/file-tags", response_model=list[FileTags])
async def kb_file_tags(
    kb_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[FileTags]:
    kb = await session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.owner_user_id == user.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    if kb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="kb_not_found")
    rows = await qdrant_store.list_file_tags(user_id=user.id, kb_id=kb_id)
    return [FileTags(**r) for r in rows]
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add the import alongside the others:
```python
from app.features.rag.api.inspect import router as rag_inspect_router
```
and register it next to `app.include_router(admin_router)`:
```python
    app.include_router(rag_inspect_router)
```

- [ ] **Step 5: Run test, verify it PASSES**

BACKEND_TEST `tests/test_rag_file_tags_endpoint.py`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/features/rag/api/inspect.py backend/app/main.py backend/tests/test_rag_file_tags_endpoint.py
git commit -m "feat(rag): GET /rag/kb/{id}/file-tags endpoint"
```

---

## Task 5 (B1 frontend): inspector shows real chunk count + tag chips

**Files:** Modify `frontend/lib/knowledge-bases.ts` and `frontend/app/(protected)/rag-databases/page.tsx`; update `frontend/app/(protected)/rag-databases/page.test.tsx`.

- [ ] **Step 1: Add the client fn + type**

In `frontend/lib/knowledge-bases.ts`, after the `KnowledgeFile` type, add:
```typescript
export type FileTags = {
  file_id: number;
  doc_type: string | null;
  intent: string | null;
  tags_topic: string[];
  chunk_count: number;
};

export async function listFileTags(kbId: number): Promise<FileTags[]> {
  if (isMockDataMode()) return [];
  const res = await api.get<FileTags[]>(`/rag/kb/${kbId}/file-tags`);
  return res.data;
}
```
(`isMockDataMode` and `api` are already imported in this file.)

- [ ] **Step 2: Write/extend the failing test**

In `frontend/app/(protected)/rag-databases/page.test.tsx`, ensure the module mock for `../../../lib/knowledge-bases` also mocks `listFileTags`, and add a test. Use this mock setup and test (merge into the existing `vi.mock` block / describe — read the file first to match its harness):
```tsx
// in the vi.mock factory for "../../../lib/knowledge-bases", add:
//   listFileTags: vi.fn(),
// and in the test body:
import { listFileTags } from "../../../lib/knowledge-bases";

it("shows real chunk count and tag chips", async () => {
  vi.mocked(listFileTags).mockResolvedValue([
    { file_id: 1, doc_type: "guide", intent: "how_to", tags_topic: ["kubernetes"], chunk_count: 12 },
  ]);
  // (listKnowledgeBases → [{id:1,...}], listFiles → [{id:1, filename:"k8s.txt", ...}])
  render(<RagDatabasesPage />);
  expect(await screen.findByText("k8s.txt")).toBeInTheDocument();
  expect(await screen.findByText("guide")).toBeInTheDocument();
  expect(await screen.findByText("#kubernetes")).toBeInTheDocument();
  expect(await screen.findByText(/12 vectors/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test, verify it FAILS**

FRONTEND_TEST `vitest run "app/(protected)/rag-databases/page.test.tsx"`
Expected: FAIL — chips / real count not rendered (and/or `listFileTags` not used).

- [ ] **Step 4: Wire real tags into the page**

In `frontend/app/(protected)/rag-databases/page.tsx`:

(a) Update the import to include the new symbols:
```tsx
import {
  type FileTags,
  type KnowledgeBase,
  type KnowledgeFile,
  downloadKnowledgeFile,
  listFileTags,
  listFiles,
  listKnowledgeBases,
} from "../../../lib/knowledge-bases";
```

(b) Extend the `RagDatabase` type with a tag map and drop the estimate:
```tsx
type RagDatabase = KnowledgeBase & {
  files: KnowledgeFile[];
  vector_count: number;
  embedding_model: string;
  fileTags: Map<number, FileTags>;
};
```
Delete the `estimateVectors` function (no longer used).

(c) In the load effect, where each KB row is built, fetch tags and compute the real count:
```tsx
            const files = await listFiles(kb.id);
            const tags = await listFileTags(kb.id);
            const fileTags = new Map(tags.map((t) => [t.file_id, t]));
            return {
              ...kb,
              files,
              file_count: files.length,
              vector_count: tags.reduce((sum, t) => sum + t.chunk_count, 0),
              embedding_model: "BAAI/bge-m3",
              fileTags,
            };
```

(d) In the per-file row render (inside `db.visible_files.map((file) => ( … ))`), after the filename element, render chips from `db.fileTags.get(file.id)`:
```tsx
                          {(() => {
                            const t = db.fileTags.get(file.id);
                            if (!t) return null;
                            return (
                              <div className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px]">
                                {t.doc_type ? (
                                  <span className="rounded bg-emerald-50 px-1 text-emerald-700">{t.doc_type}</span>
                                ) : null}
                                {t.intent ? (
                                  <span className="rounded bg-sky-50 px-1 text-sky-700">{t.intent}</span>
                                ) : null}
                                {t.tags_topic.map((tp) => (
                                  <span key={tp} className="text-muted-foreground">#{tp}</span>
                                ))}
                              </div>
                            );
                          })()}
```
(Place it inside the row's text column, next to the filename — read the file to find the exact element; the row maps `db.visible_files`.)

- [ ] **Step 5: Run test, verify it PASSES + typecheck**

FRONTEND_TEST `vitest run "app/(protected)/rag-databases/page.test.tsx"`
Expected: PASS
FRONTEND_TEST `tsc --noEmit`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add "frontend/lib/knowledge-bases.ts" "frontend/app/(protected)/rag-databases/page.tsx" "frontend/app/(protected)/rag-databases/page.test.tsx"
git commit -m "feat(rag-ui): show real chunk count + tag chips in RAG Databases"
```

---

## Task 6: Full verification + deploy

- [ ] **Step 1: Full backend suite** — BACKEND_TEST `` (no args). Expected: new tests pass; only the 3 known pre-existing env failures (`test_config`, `test_cors`, `test_upload_pdf`) remain.
- [ ] **Step 2: Full frontend suite + typecheck** — FRONTEND_TEST `vitest run` and FRONTEND_TEST `tsc --noEmit`. Expected: all pass, clean.
- [ ] **Step 3: Rebuild** — `docker compose up -d --build backend frontend`; `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.1.102:8080/health` → `200`.
- [ ] **Step 4: UI smoke** — open `192.168.1.102:3000` → RAG Databases shows real vector counts + tag chips on tagged files; Chat with Use RAG against a tagged KB shows doc_type/#topics next to citations.

---

## Self-review notes

- **Spec coverage:** §4 `list_file_tags` → Task 3. §5 endpoint → Task 4; inspector page → Task 5. §6 citation backend → Task 1; frontend → Task 2. §7 edge cases: missing collection → Task 3 guard (tested); cross-user 404 → Task 4 (tested); untagged → `doc_type=None`/`tags_topic=[]` flow through (chips render nothing). §8 testing → each task TDD. §3 non-goals: read-only, no filtering, per-file only — honored (no query-path or edit code).
- **Type consistency:** `FileTags {file_id, doc_type, intent, tags_topic, chunk_count}` identical in backend (`inspect.py`, `list_file_tags`) and frontend (`knowledge-bases.ts`). `Citation` optional fields match the backend citation dict keys (`doc_type`, `tags_topic`). Endpoint path `/rag/kb/{kb_id}/file-tags` identical in `inspect.py` and `listFileTags`.
- **Placeholder scan:** the only "read the file to place it" notes are for inserting JSX into existing large components (ChatWorkspace already shown verbatim; the rag-databases row anchor is `db.visible_files.map`) — the code to insert is fully given.
