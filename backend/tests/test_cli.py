import asyncio

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.db.base import async_session_factory
from app.db.models import User


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _fetch_user(username: str) -> User | None:
    async def _q() -> User | None:
        async with async_session_factory()() as session:
            return await session.scalar(select(User).where(User.username == username))

    return asyncio.run(_q())


def test_create_user_inserts_row(runner: CliRunner, db_session) -> None:
    result = runner.invoke(cli_app, ["create-user", "alice", "--password", "hunter2"])
    assert result.exit_code == 0, result.output
    user = _fetch_user("alice")
    assert user is not None
    assert user.password == "hunter2"


def test_create_user_rejects_existing_username(runner: CliRunner, db_session) -> None:
    first = runner.invoke(cli_app, ["create-user", "bob", "--password", "pwd"])
    assert first.exit_code == 0

    duplicate = runner.invoke(
        cli_app, ["create-user", "bob", "--password", "different"]
    )
    assert duplicate.exit_code != 0
    assert "already exists" in duplicate.output.lower()


def test_suggest_tag_aliases_empty_database_outputs_json(
    runner: CliRunner, db_session
) -> None:
    result = runner.invoke(cli_app, ["suggest-tag-aliases"])

    assert result.exit_code == 0, result.output
    assert '"suggestions": []' in result.output
