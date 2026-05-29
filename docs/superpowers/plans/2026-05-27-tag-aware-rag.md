# Tag-aware RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate LLM tags per document at ingestion and fold them into the embedded/BM25 text (soft enrichment) to lift retrieval accuracy on corpora of many tiny documents, plus tighten the answer system prompt.

**Architecture:** A new `tagger` service makes one LLM call per document (reusing the chat model) returning `topic` / `doc_type` / `intent` / `language`. Ingestion prepends a compact tag line to the text that is embedded and sparse-encoded, while the Qdrant payload keeps the **raw** chunk text plus the tag fields. No hard tag filtering is wired into the query path. The system prompt gains answer-discipline rules.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Qdrant (`qdrant-client`), langchain-openai `ChatOpenAI` against vLLM, pytest + testcontainers.

**Design spec:** [docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md](../specs/2026-05-27-tag-aware-rag-design.md)

---

## Backend test runner

All backend test commands below mean: run this from the repo root (it installs dev deps and runs pytest inside the backend image, with testcontainers spinning up Postgres):

```bash
docker run --rm --network knowledgedeck_net \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$(pwd)/backend:/work" -w /work --env-file .env \
  knowledgedeck-backend \
  sh -c "pip install -q -r requirements-dev.txt && python -m pytest -v <TEST_ARGS>"
```

Referenced below as **BACKEND_TEST `<TEST_ARGS>`**. Tests mount `backend/` so source edits are picked up without rebuilding. The running app does need a rebuild — see Task 7.

## File structure

| File | Responsibility |
|---|---|
| `backend/app/core/config.py` (modify) | add `rag_tagging_enabled`, `rag_tag_max_chars` |
| `backend/app/features/rag/services/tagger.py` (new) | `DocTags`, `enrich_text_for_embedding`, `_parse_tags`, `generate_doc_tags` |
| `backend/app/features/rag/services/qdrant_store.py` (modify) | `upsert_chunks` stores tag payload; `ensure_collection` adds keyword indexes |
| `backend/app/features/rag/services/ingestion.py` (modify) | tag the document, build enriched embed-text, pass tags to upsert |
| `backend/app/features/chat/services/chat_service.py` (modify) | extend `SYSTEM_PROMPT` |
| `backend/tests/test_tagger.py` (new) | tagger unit tests |
| `backend/tests/test_ingestion_tagging.py` (new) | ingestion wiring test |
| `backend/tests/test_qdrant_upsert_tags.py` (new) | payload + index test |
| `backend/tests/test_system_prompt.py` (new) | prompt clause test |

**Note (deviation from spec §4):** `source_updated_at` is **not** stored. It is unused in the query path (recency boosting is a spec non-goal), and `KnowledgeFile.created_at` already exists in SQL if ever needed. Storing it now would be a dead field (YAGNI).

---

## Task 1: Config settings

**Files:**
- Modify: `backend/app/core/config.py` (after the chunking knobs, ~line 83)
- Test: `backend/tests/test_tagging_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tagging_config.py`:

```python
from app.core.config import Settings


def test_tagging_settings_defaults() -> None:
    s = Settings()
    assert s.rag_tagging_enabled is True
    assert s.rag_tag_max_chars == 4000
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_tagging_config.py`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'rag_tagging_enabled'`

- [ ] **Step 3: Add the settings**

In `backend/app/core/config.py`, immediately after the line `chunk_overlap: int = 150`:

```python

    # LLM document tagging (see docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md).
    # When enabled, ingestion makes one LLM call per document to produce
    # topic/doc_type/intent tags and folds them into the embedded text.
    rag_tagging_enabled: bool = True
    rag_tag_max_chars: int = 4000  # head of the doc sent to the tagger LLM
```

- [ ] **Step 4: Run test to verify it passes**

BACKEND_TEST `tests/test_tagging_config.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_tagging_config.py
git commit -m "feat(rag): add tagging config flags"
```

---

## Task 2: Tagger service — pure helpers (DocTags, enrich, parse)

**Files:**
- Create: `backend/app/features/rag/services/tagger.py`
- Test: `backend/tests/test_tagger.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tagger.py`:

```python
from app.features.rag.services.tagger import (
    DocTags,
    _parse_tags,
    enrich_text_for_embedding,
)


