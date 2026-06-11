import pytest

from app.features.rag.services import rag
from app.features.rag.services.sparse_embed import SparseVec


def test_rerank_passage_includes_metadata() -> None:
    passage = rag._rerank_passage(
        {
            "payload": {
                "filename": "pcie-spec.pdf",
                "text": "link training details",
                "vendor": "pcisig",
                "platform": "pcie_5.0",
                "knowledge_type": "specification",
                "doc_type": "reference",
                "tags_topic": ["pcie", "ltssm"],
            }
        }
    )

    assert "filename: pcie-spec.pdf" in passage
    assert "vendor: pcisig" in passage
    assert "platform: pcie_5.0" in passage
    assert "topics: pcie, ltssm" in passage
    assert passage.endswith("link training details")


def test_rerank_passage_truncates_oversized_payload(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(rag_rerank_passage_max_chars=200),
    )

    passage = rag._rerank_passage(
        {
            "payload": {
                "filename": "large-code.cs",
                "text": "HEAD" + ("x" * 500) + "TAIL",
                "vendor": "unknown",
                "platform": "unknown",
                "knowledge_type": "code",
                "doc_type": "source",
            }
        }
    )

    assert len(passage) == 200
    assert "filename: large-code.cs" in passage
    assert "HEAD" in passage
    assert passage.endswith("TAIL")
    assert "truncated due to model context limit" in passage


def test_rerank_batches_respect_total_character_budget() -> None:
    batches = rag._rerank_batches(
        "query",
        ["a" * 5, "b" * 5, "c" * 5],
        max_chars=20,
    )

    assert batches == [[(0, "a" * 5), (1, "b" * 5)], [(2, "c" * 5)]]


def test_rerank_batches_keep_default_candidate_set_in_one_request() -> None:
    # bge-reranker-base has a 512-token window, so each passage is capped
    # before scoring. With the default 40 rerank candidates, the capped inputs
    # still fit in one /score call, so normal retrieval keeps the same request
    # count.
    batches = rag._rerank_batches(
        "normal engineering question",
        ["p" * 1000 for _ in range(40)],
        max_chars=64_000,
    )

    assert len(batches) == 1
    assert len(batches[0]) == 40


@pytest.mark.asyncio
async def test_rank_hits_trims_query_and_batches_passages(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(
            rag_rerank_query_max_chars=50,
            rag_rerank_passage_max_chars=60,
            rag_rerank_batch_max_chars=120,
        ),
    )

    calls: list[tuple[str, list[str]]] = []

    class _FakeReranker:
        async def score(self, query, passages):
            calls.append((query, list(passages)))
            return [(i, float(len(calls) * 10 + i)) for i, _ in enumerate(passages)]

    hits = [
        {
            "score": 0.1,
            "payload": {
                "filename": f"{i}.txt",
                "text": "HEAD" + (str(i) * 200) + "TAIL",
            },
        }
        for i in range(3)
    ]

    monkeypatch.setattr(rag, "_build_reranker", lambda: _FakeReranker())

    ranked = await rag._rank_hits("Q" * 200, hits)

    assert len(calls) == 3
    assert all(len(query) == 50 for query, _ in calls)
    assert all(len(passage) <= 60 for _, passages in calls for passage in passages)
    assert sorted(index for index, _ in ranked) == [0, 1, 2]
    assert ranked[0][1] > ranked[-1][1]


def test_select_final_hits_limits_repeated_files(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(rag_final_top_k=4, rag_per_file_context_limit=2),
    )
    hits = [
        {"score": 1.0, "payload": {"file_id": 1, "filename": f"a-{i}.txt"}}
        for i in range(3)
    ] + [
        {"score": 1.0, "payload": {"file_id": 2, "filename": "b.txt"}},
        {"score": 1.0, "payload": {"file_id": 3, "filename": "c.txt"}},
    ]

    selected = rag._select_final_hits(
        hits,
        [(0, 0.9), (1, 0.8), (2, 0.7), (3, 0.6), (4, 0.5)],
        min_score=0.0,
    )

    assert [hit["payload"]["file_id"] for hit in selected] == [1, 1, 2, 3]


def test_select_final_hits_applies_tag_match_boost(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(
            rag_final_top_k=2,
            rag_per_file_context_limit=3,
            rag_tag_match_boost=0.05,
        ),
    )
    hits = [
        {
            "score": 0.2,
            "payload": {
                "file_id": 1,
                "vendor": "3gpp",
                "platform": "5g_nr",
                "knowledge_type": "standard",
            },
        },
        {
            "score": 0.2,
            "payload": {
                "file_id": 2,
                "vendor": "unknown",
                "platform": "unknown",
                "knowledge_type": "document",
            },
        },
    ]

    selected = rag._select_final_hits(
        hits,
        [(0, 0.08), (1, 0.09)],
        min_score=0.1,
        query_tags={
            "vendor": "3gpp",
            "platform": "5g_nr",
            "knowledge_type": "standard",
        },
    )

    assert [hit["payload"]["file_id"] for hit in selected] == [1]
    assert selected[0]["rerank_score"] == 0.08
    assert selected[0]["score"] == pytest.approx(0.23)


