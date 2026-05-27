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
    assert payload["text"] == "raw chunk text"
    assert payload["tags_topic"] == ["billing"]
    assert payload["doc_type"] == "faq"
    assert payload["intent"] == "how_to"
    assert payload["language"] == "en"