def test_parse_well_formed_json() -> None:
    raw = '{"topic": ["billing", "api-auth"], "doc_type": "faq", "intent": "how_to", "language": "en"}'
    tags = _parse_tags(raw)
    assert tags.topic == ["billing", "api-auth"]
    assert tags.doc_type == "faq"
    assert tags.intent == "how_to"
    assert tags.language == "en"


def test_parse_strips_code_fence() -> None:
    raw = '```json\n{"topic": ["x"], "doc_type": "guide", "intent": "conceptual"}\n```'
    tags = _parse_tags(raw)
    assert tags.topic == ["x"]
    assert tags.doc_type == "guide"


def test_parse_rejects_unknown_enum() -> None:
    raw = '{"topic": ["x"], "doc_type": "newspaper", "intent": "vibes"}'
    tags = _parse_tags(raw)
    assert tags.doc_type is None
    assert tags.intent is None


def test_parse_caps_topics_at_five() -> None:
    raw = '{"topic": ["a", "b", "c", "d", "e", "f", "g"]}'
    tags = _parse_tags(raw)
    assert tags.topic == ["a", "b", "c", "d", "e"]


def test_parse_garbage_returns_empty() -> None:
    assert _parse_tags("not json at all") == DocTags.empty()


def test_enrich_prepends_tag_line() -> None:
    tags = DocTags(topic=["billing"], doc_type="faq", intent="how_to", language="en")
    out = enrich_text_for_embedding("How do I pay?", tags)
    assert out == "[topics: billing | type: faq | intent: how_to]\nHow do I pay?"


def test_enrich_empty_tags_returns_text_unchanged() -> None:
    assert enrich_text_for_embedding("hello", DocTags.empty()) == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_tagger.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.features.rag.services.tagger'`

- [ ] **Step 3: Create the tagger module (pure helpers only for now)**

Create `backend/app/features/rag/services/tagger.py`:

```python
"""LLM document tagging for RAG enrichment.

One LLM call per document produces topic/doc_type/intent/language tags. The
tags are folded into the text that gets embedded + sparse-encoded (soft
enrichment) so tiny documents carry more semantic signal. See
docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DOC_TYPES = {"guide", "faq", "api", "reference", "code", "release_note"}
_INTENTS = {"how_to", "troubleshooting", "conceptual", "policy"}
_MAX_TOPICS = 5


@dataclass
class DocTags:
    topic: list[str] = field(default_factory=list)
    doc_type: str | None = None
    intent: str | None = None
    language: str | None = None

    @classmethod
    def empty(cls) -> "DocTags":
        return cls()


def _parse_tags(raw: str) -> DocTags:
    """Parse the tagger LLM output into validated DocTags. Any malformed or
    out-of-vocabulary content degrades to empty/None rather than raising."""
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return DocTags.empty()
    if not isinstance(obj, dict):
        return DocTags.empty()

    topic_raw = obj.get("topic")
    topic = [str(t).strip() for t in topic_raw if str(t).strip()][:_MAX_TOPICS] \
        if isinstance(topic_raw, list) else []

    doc_type = obj.get("doc_type")
    doc_type = doc_type if doc_type in _DOC_TYPES else None

    intent = obj.get("intent")
    intent = intent if intent in _INTENTS else None

    language = obj.get("language")
    language = str(language).strip() if isinstance(language, str) and language.strip() else None

    return DocTags(topic=topic, doc_type=doc_type, intent=intent, language=language)


def enrich_text_for_embedding(text: str, tags: DocTags) -> str:
    """Prepend a compact tag line to the text that will be embedded. Returns
    the text unchanged when there are no usable tags."""
    parts: list[str] = []
    if tags.topic:
        parts.append("topics: " + ", ".join(tags.topic))
    if tags.doc_type:
        parts.append("type: " + tags.doc_type)
    if tags.intent:
        parts.append("intent: " + tags.intent)
    if not parts:
        return text
    return "[" + " | ".join(parts) + "]\n" + text
```

- [ ] **Step 4: Run test to verify it passes**

