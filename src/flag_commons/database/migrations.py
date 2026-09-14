"""Alembic ``upgrade head`` under a PostgreSQL advisory lock."""

from __future__ import annotations

import asyncio
import logging
import zlib
from os import PathLike
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from flag_commons.database.engine import (
    DatabaseError,
    create_sync_engine,
    normalize_url,
)

# Same lock for every FLAG service migrating the same database.
MIGRATION_LOCK_KEY = zlib.crc32(b"flag_commons.migrations")

_log = logging.getLogger(__name__)


def run_migrations(
    script_location: str | PathLike[str],
    url: str,
    *,
    logger: logging.Logger | None = None,
    revision: str = "head",
) -> None:
    """Run ``alembic upgrade <revision>`` for the scripts in ``script_location``.

    ``script_location`` is the Alembic script directory (the one holding
    ``env.py`` and ``versions/``), normally packaged inside the service. The
    upgrade runs while this process holds ``pg_advisory_lock``, so concurrent
    replicas serialize. An up-to-date database is a successful no-op.
    """
    log = logger or _log
    location = Path(script_location)
    if not (location / "env.py").is_file():
        raise DatabaseError(
            f"database: failed to create migrator: no env.py in {location}"
        )

    cfg = Config()
    cfg.set_main_option("script_location", str(location))
    # Alembic's env.py builds its own engine from this value, so it must carry
    # the psycopg driver too, and configparser needs literal % doubled.
    cfg.set_main_option("sqlalchemy.url", normalize_url(url).replace("%", "%%"))

    engine = create_sync_engine(url, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as lock_conn:
            lock_conn.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            log.info("running database migrations: source=%s", location)
            try:
                command.upgrade(cfg, revision)
            except Exception as exc:  # noqa: BLE001 - re-wrap every alembic/driver failure
                raise DatabaseError(f"database: migration failed: {exc}") from exc
            finally:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY}
                )
            log.info("migrations complete: revision=%s", revision)
    finally:
        engine.dispose()


async def run_migrations_async(
    script_location: str | PathLike[str],
    url: str,
    *,
    logger: logging.Logger | None = None,
    revision: str = "head",
) -> None:
    """Run :func:`run_migrations` in a worker thread."""
    await asyncio.to_thread(
        run_migrations, script_location, url, logger=logger, revision=revision
    )
