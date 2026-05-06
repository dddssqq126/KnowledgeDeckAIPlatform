import io

import pytest
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


TXT = b"hello\n"


async def make_kb_and_file(client, user, *, kb_name="K", filename="x.txt") -> tuple[int, int]:
    kb = await client.post(
        "/knowledge-bases", json={"name": kb_name}, headers=auth(user)
    )
    kb_id = kb.json()["id"]
    f = await client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": (filename, io.BytesIO(TXT), "text/plain")},
        headers=auth(user),
    )
    return kb_id, f.json()["id"]


@pytest.mark.asyncio
async def test_list_files_returns_only_non_deleted(http_client, alice: User) -> None:
    kb_id, file_id = await make_kb_and_file(http_client, alice)
    await http_client.post(
        f"/knowledge-bases/{kb_id}/files",
        files={"file": ("y.txt", io.BytesIO(TXT), "text/plain")},
        headers=auth(alice),
    )
    res = await http_client.get(
        f"/knowledge-bases/{kb_id}/files", headers=auth(alice)
    )
    assert res.status_code == 200
    body = res.json()
    assert {b["filename"] for b in body} == {"x.txt", "y.txt"}
    await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(alice)
    )
    res = await http_client.get(
        f"/knowledge-bases/{kb_id}/files", headers=auth(alice)
    )
    assert {b["filename"] for b in res.json()} == {"y.txt"}


@pytest.mark.asyncio
async def test_delete_file_returns_204(http_client, alice: User) -> None:
    kb_id, file_id = await make_kb_and_file(http_client, alice)
    res = await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(alice)
    )
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_download_file_returns_original_bytes(http_client, alice: User) -> None:
    _, file_id = await make_kb_and_file(http_client, alice)
    res = await http_client.get(
        f"/knowledge-bases/files/{file_id}/download", headers=auth(alice)
    )
    assert res.status_code == 200
    assert res.content == TXT
    assert res.headers["content-type"].startswith("text/plain")
    assert 'filename="x.txt"' in res.headers["content-disposition"]


@pytest.mark.asyncio
async def test_download_file_other_user_returns_404(
    http_client, alice: User, bob: User
) -> None:
    _, file_id = await make_kb_and_file(http_client, alice)
    res = await http_client.get(
        f"/knowledge-bases/files/{file_id}/download", headers=auth(bob)
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_download_deleted_file_returns_404(http_client, alice: User) -> None:
    kb_id, file_id = await make_kb_and_file(http_client, alice)
    await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(alice)
    )
    res = await http_client.get(
        f"/knowledge-bases/files/{file_id}/download", headers=auth(alice)
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_file_other_user_returns_404(
    http_client, alice: User, bob: User
) -> None:
    kb_id, file_id = await make_kb_and_file(http_client, alice)
    res = await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(bob)
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_file_twice_returns_404(http_client, alice: User) -> None:
    kb_id, file_id = await make_kb_and_file(http_client, alice)
    await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(alice)
    )
    res = await http_client.delete(
        f"/knowledge-bases/{kb_id}/files/{file_id}", headers=auth(alice)
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_kb_delete_cascades_to_files(
    http_client, alice: User, db_session
) -> None:
    from sqlalchemy import select

    from app.db.models import KnowledgeFile

    kb_id, file_id = await make_kb_and_file(http_client, alice)
    await http_client.delete(f"/knowledge-bases/{kb_id}", headers=auth(alice))
    # KB now hidden — listing files would also 404 because KB lookup fails first.
    res = await http_client.get(
        f"/knowledge-bases/{kb_id}/files", headers=auth(alice)
    )
    assert res.status_code == 404
    # Verify the cascade actually marked the file row, not just the KB.
    file_row = await db_session.scalar(
        select(KnowledgeFile).where(KnowledgeFile.id == file_id)
    )
    assert file_row is not None
    assert file_row.deleted_at is not None


@pytest.mark.asyncio
async def test_list_files_other_user_returns_404(
    http_client, alice: User, bob: User
) -> None:
    kb_id, _ = await make_kb_and_file(http_client, alice)
    res = await http_client.get(
        f"/knowledge-bases/{kb_id}/files", headers=auth(bob)
    )
    assert res.status_code == 404
