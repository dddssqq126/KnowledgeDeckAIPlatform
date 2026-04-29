import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import User


@pytest.fixture()
async def alice(db_session) -> User:
    user = User(username="alice", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture()
async def bob(db_session) -> User:
    user = User(username="bob", password="x")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer u_{user.id}"}


async def make_kb(http_client: AsyncClient, user: User, name: str = "K") -> int:
    res = await http_client.post(
        "/knowledge-bases", json={"name": name}, headers=auth(user)
    )
    return res.json()["id"]


PDF_BYTES = b"%PDF-1.4\n%EOF\n"
TXT_BYTES = b"hello world\n"
CS_BYTES = b"using System;\nclass A {}\n"


@pytest.mark.asyncio
async def test_upload_pdf_happy_path(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("doc.pdf", io.BytesIO(PDF_BYTES), "application/pdf")},
        headers=auth(alice),
    )
    assert res.status_code == 201
    body = res.json()
    assert body["filename"] == "doc.pdf"
    assert body["extension"] == "pdf"
    assert body["size_bytes"] == len(PDF_BYTES)
    assert body["status"] == "uploaded"


@pytest.mark.asyncio
async def test_upload_txt_happy_path(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("note.txt", io.BytesIO(TXT_BYTES), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_upload_cs_happy_path(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("Program.cs", io.BytesIO(CS_BYTES), "text/x-csharp")},
        headers=auth(alice),
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_upload_rejects_unknown_extension(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("x.exe", io.BytesIO(b"PK\x03\x04"), "application/octet-stream")},
        headers=auth(alice),
    )
    assert res.status_code == 400
    assert res.json() == {"detail": "invalid_extension"}


@pytest.mark.asyncio
async def test_upload_rejects_pdf_without_magic(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("evil.pdf", io.BytesIO(b"NOT-A-PDF"), "application/pdf")},
        headers=auth(alice),
    )
    assert res.status_code == 400
    assert res.json() == {"detail": "invalid_content"}


@pytest.mark.asyncio
async def test_upload_rejects_txt_with_null_byte(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("bad.txt", io.BytesIO(b"hello\x00world"), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 400
    assert res.json() == {"detail": "invalid_content"}


@pytest.mark.asyncio
async def test_upload_rejects_txt_not_utf8(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    bad = b"\xff\xfe\xfd not utf-8"
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("bad.txt", io.BytesIO(bad), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 400
    assert res.json() == {"detail": "invalid_content"}


@pytest.mark.asyncio
async def test_upload_rejects_oversize(http_client, alice: User, monkeypatch) -> None:
    # Lower the cap for the test instead of streaming 50 MiB.
    from app.features.knowledge_bases.api import files as files_module
    monkeypatch.setattr(files_module, "MAX_UPLOAD_BYTES", 100)
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("big.txt", io.BytesIO(b"a" * 200), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 413
    assert res.json() == {"detail": "file_too_large"}


@pytest.mark.asyncio
async def test_upload_rejects_duplicate_filename(http_client, alice: User) -> None:
    kb_id = await make_kb(http_client, alice)
    await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("x.txt", io.BytesIO(TXT_BYTES), "text/plain")},
        headers=auth(alice),
    )
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("x.txt", io.BytesIO(TXT_BYTES), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 409
    assert res.json() == {"detail": "duplicate_filename"}


@pytest.mark.asyncio
async def test_upload_to_other_users_kb_returns_404(
    http_client, alice: User, bob: User
) -> None:
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("x.txt", io.BytesIO(TXT_BYTES), "text/plain")},
        headers=auth(bob),
    )
    assert res.status_code == 404
    assert res.json() == {"detail": "kb_not_found"}


@pytest.mark.asyncio
async def test_upload_rolls_back_db_when_storage_put_fails(
    http_client, alice: User, db_session, monkeypatch
) -> None:
    from sqlalchemy import select

    from app.db.models import KnowledgeFile
    from app.features.knowledge_bases.services import object_storage as storage

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated storage outage")

    monkeypatch.setattr(storage.LocalObjectStorageClient, "put_object", boom, raising=True)
    kb_id = await make_kb(http_client, alice)
    res = await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("x.txt", io.BytesIO(TXT_BYTES), "text/plain")},
        headers=auth(alice),
    )
    assert res.status_code == 500
    rows = await db_session.execute(
        select(KnowledgeFile).where(KnowledgeFile.knowledge_base_id == kb_id)
    )
    assert rows.all() == []
