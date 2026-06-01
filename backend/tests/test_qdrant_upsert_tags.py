import pytest

from app.features.rag.services import qdrant_store
from app.features.rag.services.sparse_embed import SparseVec
from app.features.rag.services.tagger import DocTags


class _CapturingClient:
    def __init__(self) -> None:
        self.points = None
        self.calls = []

    def upsert(self, *, collection_name, points):  # noqa: ANN001
        self.points = points
        self.calls.append((collection_name, points))


@pytest.mark.asyncio
async def test_upsert_writes_tag_payload(monkeypatch) -> None:
    fake = _CapturingClient()
    monkeypatch.setattr(qdrant_store, "_client", fake, raising=False)

    tags = DocTags(
        topic=["billing"],
        doc_type="faq",
        intent="how_to",
        language="en",
        vendor="teradyne",
        platform="j750",
        knowledge_type="vendor_doc",
    )
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
    assert payload["text"] == "raw chunk text"
    assert payload["tags_topic"] == ["billing"]
    assert payload["doc_type"] == "faq"
    assert payload["intent"] == "how_to"
    assert payload["language"] == "en"
    assert payload["vendor"] == "teradyne"
    assert payload["platform"] == "j750"
    assert payload["knowledge_type"] == "vendor_doc"


@pytest.mark.asyncio
async def test_upsert_chunks_batches_large_payloads(monkeypatch) -> None:
    from app.core.config import Settings

    fake = _CapturingClient()
    monkeypatch.setattr(qdrant_store, "_client", fake, raising=False)
    monkeypatch.setattr(
        qdrant_store,
        "get_settings",
        lambda: Settings(
            qdrant_collection="test_collection", qdrant_upsert_batch_size=2
        ),
    )

    tags = DocTags.empty()
    chunks = [
        {"text": f"chunk {i}", "page_number": i, "chunk_index": i} for i in range(5)
    ]

    await qdrant_store.upsert_chunks(
        user_id=1,
        kb_id=2,
        file_id=3,
        filename="large.txt",
        chunks=chunks,
        dense_vectors=[[float(i)] for i in range(5)],
        sparse_vectors=[SparseVec(indices=[i], values=[1.0]) for i in range(5)],
        tags=tags,
    )

    assert [len(points) for _, points in fake.calls] == [2, 2, 1]
    assert [collection_name for collection_name, _ in fake.calls] == [
        "test_collection",
        "test_collection",
        "test_collection",
    ]
    assert [
        point.payload["chunk_index"] for _, points in fake.calls for point in points
    ] == [0, 1, 2, 3, 4]