BACKEND_TEST `tests/test_tagger.py`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/rag/services/tagger.py backend/tests/test_tagger.py
git commit -m "feat(rag): tagger helpers — DocTags parse + embedding enrichment"
```

---

## Task 3: Tagger service — generate_doc_tags (LLM call + failure fallback)

**Files:**
- Modify: `backend/app/features/rag/services/tagger.py`
- Test: `backend/tests/test_tagger.py` (add)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_tagger.py`:

```python
import pytest

from app.features.rag.services import tagger as tagger_mod


@pytest.mark.asyncio
async def test_generate_doc_tags_returns_empty_on_llm_error(monkeypatch) -> None:
    class _BoomLLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("vllm down")

    monkeypatch.setattr(tagger_mod, "_build_tagger_llm", lambda: _BoomLLM())

    tags = await tagger_mod.generate_doc_tags("some document text", "doc.txt")
    assert tags == DocTags.empty()


@pytest.mark.asyncio
async def test_generate_doc_tags_parses_llm_output(monkeypatch) -> None:
    class _FakeResult:
        content = '{"topic": ["k8s"], "doc_type": "guide", "intent": "how_to", "language": "en"}'

    class _FakeLLM:
        def __init__(self):
            self.seen = None

        async def ainvoke(self, messages):
            self.seen = messages
            return _FakeResult()

    fake = _FakeLLM()
    monkeypatch.setattr(tagger_mod, "_build_tagger_llm", lambda: fake)

    tags = await tagger_mod.generate_doc_tags("kubernetes setup guide ...", "setup.md")
    assert tags.topic == ["k8s"]
    assert tags.doc_type == "guide"
    # the document text was passed to the model
    assert any("kubernetes setup guide" in str(m.content) for m in fake.seen)
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_tagger.py::test_generate_doc_tags_returns_empty_on_llm_error`
Expected: FAIL — `AttributeError: module ... has no attribute '_build_tagger_llm'`

- [ ] **Step 3: Add the LLM call**

Append to `backend/app/features/rag/services/tagger.py`:

```python
_TAGGER_SYSTEM = (
    "You label a document for a retrieval system. Read the document and reply "
    "with ONLY a JSON object, no prose, no code fence, with keys:\n"
    '  "topic": array of 2-5 short lowercase topic keywords,\n'
    f'  "doc_type": one of {sorted(_DOC_TYPES)},\n'
    f'  "intent": one of {sorted(_INTENTS)},\n'
    '  "language": ISO language code of the document (e.g. "en", "zh").\n'
    "If unsure about doc_type or intent, omit that key. Output JSON only."
)


def _build_tagger_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        streaming=False,
        temperature=0,
        max_tokens=256,
    )


async def generate_doc_tags(text: str, filename: str) -> DocTags:
    """One LLM call → validated DocTags. Never raises: any failure (LLM down,
    timeout, bad output) returns DocTags.empty() so ingestion can proceed."""
    s = get_settings()
    snippet = text[: s.rag_tag_max_chars]
    prompt = f"Filename: {filename}\n\nDocument:\n{snippet}"
    try:
        result = await _build_tagger_llm().ainvoke(
            [SystemMessage(content=_TAGGER_SYSTEM), HumanMessage(content=prompt)]
        )
        return _parse_tags(result.content or "")
    except Exception:
        logger.exception("doc_tagging_failed filename=%s", filename)
        return DocTags.empty()
```

- [ ] **Step 4: Run test to verify it passes**

BACKEND_TEST `tests/test_tagger.py`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/rag/services/tagger.py backend/tests/test_tagger.py
git commit -m "feat(rag): generate_doc_tags LLM call with safe fallback"
```

---

## Task 4: Qdrant upsert stores tags + keyword indexes

**Files:**
- Modify: `backend/app/features/rag/services/qdrant_store.py` (`upsert_chunks` ~105-150; `ensure_collection` ~81-86)
- Test: `backend/tests/test_qdrant_upsert_tags.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_qdrant_upsert_tags.py`:

```python
import pytest

from app.features.rag.services import qdrant_store
from app.features.rag.services.sparse_embed import SparseVec
from app.features.rag.services.tagger import DocTags


class _CapturingClient:
    def __init__(self) -> None:
        self.points = None

    def upsert(self, *, collection_name, points):  # noqa: ANN001
        self.points = points


