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
        lambda text, filename: _coro(
            DocTags(
                topic=["billing"],
                doc_type="faq",
                vendor="teradyne",
                platform="ultraflex",
                knowledge_type="vendor_doc",
            )
        ),
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

    assert captured["embed_texts"][0].startswith(
        "[topics: billing | type: faq | vendor: teradyne | "
        "platform: ultraflex | knowledge_type: vendor_doc]\n"
    )
    assert captured["upsert"]["chunks"][0]["text"] == "raw body"
    assert captured["upsert"]["tags"].topic == ["billing"]
    assert captured["upsert"]["tags"].vendor == "teradyne"
    assert file_row.tag_vendor == "teradyne"
    assert file_row.tag_platform == "ultraflex"
    assert file_row.tag_knowledge_type == "vendor_doc"
    assert file_row.status is FileStatus.INDEXED


def _coro(value):
    async def _c():
        return value
    return _c()


@pytest.mark.asyncio
async def test_ingest_skips_tagging_when_disabled(monkeypatch, db_session, file_row):
    from app.core.config import Settings

    monkeypatch.setattr(ingestion, "get_settings", lambda: Settings(rag_tagging_enabled=False))
    monkeypatch.setattr(
        document_parser, "parse",
        lambda ext, data: [document_parser.ParsedSegment(text="raw body", page_number=1)],
    )

    def _boom(text, filename):
        raise AssertionError("generate_doc_tags must not be called when tagging disabled")

    monkeypatch.setattr(ingestion.tagger, "generate_doc_tags", _boom)

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

    # no enrichment prefix — embedded text equals the raw chunk text
    assert captured["embed_texts"] == ["raw body"]
    assert captured["upsert"]["tags"] == DocTags.empty()
    assert file_row.status is FileStatus.INDEXED
