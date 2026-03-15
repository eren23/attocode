"""Async SQLAlchemy engine and session management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    """Create the async engine and session factory.

    Args:
        database_url: PostgreSQL connection string (postgresql+asyncpg://...).
    """
    global _engine, _session_factory

    if _engine is not None:
        logger.warning("init_engine() called more than once; disposing previous engine")

    _engine = create_async_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("Database engine initialized")


async def dispose_engine() -> None:
    """Dispose the async engine, closing all connections."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session. For use as a FastAPI dependency."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")
    async with _session_factory() as session:
        yield session


def get_engine() -> AsyncEngine | None:
    """Return the current engine (or None if not initialized)."""
    return _engine