@pytest.mark.asyncio
async def test_upsert_writes_tag_payload(monkeypatch) -> None:
    fake = _CapturingClient()
    monkeypatch.setattr(qdrant_store, "_client", fake, raising=False)

    tags = DocTags(topic=["billing"], doc_type="faq", intent="how_to", language="en")
    await qdrant_store.upsert_chunks(
        user_id=1,
        kb_id=2,
        file_id=3,
        filename="f.txt",
        chunks=[{"text": "raw chunk text", "page_number": 1, "chunk_index": 0}],
        dense_vectors=[[0.0] * 4],
        sparse_vectors=[SparseVec(indices=[1], values=[1.0])],
        tags=tags,
    )

    payload = fake.points[0].payload
    # raw text preserved (not enriched)
    assert payload["text"] == "raw chunk text"
    assert payload["tags_topic"] == ["billing"]
    assert payload["doc_type"] == "faq"
    assert payload["intent"] == "how_to"
    assert payload["language"] == "en"
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_qdrant_upsert_tags.py`
Expected: FAIL — `TypeError: upsert_chunks() got an unexpected keyword argument 'tags'`

- [ ] **Step 3: Add the `tags` param + payload fields**

In `backend/app/features/rag/services/qdrant_store.py`, add the import near the top (after the existing imports):

```python
from app.features.rag.services.tagger import DocTags
```

Change the `upsert_chunks` signature to add `tags`:

```python
async def upsert_chunks(
    *,
    user_id: int,
    kb_id: int,
    file_id: int,
    filename: str,
    chunks: list[dict[str, Any]],
    dense_vectors: list[list[float]],
    sparse_vectors: list[SparseVec],
    tags: DocTags,
) -> None:
```

In the `payload={...}` dict inside `_impl`, add the four tag fields after `"chunk_index": chunk["chunk_index"],`:

```python
                    "tags_topic": tags.topic,
                    "doc_type": tags.doc_type,
                    "intent": tags.intent,
                    "language": tags.language,
```

- [ ] **Step 4: Add keyword payload indexes in `ensure_collection`**

In `ensure_collection`'s `_impl`, after the existing integer-index loop (the `for field in ("user_id", "kb_id", "file_id"):` block), add:

```python
        for field in ("doc_type", "intent", "tags_topic", "language"):
            client.create_payload_index(
                collection_name=s.qdrant_collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )
```

- [ ] **Step 5: Run test to verify it passes**

BACKEND_TEST `tests/test_qdrant_upsert_tags.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/features/rag/services/qdrant_store.py backend/tests/test_qdrant_upsert_tags.py
git commit -m "feat(rag): store tag payload + keyword indexes in Qdrant"
```

---

## Task 5: Ingestion wires tagging + enrichment

**Files:**
- Modify: `backend/app/features/rag/services/ingestion.py` (`ingest_file` ~77-96)
- Test: `backend/tests/test_ingestion_tagging.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ingestion_tagging.py`. It drives the real `ingest_file` with the parse/embed/qdrant boundaries faked, asserting (a) embedded text is enriched, (b) upsert gets raw chunks + tags.

```python
import pytest

from app.db.models import FileStatus, KnowledgeFile
from app.features.rag.services import ingestion
from app.features.rag.services import document_parser
from app.features.rag.services.tagger import DocTags


@pytest.fixture()
async def file_row(db_session):
    from app.db.models import KnowledgeBase, User

    user = User(username="taguser", password="")
    db_session.add(user)
    await db_session.flush()
    kb = KnowledgeBase(owner_user_id=user.id, name="kb")
    db_session.add(kb)
    await db_session.flush()
    f = KnowledgeFile(
        knowledge_base_id=kb.id,
        owner_user_id=user.id,
        filename="d.txt",
        extension="txt",
        size_bytes=10,
        content_sha256="x",
        storage_key="k",
        status=FileStatus.UPLOADED,
    )
    db_session.add(f)
    await db_session.commit()
    await db_session.refresh(f)
    return f


