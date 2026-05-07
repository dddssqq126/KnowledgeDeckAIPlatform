from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def sqlite_url(tmp_path_factory) -> str:
    db_path = tmp_path_factory.mktemp("kd-db") / "test.db"
    return f"sqlite+aiosqlite:///{db_path}"


@pytest_asyncio.fixture(scope="session")
async def shared_engine(sqlite_url: str) -> AsyncIterator[AsyncEngine]:
    from app.db.models import Base

    engine = create_async_engine(sqlite_url, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _patch_app_db(monkeypatch, shared_engine: AsyncEngine, sqlite_url: str) -> None:
    """Make app database dependencies share the SQLite test engine."""
    from app.core.config import get_settings
    from app.db import base as db_base

    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    factory = async_sessionmaker(shared_engine, expire_on_commit=False)
    monkeypatch.setattr(db_base, "_engine", shared_engine, raising=False)
    monkeypatch.setattr(db_base, "_session_factory", factory, raising=False)


@pytest_asyncio.fixture()
async def db_session(shared_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test clean state using SQLite deletes; tests may freely commit."""
    from app.db.models import Base

    factory = async_sessionmaker(shared_engine, expire_on_commit=False)
    async with factory() as setup:
        for table in reversed(Base.metadata.sorted_tables):
            await setup.execute(table.delete())
        await setup.commit()

    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture(autouse=True)
def _patch_app_storage(monkeypatch, sqlite_url: str) -> None:
    """Point app object storage at the SQLite test database."""
    from app.features.knowledge_bases.services import object_storage as storage

    client = storage.SQLiteObjectStorageClient(
        database_url=sqlite_url,
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
