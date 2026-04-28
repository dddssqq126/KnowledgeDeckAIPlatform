import pytest

from app.features.rag.services import sparse_embed


@pytest.mark.asyncio
async def test_sparse_embed_is_deterministic() -> None:
    text = "Kubernetes pod lifecycle and kubernetes networking"

    first = await sparse_embed.embed_query(text)
    second = await sparse_embed.embed_query(text)

    assert first.indices == second.indices
    assert first.values == second.values
    assert len(first.indices) > 0


@pytest.mark.asyncio
async def test_sparse_embed_query_and_passage_share_hashed_vocabulary() -> None:
    text = "GPU GPU inference"

    query_vec = await sparse_embed.embed_query(text)
    passage_vec = (await sparse_embed.embed_passages([text]))[0]

    # Same vocabulary mapping => same active dimensions.
    assert query_vec.indices == passage_vec.indices
    assert len(query_vec.indices) == 2
    assert all(v > 0 for v in query_vec.values)
    assert all(v > 0 for v in passage_vec.values)
