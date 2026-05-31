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
