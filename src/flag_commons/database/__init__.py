"""PostgreSQL engines and Alembic migrations (extra ``postgres``).

* :func:`create_engine` / :func:`create_sync_engine` build SQLAlchemy 2
  engines on psycopg 3 with the Go pool defaults (10 connections, 30-minute
  recycle) plus ``pool_pre_ping``.
* :func:`connect` / :func:`connect_sync` build an engine **and ping it with
  exponential backoff**, so bad credentials fail at boot instead of on the
  first query.
* :func:`run_migrations` runs ``alembic upgrade head`` inside a
  ``pg_advisory_lock``, matching golang-migrate's locking. Migrations ship
  inside the service wheel; pass the packaged Alembic script directory.
"""

from flag_commons.database.engine import (
    DEFAULT_CONNECT_RETRIES,
    DEFAULT_MAX_OVERFLOW,
    DEFAULT_POOL_RECYCLE,
    DEFAULT_POOL_SIZE,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_MAX_DELAY,
    DatabaseError,
    connect,
    connect_sync,
    create_engine,
    create_sync_engine,
    normalize_url,
    ping,
    ping_sync,
)
from flag_commons.database.migrations import (
    DEFAULT_LOCK_TIMEOUT,
    MIGRATION_LOCK_KEY,
    run_migrations,
    run_migrations_async,
)

__all__ = [
    "DEFAULT_CONNECT_RETRIES",
    "DEFAULT_LOCK_TIMEOUT",
    "DEFAULT_MAX_OVERFLOW",
    "DEFAULT_POOL_RECYCLE",
    "DEFAULT_POOL_SIZE",
    "DEFAULT_RETRY_BASE_DELAY",
    "DEFAULT_RETRY_MAX_DELAY",
    "MIGRATION_LOCK_KEY",
    "DatabaseError",
    "connect",
    "connect_sync",
    "create_engine",
    "create_sync_engine",
    "normalize_url",
    "ping",
    "ping_sync",
    "run_migrations",
    "run_migrations_async",
]