@pytest.mark.asyncio
async def test_ingest_enriches_embed_text_and_passes_tags(monkeypatch, db_session, file_row):
    monkeypatch.setattr(
        document_parser, "parse",
        lambda ext, data: [document_parser.ParsedSegment(text="raw body", page_number=1)],
    )
    monkeypatch.setattr(
        ingestion.tagger, "generate_doc_tags",
        lambda text, filename: _coro(DocTags(topic=["billing"], doc_type="faq")),
    )

    captured = {}

    async def fake_embed(texts):
        captured["embed_texts"] = texts
        return [[0.0] * 4 for _ in texts]

    async def fake_sparse(texts):
        from app.features.rag.services.sparse_embed import SparseVec
        return [SparseVec(indices=[1], values=[1.0]) for _ in texts]

    async def fake_ensure():
        return None

    async def fake_upsert(**kwargs):
        captured["upsert"] = kwargs

    monkeypatch.setattr(ingestion, "_embed", fake_embed)
    monkeypatch.setattr(ingestion.sparse_embed, "embed_passages", fake_sparse)
    monkeypatch.setattr(ingestion.qdrant_store, "ensure_collection", fake_ensure)
    monkeypatch.setattr(ingestion.qdrant_store, "upsert_chunks", fake_upsert)

    await ingestion.ingest_file(session=db_session, file_row=file_row, data=b"raw body")

    # embedded text carries the tag prefix
    assert captured["embed_texts"][0].startswith("[topics: billing | type: faq]\n")
    # upsert receives RAW chunk text + the tags object
    assert captured["upsert"]["chunks"][0]["text"] == "raw body"
    assert captured["upsert"]["tags"].topic == ["billing"]
    assert file_row.status is FileStatus.INDEXED


def _coro(value):
    async def _c():
        return value
    return _c()
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_ingestion_tagging.py`
Expected: FAIL — `AttributeError: module 'app.features.rag.services.ingestion' has no attribute 'tagger'` (tagger not imported / not wired)

- [ ] **Step 3: Wire tagging into `ingest_file`**

In `backend/app/features/rag/services/ingestion.py`, add `tagger` to the services import on line 20:

```python
from app.features.rag.services import document_parser, qdrant_store, sparse_embed, tagger, text_splitter
```

Replace the block from `await qdrant_store.ensure_collection()` through the `upsert_chunks(...)` call (currently lines 84-96) with:

```python
        s = get_settings()
        if s.rag_tagging_enabled:
            full_text = "\n".join(seg.text for seg in segments)[: s.rag_tag_max_chars]
            tags = await tagger.generate_doc_tags(full_text, file_row.filename)
        else:
            tags = tagger.DocTags.empty()

        await qdrant_store.ensure_collection()
        raw_texts = [c["text"] for c in chunks]
        embed_texts = [tagger.enrich_text_for_embedding(t, tags) for t in raw_texts]
        dense_vectors = await _embed(embed_texts)
        sparse_vectors = await sparse_embed.embed_passages(embed_texts)
        await qdrant_store.upsert_chunks(
            user_id=file_row.owner_user_id,
            kb_id=file_row.knowledge_base_id,
            file_id=file_row.id,
            filename=file_row.filename,
            chunks=chunks,
            dense_vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
            tags=tags,
        )
```

- [ ] **Step 4: Run test to verify it passes**

BACKEND_TEST `tests/test_ingestion_tagging.py`
Expected: PASS

- [ ] **Step 5: Run the full RAG/ingestion test group for regressions**

BACKEND_TEST `tests/test_ingestion_tagging.py tests/test_qdrant_upsert_tags.py tests/test_tagger.py tests/test_qdrant_hybrid_search.py`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add backend/app/features/rag/services/ingestion.py backend/tests/test_ingestion_tagging.py
git commit -m "feat(rag): tag documents at ingestion and enrich embedded text"
```

---

## Task 6: System prompt answer-discipline rules

**Files:**
- Modify: `backend/app/features/chat/services/chat_service.py` (`SYSTEM_PROMPT` ~81-111)
- Test: `backend/tests/test_system_prompt.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_system_prompt.py`:

```python
from app.features.chat.services.chat_service import SYSTEM_PROMPT


def test_prompt_has_answer_discipline_rules() -> None:
    p = SYSTEM_PROMPT.lower()
    # only answer from context for doc Q&A
    assert "only" in p and "context" in p
    # admit insufficient context
    assert "insufficient" in p or "not enough" in p
    # ask one clarifying question when ambiguous
    assert "clarif" in p
    # citation behavior must remain referenced (unchanged block)
    assert "citation" in p
```

