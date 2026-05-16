"""Async engine factory. Lazy by design."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..config import Config

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            Config.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


async def dispose_engine() -> None:
    """Disposed on FastAPI shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
