"""Alembic ``upgrade head`` under a PostgreSQL advisory lock."""

from __future__ import annotations

import asyncio
import logging
import zlib
from os import PathLike
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

from flag_commons.database.engine import (
    DatabaseError,
    create_sync_engine,
    normalize_url,
)

# Same lock for every FLAG Python service migrating the same database. Note
# that golang-migrate derives its own key from the database name, so a Go
# service and a Python service migrating one database do not interlock; the
# rewrite starts KARR on a fresh database for that reason.
MIGRATION_LOCK_KEY = zlib.crc32(b"flag_commons.migrations")
DEFAULT_LOCK_TIMEOUT = 300.0  # seconds to wait for a peer's migration to finish

_log = logging.getLogger(__name__)


def run_migrations(
    script_location: str | PathLike[str],
    url: str,
    *,
    logger: logging.Logger | None = None,
    revision: str = "head",
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> None:
    """Run ``alembic upgrade <revision>`` for the scripts in ``script_location``.

    ``script_location`` is the Alembic script directory (the one holding
    ``env.py`` and ``versions/``), normally packaged inside the service. The
    upgrade runs while this process holds ``pg_advisory_lock``, so concurrent
    replicas serialize; waiting longer than ``lock_timeout`` seconds for the
    lock is an error rather than a silent hang. An up-to-date database is a
    successful no-op.
    """
    log = logger or _log
    location = Path(script_location)
    if not (location / "env.py").is_file():
        raise DatabaseError(
            f"database: failed to create migrator: no env.py in {location}"
        )

    cfg = Config()
    # configparser interpolation needs literal % doubled in both values.
    cfg.set_main_option("script_location", str(location).replace("%", "%%"))
    # Alembic's env.py builds its own engine from this value, so it must carry
    # the psycopg driver too.
    cfg.set_main_option("sqlalchemy.url", normalize_url(url).replace("%", "%%"))

    engine = create_sync_engine(url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as lock_conn:
            _acquire_lock(lock_conn, lock_timeout)
            log.info("running database migrations: source=%s", location)
            try:
                command.upgrade(cfg, revision)
            except Exception as exc:  # noqa: BLE001 - re-wrap every alembic/driver failure
                raise DatabaseError(f"database: migration failed: {exc}") from exc
            finally:
                _release_lock(lock_conn, log)
            log.info("migrations complete: revision=%s", revision)
    finally:
        engine.dispose()


def _acquire_lock(conn: Connection, lock_timeout: float) -> None:
    millis = max(1, int(lock_timeout * 1000))
    try:
        conn.execute(text(f"SET lock_timeout = {millis}"))
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(
            f"database: could not acquire migration lock within {lock_timeout:g}s: {exc}"
        ) from exc


def _release_lock(conn: Connection, log: logging.Logger) -> None:
    """Release the advisory lock without masking an in-flight migration error.

    The session ends when the engine is disposed, which also releases the
    lock, so a failure here is only logged.
    """
    try:
        released = conn.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
        ).scalar()
        if not released:
            log.warning("migration lock was not held at release time")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "could not release migration lock (session will release it): %s", exc
        )


async def run_migrations_async(
    script_location: str | PathLike[str],
    url: str,
    *,
    logger: logging.Logger | None = None,
    revision: str = "head",
    lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
) -> None:
    """Run :func:`run_migrations` in a worker thread."""
    await asyncio.to_thread(
        run_migrations,
        script_location,
        url,
        logger=logger,
        revision=revision,
        lock_timeout=lock_timeout,
    )
