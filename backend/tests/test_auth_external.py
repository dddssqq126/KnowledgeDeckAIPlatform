import pytest
from sqlalchemy import func, select

from app.db.models import User


@pytest.mark.asyncio
async def test_external_creates_user_and_returns_token(http_client, db_session) -> None:
    """A never-seen username is provisioned on the fly and gets a usable token."""
    response = await http_client.post(
        "/auth/external", json={"username": "ext_new_user"}
    )
    assert response.status_code == 200
    body = response.json()

    row = await db_session.scalar(
        select(User).where(User.username == "ext_new_user")
    )
    assert row is not None
    assert body["token"] == f"u_{row.id}"
    assert body["user"] == {"id": row.id, "username": "ext_new_user"}


@pytest.mark.asyncio
async def test_external_reuses_existing_user(http_client, db_session) -> None:
    """Calling with an existing username reuses that user — no duplicate row,
    and the token matches the original id (so prior data stays attached)."""
    existing = User(username="ext_existing", password="hunter2")
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    response = await http_client.post(
        "/auth/external", json={"username": "ext_existing"}
    )
    assert response.status_code == 200
    assert response.json()["token"] == f"u_{existing.id}"

    count = await db_session.scalar(
        select(func.count()).select_from(User).where(User.username == "ext_existing")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_external_empty_username_returns_422(http_client) -> None:
    response = await http_client.post("/auth/external", json={"username": ""})
    assert response.status_code == 422
