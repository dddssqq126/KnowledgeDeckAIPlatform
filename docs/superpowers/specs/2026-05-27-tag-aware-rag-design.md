# Tag-aware RAG — Design Spec

- **Date:** 2026-05-27
- **Branch:** `feat/add-tag-rag`
- **Status:** Approved design, pending implementation plan

## 1. Problem

Retrieval accuracy is weak for one real corpus shape:

- **Client A** — ~1000 documents, each content-rich (code + data). The existing
  pipeline (hybrid dense+sparse → cross-encoder rerank) handles this acceptably.
- **Client B** — ~4000 documents, each **very small**, accuracy felt insufficient.

Root cause for B: a document smaller than one chunk produces a **semantically
thin embedding**, and BM25 term statistics over thousands of tiny fragments are
poor. Dense similarity between a short query and thousands of short fragments is
noisy, and the reranker cannot reliably disambiguate near-identical low-signal
fragments.

## 2. Goal

Add LLM-generated tags to each document and **use them to enrich the indexed
representation**, so tiny documents carry more semantic signal — directly
attacking B's root cause — without risking recall.

Secondarily, tighten the answer-generation system prompt to improve answer
faithfulness (a separate axis from retrieval).

## 3. Non-goals (explicitly out of scope)

- **No hard tag-based filtering by default.** A wrong query-tag inference would
  exclude the correct document and drop recall. Payload tag indexes are created
  so filtering *can* be enabled later, but it is **not** wired into the default
  query path.
- **No `product` / `module` / `version` tags.** The data model is a generic
  knowledge base (KB → arbitrary user files); there is no product taxonomy.
- **No `quality_score`.** LLM self-scoring is unreliable. YAGNI.
- **No async/background ingestion.** Ingestion stays synchronous at upload.
- **No evaluation harness in this scope.** See §10 — improvement is unverified
  without one; this is an accepted, documented risk.

## 4. Tag schema

Per **document** (not per chunk — see §6 for why):

| Field | Source | Values |
|---|---|---|
| `tags_topic` | LLM | list of 2–5 free-form topic keywords |
| `doc_type` | LLM | one of: `guide`, `faq`, `api`, `reference`, `code`, `release_note` |
| `intent` | LLM | one of: `how_to`, `troubleshooting`, `conceptual`, `policy` |
| `language` | system | detected language code (best-effort) |
| `source_updated_at` | system | the file's `created_at` |

`doc_type` / `intent` are constrained enums (LLM output validated against the
allowed set; unknown → `null`). `tags_topic` is free-form.

## 5. How tags improve retrieval (the mechanism — "soft" only)

Three layers, all non-destructive:

1. **Embedding enrichment (primary win for B).** Before embedding a chunk, a
   compact tag line is prepended to the text that is *embedded*:

   ```
   [topics: billing, api-auth | type: faq | intent: how_to]
   <original chunk text>
   ```

   This enriched string is what feeds the dense embedder **and** the sparse
   BM25 encoder. The tiny doc's vector gains extra semantic anchors.

2. **Sparse / keyword channel.** Because the tag line flows into the BM25 text,
   topic keywords become matchable tokens — strengthening proper-noun / topic
   keyword hits.

3. **Filterable payload (kept, not enabled).** Tag fields are stored in the
   Qdrant payload with payload indexes on `doc_type`, `intent`, `tags_topic`,
   so soft `should`-boosts or hard filters can be added later once an eval set
   exists to tune them safely.

**Critical distinction:** enrichment applies only to the *embedded/sparse*
representation. The payload `text` stored for context display and citations
remains the **raw** chunk text, so generated answers and citations are never
polluted by the tag prefix.

## 6. Ingestion flow change (synchronous, at upload)

Current ([ingestion.py](../../../backend/app/features/rag/services/ingestion.py)):

```
parse → chunk → embed → upsert(Qdrant)
```

New:

```
parse → chunk → [LLM tag (1 call/document)] → enrich embed-text with tags
      → embed(enriched) + sparse(enriched) → upsert(raw text + tag payload)
```

- **Granularity: per-document, one LLM call.** Tags apply to every chunk of the
  document. For B's tiny docs (≈1 chunk) per-document == per-chunk but cheap;
  for A's rich docs, per-document tags are coarse but adequate for enrichment.
