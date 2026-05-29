# Tag visibility in the UI — Design Spec

- **Date:** 2026-05-27
- **Branch:** `feat/add-tag-rag`
- **Status:** Approved design, pending implementation plan
- **Builds on:** [2026-05-27-tag-aware-rag-design.md](2026-05-27-tag-aware-rag-design.md) (tags already produced + stored in the Qdrant payload)

## 1. Problem

Document tags (`tags_topic` / `doc_type` / `intent` / `language`) are written to the
Qdrant payload during ingestion, but **nothing surfaces them**. There is no way
in the product to confirm tagging worked or to see what a document was tagged as —
tags live only in Qdrant, and the SQL `KnowledgeFile` table has no tag columns.

## 2. Goal

Surface the existing tags in two places, **read-only**:

- **B1 — RAG Databases inspector:** show each file's `doc_type` / `intent` /
  topics, and its **real** chunk count (replacing today's fake estimate).
- **B2 — Chat citations:** show the `doc_type` / topics of each cited source.

No new tagging logic, no schema change — this is purely *reading* what's already
in the Qdrant payload and rendering it.

## 3. Non-goals

- No editing of tags from the UI.
- No tag-based filtering/search of the corpus (still a non-goal; soft enrichment only).
- No per-chunk drilldown in the inspector — **per-file summary only** (tags are
  per-document; all chunks of a file share them).
- No SQL schema change / migration.

## 4. Shared backend capability

New function in [`features/rag/services/qdrant_store.py`](../../../backend/app/features/rag/services/qdrant_store.py):

```
async def list_file_tags(*, user_id: int, kb_id: int) -> list[dict]
```

- Scrolls the collection filtered by `user_id` AND `kb_id` (payload filter, same
  pattern as `hybrid_search`).
- If the collection doesn't exist → returns `[]` (reuse the `collection_exists`
  guard already added to `hybrid_search`).
- Aggregates points by `file_id`. Tags are per-document, so take them from the
  first point seen for each file; count points per `file_id` for `chunk_count`.
- Returns one dict per file:
  `{"file_id": int, "doc_type": str|None, "intent": str|None, "tags_topic": list[str], "chunk_count": int}`.

## 5. B1 — RAG Databases inspector

### Backend
New read-only router `backend/app/features/rag/api/inspect.py` (prefix `/rag`),
registered in `backend/app/main.py` alongside the other routers. Kept separate
from `admin.py`, which is for destructive ops (reindex):

```
GET /rag/kb/{kb_id}/file-tags   →  list[FileTags]   (auth: get_current_user)
```

- Verify the KB exists AND `owner_user_id == current_user.id`; otherwise `404`
  (same user-scoping convention as chat sessions). This prevents cross-user reads.
- Returns `list_file_tags(user_id=current_user.id, kb_id=kb_id)`.
- Response model `FileTags`: `file_id: int`, `doc_type: str | None`,
  `intent: str | None`, `tags_topic: list[str]`, `chunk_count: int`.

Placement rationale: it reads Qdrant, which is the shared `rag` module's
responsibility (CLAUDE.md: rag is shared by KB/chat/slides). The knowledge_bases
router keeps owning the SQL file list.

### Frontend
[`frontend/app/(protected)/rag-databases/page.tsx`](../../../frontend/app/(protected)/rag-databases/page.tsx):

- Add a client fn (in `frontend/lib/knowledge-bases.ts`):
  `listFileTags(kbId: number): Promise<FileTags[]>` calling `GET /rag/kb/{kbId}/file-tags`.
- For each KB, after `listFiles(kb.id)`, also fetch `listFileTags(kb.id)` and build
  a `Map<file_id, FileTags>`.
- **Replace `estimateVectors`** with the summed real `chunk_count` from the map
  (`vector_count` = Σ chunk_count). If a file has no tag entry (un-ingested /
  failed / tagging was off), it contributes 0 and shows no chips.