def test_select_final_hits_accepts_deep_mode_limit(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(rag_final_top_k=2, rag_per_file_context_limit=10),
    )
    hits = [
        {"score": 1.0, "payload": {"file_id": i, "filename": f"{i}.txt"}}
        for i in range(5)
    ]

    selected = rag._select_final_hits(
        hits,
        [(i, 0.9) for i in range(5)],
        min_score=0.0,
        final_top_k=4,
    )

    assert [hit["payload"]["file_id"] for hit in selected] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_coverage_judge_trims_oversized_prompt(monkeypatch) -> None:
    from app.core.config import Settings

    captured = {}

    class _FakeJudge:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[-1].content
            return type(
                "Result",
                (),
                {"content": '{"status":"answered","reason":"ok","retry":false}'},
            )()

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(
            rag_coverage_user_message_max_chars=80,
            rag_coverage_query_max_chars=70,
            rag_coverage_context_max_chars=90,
        ),
    )
    monkeypatch.setattr(rag, "_build_coverage_judge", lambda: _FakeJudge())

    judgment = await rag._judge_coverage(
        user_message="USER" + ("u" * 200) + "TAIL",
        retrieval_query="QUERY" + ("q" * 200) + "TAIL",
        context="CTX" + ("c" * 200) + "TAIL",
    )

    assert judgment is not None
    prompt = captured["prompt"]
    assert "truncated due to model context limit" in prompt
    assert len(prompt) < 400


@pytest.mark.asyncio
async def test_checked_deep_mode_answered_does_not_retry(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_retrieve_pass(**kwargs):
        calls.append(kwargs["query"])
        return rag._RetrievalPass(
            query=kwargs["query"],
            candidates=[],
            final_hits=[],
            context="[1] source_id=1 filename=a.txt\nanswer",
            citations=[{"file_id": 1, "filename": "a.txt"}],
        )

    async def fake_judge_coverage(**_kwargs):
        return rag.CoverageJudgment(status="answered", reason="enough", retry=False)

    monkeypatch.setattr(rag, "_retrieve_pass", fake_retrieve_pass)
    monkeypatch.setattr(rag, "_judge_coverage", fake_judge_coverage)

    result = await rag.retrieve_context_checked(
        user_id=1,
        kb_ids=None,
        query="original query",
        user_message="question?",
        deep_mode=True,
    )

    assert calls == ["original query"]
    assert result.context.endswith("answer")
    assert result.diagnostics.coverage_status == "answered"
    assert result.diagnostics.retried is False
    assert result.diagnostics.retrieval_note() is None


@pytest.mark.asyncio
async def test_checked_deep_mode_retries_and_merges_candidates(monkeypatch) -> None:
    from app.core.config import Settings

    first_hit = {
        "score": 0.5,
        "payload": {
            "file_id": 1,
            "filename": "first.txt",
            "text": "first pass evidence",
            "chunk_index": 0,
        },
    }
    duplicate_first_hit = {
        "score": 0.4,
        "payload": {
            "file_id": 1,
            "filename": "first.txt",
            "text": "duplicate first pass evidence",
            "chunk_index": 0,
        },
    }
    retry_hit = {
        "score": 0.7,
        "payload": {
            "file_id": 2,
            "filename": "retry.txt",
            "text": "retry evidence",
            "chunk_index": 0,
        },
    }
    search_queries: list[str] = []
    judge_contexts: list[str] = []

    async def fake_search_candidates(**kwargs):
        search_queries.append(kwargs["query"])
        if kwargs["query"] == "alternate angle":
            return [duplicate_first_hit, retry_hit]
        return [first_hit]

    async def fake_rank_hits(query, hits):
        if "alternate angle" in query:
            assert len(hits) == 2
            return [(1, 0.95), (0, 0.9)]
        return [(0, 0.9)]

    async def fake_judge_coverage(**kwargs):
        judge_contexts.append(kwargs["context"])
        if len(judge_contexts) == 1:
            return rag.CoverageJudgment(
                status="miss",
                reason="missing retry evidence",
                alternate_query="alternate angle",
                retry=True,
            )
        return rag.CoverageJudgment(status="answered", reason="now covered")

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(rag_rerank_min_score=0.0, rag_per_file_context_limit=3),
    )
    monkeypatch.setattr(rag, "_search_candidates", fake_search_candidates)
    monkeypatch.setattr(rag, "_rank_hits", fake_rank_hits)
    monkeypatch.setattr(rag, "_judge_coverage", fake_judge_coverage)

    result = await rag.retrieve_context_checked(
        user_id=1,
        kb_ids=None,
        query="original query",
        user_message="question?",
        deep_mode=True,
    )

    assert search_queries == ["original query", "alternate angle"]
    assert result.context.count("first.txt") == 1
    assert "retry evidence" in result.context
    assert result.citations == [
        {
            "file_id": 2,
            "filename": "retry.txt",
            "doc_type": None,
            "tags_topic": [],
            "vendor": "unknown",
            "platform": "unknown",
            "knowledge_type": "unknown",
        },
        {
            "file_id": 1,
            "filename": "first.txt",
            "doc_type": None,
            "tags_topic": [],
            "vendor": "unknown",
            "platform": "unknown",
            "knowledge_type": "unknown",
        },
    ]
    assert result.diagnostics.retried is True
    assert result.diagnostics.retry_query == "alternate angle"
    assert result.diagnostics.coverage_status == "answered"


