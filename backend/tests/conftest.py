from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def postgres_url() -> AsyncIterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        sync_url = container.get_connection_url()
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        if async_url.startswith("postgresql://"):
            async_url = async_url.replace("postgresql://", "postgresql+psycopg://", 1)
        yield async_url


@pytest.fixture(scope="session", autouse=True)
def _run_migrations(postgres_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture(scope="session")
async def shared_engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(postgres_url, future=True, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _patch_app_db(monkeypatch, shared_engine: AsyncEngine) -> None:
    """Make app.db.base.get_engine() / async_session_factory() share the test engine."""
    from app.db import base as db_base

    factory = async_sessionmaker(shared_engine, expire_on_commit=False)
    monkeypatch.setattr(db_base, "_engine", shared_engine, raising=False)
    monkeypatch.setattr(db_base, "_session_factory", factory, raising=False)


@pytest_asyncio.fixture()
async def db_session(shared_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test clean state via TRUNCATE; tests may freely commit."""
    factory = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with factory() as setup:
        await setup.execute(text(
            "TRUNCATE TABLE files, knowledge_bases, users RESTART IDENTITY CASCADE"
        ))
        await setup.commit()

    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture(autouse=True)
def _patch_app_storage(monkeypatch, tmp_path_factory) -> None:
    """Point app object storage at per-session local filesystem storage."""
    from app.features.knowledge_bases.services import object_storage as storage

    root = tmp_path_factory.mktemp("kd-storage")
    client = storage.LocalObjectStorageClient(
        root=str(root),
        bucket="kd-test",
    )
    monkeypatch.setattr(storage, "_client", client, raising=False)


@pytest.fixture()
async def http_client():
    """ASGI test client backed by a fresh app instance per test."""
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