- Render per file: a `doc_type` chip, an `intent` chip, and topic chips
  (`#topic`). Files with no tags show nothing extra (graceful).

## 6. B2 — Chat citation tags

### Backend
[`features/rag/services/rag.py`](../../../backend/app/features/rag/services/rag.py)
`retrieve_context` currently appends `{"file_id", "filename"}` per citation. Extend
the citation dict (pass-through from `hit["payload"]`, which already holds the tags):

```python
citations.append({
    "file_id": fid,
    "filename": hit["payload"]["filename"],
    "doc_type": hit["payload"].get("doc_type"),
    "tags_topic": hit["payload"].get("tags_topic") or [],
})
```

- `intent` is intentionally omitted from citations (kept lean; topics + doc_type
  are the useful signal in-context — matches the brainstorm decision).
- Everything downstream is unchanged: `ChatMessage.citations` is a JSON column
  (stores arbitrary dicts), the SSE `citations` event passes the list through.

### Frontend
- `frontend/lib/chat.ts`: extend
  `Citation = { file_id: number; filename: string; doc_type?: string | null; tags_topic?: string[] }`.
- `frontend/components/ChatWorkspace.tsx` (the chat message renderer) shows the
  `doc_type` + topic chips next to each citation's `filename`. Old persisted
  messages whose citations lack the fields render exactly as before (fields
  optional). The read-only `shared-chat/[token]` view reuses the same citation
  shape, so it picks the chips up for free if it shares the renderer; updating it
  is secondary and can be deferred.

## 7. Error handling / edge cases

- Missing collection → `list_file_tags` returns `[]`; inspector shows files with
  0 vectors and no chips; chat works as today.
- A file present in SQL but absent from Qdrant (ingestion FAILED) → no tag entry;
  inspector shows it with 0 chunk_count, no chips.
- Cross-user / unknown `kb_id` on the endpoint → `404`.
- Untagged points (pre-feature or `rag_tagging_enabled=False`) → `doc_type=None`,
  `tags_topic=[]`; UI renders no chips. No errors.

## 8. Testing (TDD)

Backend:
- `list_file_tags`: aggregation by file_id + chunk_count + per-doc tags, via a fake
  Qdrant client (mirror `test_qdrant_upsert_tags.py` style); missing-collection → `[]`.
- `GET /rag/kb/{kb_id}/file-tags`: returns tags for the owner; `404` for a KB owned
  by another user.
- `rag.py` citation: a unit test asserting citations carry `doc_type` + `tags_topic`
  from the hit payload.

Frontend (vitest):
- `rag-databases/page.test.tsx`: renders real chunk count + tag chips from a mocked
  `listFileTags`.
- citation rendering: a test that a `Citation` with `doc_type`/`tags_topic` renders
  the chips, and one without renders cleanly (back-compat).

## 9. Components / files touched

| File | Change |
|---|---|
| `backend/app/features/rag/services/qdrant_store.py` | `list_file_tags()` |
| `backend/app/features/rag/api/inspect.py` (new) | `GET /rag/kb/{kb_id}/file-tags` + `FileTags` model + KB-ownership check |
| `backend/app/main.py` | register the new `inspect` router |
| `backend/app/features/rag/services/rag.py` | citation dict gains `doc_type` + `tags_topic` |
| `frontend/lib/knowledge-bases.ts` | `FileTags` type + `listFileTags()` |
| `frontend/app/(protected)/rag-databases/page.tsx` | real chunk count + tag chips |
| `frontend/lib/chat.ts` | `Citation` gains optional `doc_type` / `tags_topic` |
| `frontend/components/ChatWorkspace.tsx` | render tag chips in citations |
| tests | as in §8 |

## 10. Suggested order

1. **B2** (citation pass-through) — smallest, no new endpoint.
2. **B1** (new endpoint + `list_file_tags` + inspector page).