- [ ] **Step 2: Run test to verify it fails**

BACKEND_TEST `tests/test_system_prompt.py`
Expected: FAIL — `assert "insufficient" in p or "not enough" in p` (clause absent)

- [ ] **Step 3: Extend SYSTEM_PROMPT**

In `backend/app/features/chat/services/chat_service.py`, insert this block into the `SYSTEM_PROMPT` string literal, immediately before the final `"Be concise. Do not refuse to recall information..."` line:

```python
    "Document answer discipline:\n"
    "- For questions about the user's documents, answer ONLY from the provided "
    "`Context:`. Do not fabricate facts that are not present in it.\n"
    "- If `Context:` is present but insufficient to answer, say so plainly "
    "(e.g. 'the documents don't cover this' / '資料不足以回答') instead of guessing.\n"
    "- If the question is ambiguous, ask ONE clarifying question before "
    "answering.\n\n"
```

- [ ] **Step 4: Run test to verify it passes**

BACKEND_TEST `tests/test_system_prompt.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/features/chat/services/chat_service.py backend/tests/test_system_prompt.py
git commit -m "feat(chat): add answer-discipline rules to system prompt"
```

---

## Task 7: Deploy, full suite, and corpus backfill

**Files:** none (operational).

- [ ] **Step 1: Run the full backend suite**

BACKEND_TEST `` (no args = whole suite)
Expected: all new tests pass; the only failures are the 3 known pre-existing env-induced ones (`test_config::test_settings_defaults_match_local_development`, `test_cors::test_cors_middleware_skipped_when_origins_unset`, `test_files_upload::test_upload_pdf_happy_path`).

- [ ] **Step 2: Rebuild the backend image (no volume mount on the running backend)**

```bash
docker compose up -d --build backend
```
Expected: `knowledgedeck_backend ... Up`; `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.1.102:8080/health` → `200`

- [ ] **Step 3: Smoke-test a fresh upload gets tagged**

Upload a small document via the UI (Knowledge Bases), then confirm tags landed:

```bash
curl -s http://192.168.1.102:6333/collections/knowledgedeck/points/scroll \
  -H 'Content-Type: application/json' -d '{"limit":1,"with_payload":true}' | python3 -m json.tool
```
Expected: a point whose `payload` contains `tags_topic`, `doc_type`, `intent`.

- [ ] **Step 4: Backfill existing corpus (creates the keyword indexes + re-tags)**

The reindex endpoint drops/recreates the collection (so the new keyword indexes are created) and re-ingests every file through the tagging path. Run it authenticated:

```bash
TOKEN=$(curl -s -X POST http://192.168.1.102:8080/auth/external \
  -H 'Content-Type: application/json' -d '{"username":"admin"}' \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -X POST http://192.168.1.102:8080/admin/rag-reindex \
  -H "Authorization: Bearer $TOKEN"
```
Expected: `{"reindexed": N}` with N = number of non-deleted files. This is ~5000 LLM calls for the full corpus and competes for GPU 0 — run off-peak, or scope to Client B's KB only if the endpoint supports a kb filter (otherwise it reindexes all).

- [ ] **Step 5: Commit (if any operational notes/docs changed)**

No code commit expected here unless docs were updated.

---

## Self-review notes

- **Spec coverage:** §4 schema → Tasks 2/4 (topic/doc_type/intent/language; `source_updated_at` intentionally dropped, see File Structure note). §5 enrichment → Tasks 2/5. §6 ingestion flow → Task 5. §7 components → Tasks 1-6. §8 prompt → Task 6. §9 backfill → Task 7. §10 error handling → Task 3 (empty on LLM failure) + `rag_tagging_enabled` (Tasks 1/5). §11 testing → each task is TDD.
- **Query-side use:** spec §5 layer (c) keeps tags filterable but NOT wired into the query path — correctly NOT implemented here (non-goal §3).
- **Type consistency:** `DocTags`, `enrich_text_for_embedding`, `generate_doc_tags`, `upsert_chunks(..., tags=)` names are consistent across Tasks 2-5.