- **Tag input text:** the full parsed document text, truncated to
  `rag_tag_max_chars` (head) to bound token cost on large A documents.
- **Tagging model:** reuse the existing chat LLM (`llm_*` settings) via the same
  `ChatOpenAI` path used by `rewrite_for_retrieval`. Temperature 0.
- **Cost:** +1 LLM call per upload (~+1–4s, contends for GPU 0 with chat).
  Accepted for MVP.

## 7. Components / files touched

| File | Change |
|---|---|
| `features/rag/services/tagger.py` (new) | `generate_doc_tags(text, filename) -> DocTags`; LLM call + strict parse/validate; returns empty `DocTags` on failure |
| `features/rag/services/ingestion.py` | call tagger per document; build enriched embed-text; pass tags to upsert |
| `features/rag/services/qdrant_store.py` | `upsert_chunks` accepts + stores tag payload fields; `ensure_collection`/index creation adds payload indexes for `doc_type`, `intent`, `tags_topic` |
| `features/chat/services/chat_service.py` | extend `SYSTEM_PROMPT` (see §8) |
| `core/config.py` | `rag_tagging_enabled: bool = True`, `rag_tag_max_chars: int` |
| `db/migrations` | none — tags live only in the Qdrant payload, not SQL |

A new payload index requires existing collections to be re-indexed (see §9).

## 8. System prompt change (separate axis: answer faithfulness)

Append to the existing `SYSTEM_PROMPT` (do **not** alter citation formatting or
the code-assistance block):

- For document Q&A, answer **only** from `Context:`; do not fabricate facts not
  present in it.
- If `Context:` is present but insufficient to answer, say so plainly
  ("資料不足以回答" / "the documents don't cover this") rather than guessing.
- If the question is ambiguous, ask **one** clarifying question before answering.

**Expectation set in the spec:** this improves answer quality/faithfulness only.
It runs after retrieval and does **not** change which documents are found.

## 9. Backfilling the existing corpus

Existing A (1000) + B (4000) documents have no tags. The existing admin reindex
endpoint ([rag/api/admin.py](../../../backend/app/features/rag/api/admin.py))
re-fetches source files from object storage and re-runs ingestion, so after
deploy a single reindex run repopulates all chunks through the new tagging path.

- This is a **batch job**: ~5000 LLM calls, run off-peak (contends for GPU 0).
- Run per-KB or globally via the admin endpoint.

## 10. Error handling & robustness

- **Tag LLM failure / timeout / malformed output:** log and continue with empty
  tags. The document is still embedded (un-enriched) and indexed. **An upload
  must never fail because tagging failed.**
- **Enum validation:** `doc_type` / `intent` outside the allowed set → `null`.
- **`rag_tagging_enabled=False`:** skips tagging entirely; ingestion behaves
  exactly as today (escape hatch + A/B comparison lever).

## 11. Testing (TDD)

- `tagger`: parses well-formed LLM output into `DocTags`; malformed/garbage →
  empty `DocTags`; enum values outside the allowed set → `null`.
- enrichment helper: produces the expected `[topics: … | type: … | intent: …]`
  prefix; payload stores **raw** text, vector built from **enriched** text
  (assert via a fake embedder capturing its input).
- ingestion integration: an ingested file's Qdrant payload carries the tag
  fields; `rag_tagging_enabled=False` produces no tag fields and no enrichment.
- system prompt: assert the new clauses are present (the citation/code blocks
  remain unchanged).

Backend tests run on the Postgres testcontainer per
[ARCHITECTURE.md § Test Strategy](../../ARCHITECTURE.md#test-strategy).

## 12. Risks

- **Unverified benefit.** Without an eval set, we cannot prove tag enrichment
  improves B's accuracy. Mitigation: `rag_tagging_enabled` makes before/after
  comparison possible; collecting ~30–50 real Client-B queries later remains the
  recommended follow-up.
- **Upload latency + GPU contention.** +1 LLM call per upload on the shared
  GPU 0. Acceptable for MVP; revisit async ingestion if it hurts UX.
- **Coarse per-document tags for A's rich docs.** Acceptable: enrichment is
  additive and never removes signal.
