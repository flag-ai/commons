"""Live-PostgreSQL tests for the database package and DatabaseChecker."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from flag_commons.database import (
    DatabaseError,
    connect,
    connect_sync,
    create_sync_engine,
    run_migrations,
    run_migrations_async,
)
from flag_commons.health import DatabaseChecker, Registry

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_connect_and_ping(database_url: str) -> None:
    # Go: TestNewPool_Integration
    engine = await connect(database_url, pool_size=5)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar() == 1
    finally:
        await engine.dispose()


def test_connect_sync_and_ping(database_url: str) -> None:
    engine = connect_sync(database_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


async def test_bad_credentials_fail_at_connect(database_url: str) -> None:
    # FIX: Go had no startup ping, so bad credentials surfaced on the first query.
    bad = _with_user(database_url, "nobody", "wrong")
    with pytest.raises(DatabaseError, match="ping failed"):
        await connect(bad, connect_retries=2)


def _with_user(url: str, user: str, password: str) -> str:
    from sqlalchemy.engine import make_url

    return (
        make_url(url)
        .set(username=user, password=password)
        .render_as_string(hide_password=False)
    )


async def test_database_checker_against_live_db(database_url: str) -> None:
    engine = await connect(database_url)
    try:
        reg = Registry(dist_name="flag-commons")
        reg.register(DatabaseChecker(engine))
        report = await reg.run_all()
        assert report.healthy
        assert report.checks[0].name == "database"
    finally:
        await engine.dispose()


def test_migrations_apply_and_are_idempotent(
    database_url: str, alembic_scripts: Path
) -> None:
    engine = create_sync_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS flag_commons_it"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        run_migrations(alembic_scripts, database_url)
        run_migrations(alembic_scripts, database_url)  # no change is success
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == "0001"
            )
            conn.execute(text("SELECT id, name FROM flag_commons_it"))
            # The advisory lock was released.
            assert conn.execute(text("SELECT pg_try_advisory_lock(1)")).scalar() is True
            conn.execute(text("SELECT pg_advisory_unlock(1)"))
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS flag_commons_it"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


async def test_migrations_async_and_concurrent(
    database_url: str, alembic_scripts: Path
) -> None:
    engine = create_sync_engine(database_url)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            run_migrations(alembic_scripts, database_url)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS flag_commons_it"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        await run_migrations_async(alembic_scripts, database_url)
        for t in threads:
            t.join()
        assert errors == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS flag_commons_it"))
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()
