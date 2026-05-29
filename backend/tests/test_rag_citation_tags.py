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
            "vendor": "teradyne",
            "platform": "j750",
            "knowledge_type": "vendor_doc",
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
            "vendor": "teradyne",
            "platform": "j750",
            "knowledge_type": "vendor_doc",
        }
    ]


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
