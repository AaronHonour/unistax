"""Async database engine wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from unistax.agents.api.db.models import ApiBase


class Database:
    """Owns the async engine and hands out transactional sessions."""

    def __init__(self, url: str, echo: bool = False) -> None:
        kwargs: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
        if url.startswith("sqlite") and ":memory:" in url:
            # One shared connection, otherwise every connection sees an empty database.
            kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.engine = create_async_engine(url, **kwargs)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Create missing tables. Use migrations for schema changes in production."""
        async with self.engine.begin() as conn:
            await conn.run_sync(ApiBase.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session that commits on success and rolls back on error."""
        async with self._sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()
