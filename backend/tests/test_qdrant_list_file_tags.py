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
