import pytest

from app.features.rag.services import qdrant_store
from app.features.rag.services.sparse_embed import SparseVec


class _NoCollectionClient:
    """Fake Qdrant client whose collection does not exist. query_points must
    never be called — a missing collection should short-circuit to no hits."""

    def collection_exists(self, name: str) -> bool:  # noqa: ARG002
        return False

    def query_points(self, *args, **kwargs):  # noqa: ANN002, ANN003, ARG002
        raise AssertionError("query_points must not run when collection is absent")


@pytest.mark.asyncio
async def test_hybrid_search_returns_empty_when_collection_missing(monkeypatch) -> None:
    monkeypatch.setattr(qdrant_store, "_client", _NoCollectionClient(), raising=False)

    result = await qdrant_store.hybrid_search(
        dense_vector=[0.0] * 8,
        sparse_vector=SparseVec(indices=[1], values=[1.0]),
        user_id=1,
    )

    assert result == []
