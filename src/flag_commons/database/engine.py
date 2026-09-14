"""Engine construction and startup pings."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import sqlalchemy
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import QueuePool

DEFAULT_POOL_SIZE = 10
DEFAULT_MAX_OVERFLOW = 0
DEFAULT_POOL_RECYCLE = 1800  # seconds; Go used a 30-minute max connection lifetime
DEFAULT_CONNECT_RETRIES = 5
DEFAULT_RETRY_BASE_DELAY = 0.5
DEFAULT_RETRY_MAX_DELAY = 5.0

_log = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Engine construction, connection or migration failure."""


def normalize_url(url: str) -> str:
    """Return ``url`` with the ``postgresql+psycopg`` driver selected.

    Accepts ``postgres://``, ``postgresql://`` and ``postgresql+psycopg://``.
    Any other scheme is rejected.
    """
    if not url:
        raise DatabaseError("database: invalid connection string: empty")
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError) as exc:
        raise DatabaseError(f"database: invalid connection string: {exc}") from exc
    parsed = parsed.set(drivername=parsed.drivername.lower())
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    elif parsed.drivername != "postgresql+psycopg":
        raise DatabaseError(
            f"database: invalid connection string: unsupported driver {parsed.drivername!r}"
        )
    return parsed.render_as_string(hide_password=False)


def _engine_kwargs(
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    pool_pre_ping: bool,
    extra: dict[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pool_recycle": pool_recycle,
        "pool_pre_ping": pool_pre_ping,
    }
    poolclass = extra.get("poolclass")
    # NullPool / StaticPool and friends reject queue sizing arguments.
    if poolclass is None or (
        isinstance(poolclass, type) and issubclass(poolclass, QueuePool)
    ):
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
    kwargs.update(extra)
    return kwargs


def create_engine(
    url: str,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    max_overflow: int = DEFAULT_MAX_OVERFLOW,
    pool_recycle: int = DEFAULT_POOL_RECYCLE,
    pool_pre_ping: bool = True,
    **kwargs: Any,
) -> AsyncEngine:
    """Build an :class:`AsyncEngine`. No I/O happens until first use."""
    return create_async_engine(
        normalize_url(url),
        **_engine_kwargs(pool_size, max_overflow, pool_recycle, pool_pre_ping, kwargs),
    )


def create_sync_engine(
    url: str,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    max_overflow: int = DEFAULT_MAX_OVERFLOW,
    pool_recycle: int = DEFAULT_POOL_RECYCLE,
    pool_pre_ping: bool = True,
    **kwargs: Any,
) -> Engine:
    """Sync twin of :func:`create_engine` for Flask-era code such as KITT."""
    return sqlalchemy.create_engine(
        normalize_url(url),
        **_engine_kwargs(pool_size, max_overflow, pool_recycle, pool_pre_ping, kwargs),
    )


def _backoff(attempt: int, base: float, cap: float) -> float:
    return float(min(cap, base * (2**attempt)))


async def ping(
    engine: AsyncEngine | Engine,
    *,
    retries: int = DEFAULT_CONNECT_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    logger: logging.Logger | None = None,
) -> None:
    """``SELECT 1`` with exponential backoff; ``retries`` counts total attempts."""
    if isinstance(engine, Engine):
        await asyncio.to_thread(
            ping_sync,
            engine,
            retries=retries,
            base_delay=base_delay,
            max_delay=max_delay,
            logger=logger,
        )
        return
    log = logger or _log
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 - any driver error is retryable here
            if attempt + 1 >= attempts:
                raise DatabaseError(
                    f"database: ping failed after {attempts} attempt(s): {exc}"
                ) from exc
            delay = _backoff(attempt, base_delay, max_delay)
            log.warning(
                "database ping failed, retrying: attempt=%d delay=%.1fs error=%s",
                attempt + 1,
                delay,
                exc,
            )
            await asyncio.sleep(delay)


def ping_sync(
    engine: Engine,
    *,
    retries: int = DEFAULT_CONNECT_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    logger: logging.Logger | None = None,
) -> None:
    """Blocking twin of :func:`ping`."""
    log = logger or _log
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            if attempt + 1 >= attempts:
                raise DatabaseError(
                    f"database: ping failed after {attempts} attempt(s): {exc}"
                ) from exc
            delay = _backoff(attempt, base_delay, max_delay)
            log.warning(
                "database ping failed, retrying: attempt=%d delay=%.1fs error=%s",
                attempt + 1,
                delay,
                exc,
            )
            time.sleep(delay)


async def connect(
    url: str,
    *,
    connect_retries: int = DEFAULT_CONNECT_RETRIES,
    logger: logging.Logger | None = None,
    **engine_kwargs: Any,
) -> AsyncEngine:
    """Create an engine and ping it, disposing the engine if the ping fails."""
    engine = create_engine(url, **engine_kwargs)
    try:
        await ping(engine, retries=connect_retries, logger=logger)
    except DatabaseError:
        await engine.dispose()
        raise
    (logger or _log).info(
        "database engine ready: pool_size=%s",
        engine_kwargs.get("pool_size", DEFAULT_POOL_SIZE),
    )
    return engine


def connect_sync(
    url: str,
    *,
    connect_retries: int = DEFAULT_CONNECT_RETRIES,
    logger: logging.Logger | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Blocking twin of :func:`connect`."""
    engine = create_sync_engine(url, **engine_kwargs)
    try:
        ping_sync(engine, retries=connect_retries, logger=logger)
    except DatabaseError:
        engine.dispose()
        raise
    (logger or _log).info(
        "database engine ready: pool_size=%s",
        engine_kwargs.get("pool_size", DEFAULT_POOL_SIZE),
    )
    return engine