@pytest.mark.asyncio
async def test_checked_deep_mode_judge_failure_keeps_first_pass(monkeypatch) -> None:
    async def fake_retrieve_pass(**kwargs):
        return rag._RetrievalPass(
            query=kwargs["query"],
            candidates=[],
            final_hits=[],
            context="first pass context",
            citations=[{"file_id": 1, "filename": "first.txt"}],
        )

    async def fake_judge_coverage(**_kwargs):
        return None

    monkeypatch.setattr(rag, "_retrieve_pass", fake_retrieve_pass)
    monkeypatch.setattr(rag, "_judge_coverage", fake_judge_coverage)

    result = await rag.retrieve_context_checked(
        user_id=1,
        kb_ids=None,
        query="original query",
        user_message="question?",
        deep_mode=True,
    )

    assert result.context == "first pass context"
    assert result.citations == [{"file_id": 1, "filename": "first.txt"}]
    assert result.diagnostics.coverage_status == "not_checked"


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
            "vendor": "teradyne",
            "platform": "j750",
            "knowledge_type": "vendor_doc",
        },
    }

    async def fake_embed_query(_q):
        return [0.0] * 4

    async def fake_sparse_query(_q):
        return SparseVec(indices=[1], values=[1.0])

    async def fake_hybrid(**kwargs):
        assert kwargs["top_k"] == 40
        assert kwargs["prefetch_limit"] == 80
        return [hit]

    class _FakeReranker:
        async def score(self, _q, passages):
            assert "filename: k8s.txt" in passages[0]
            assert "topics: kubernetes, hpa" in passages[0]
            return [(0, 0.9)]

    monkeypatch.setattr(rag.ingestion, "embed_query", fake_embed_query)
    monkeypatch.setattr(rag.sparse_embed, "embed_query", fake_sparse_query)
    monkeypatch.setattr(rag.qdrant_store, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(rag, "_build_reranker", lambda: _FakeReranker())

    _context, citations = await rag.retrieve_context(
        user_id=1,
        kb_ids=None,
        query="hpa?",
        query_tags={"vendor": "teradyne", "platform": "j750"},
    )

    assert citations == [
        {
            "file_id": 7,
            "filename": "k8s.txt",
            "doc_type": "guide",
            "tags_topic": ["kubernetes", "hpa"],
            "vendor": "teradyne",
            "platform": "j750",
            "knowledge_type": "vendor_doc",
        }
    ]


@pytest.mark.asyncio
async def test_retrieve_context_uses_deep_mode_search_profile(monkeypatch) -> None:
    from app.core.config import Settings

    hit = {
        "score": 0.9,
        "payload": {
            "file_id": 7,
            "filename": "deep.txt",
            "text": "body",
            "doc_type": "guide",
            "tags_topic": [],
        },
    }

    async def fake_embed_query(_q):
        return [0.0] * 4

    async def fake_sparse_query(_q):
        return SparseVec(indices=[1], values=[1.0])

    async def fake_hybrid(**kwargs):
        assert kwargs["top_k"] == 80
        assert kwargs["prefetch_limit"] == 160
        return [hit]

    class _FakeReranker:
        async def score(self, _q, passages):
            return [(0, 0.9)]

    monkeypatch.setattr(
        rag,
        "get_settings",
        lambda: Settings(
            rag_rerank_candidate_k=40,
            rag_hybrid_prefetch_limit=80,
            rag_final_top_k=7,
        ),
    )
    monkeypatch.setattr(rag.ingestion, "embed_query", fake_embed_query)
    monkeypatch.setattr(rag.sparse_embed, "embed_query", fake_sparse_query)
    monkeypatch.setattr(rag.qdrant_store, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(rag, "_build_reranker", lambda: _FakeReranker())

    context, citations = await rag.retrieve_context(
        user_id=1,
        kb_ids=None,
        query="deep search",
        deep_mode=True,
    )

    assert "deep.txt" in context
    assert citations[0]["file_id"] == 7


def test_context_includes_source_metadata() -> None:
    context = rag._format_context(
        [
            {
                "payload": {
                    "filename": "advantest-bkm.txt",
                    "page_number": 3,
                    "text": "calibration steps",
                    "vendor": "advantest",
                    "platform": "v93000",
                    "knowledge_type": "internal_bkm",
                    "doc_type": "guide",
                    "tags_topic": ["calibration", "ate"],
                }
            }
        ]
    )

    assert "[1] source_id=1 filename=advantest-bkm.txt (p.3)" in context
    assert "vendor=advantest" in context
    assert "platform=v93000" in context
    assert "knowledge_type=internal_bkm" in context
    assert "doc_type=guide" in context
    assert "topic=calibration,ate" in context
    assert "calibration steps" in context
