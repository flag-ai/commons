"""Port of Go pool_test.go and migrate_test.go, plus the ping/retry fixes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool, QueuePool

from flag_commons.database import (
    MIGRATION_LOCK_KEY,
    DatabaseError,
    connect,
    connect_sync,
    create_engine,
    create_sync_engine,
    normalize_url,
    ping,
    ping_sync,
    run_migrations,
    run_migrations_async,
)
from flag_commons.database.engine import _backoff

pytestmark = pytest.mark.anyio

URL = "postgres://karr:pw@db.test:5432/karr"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        (
            "postgresql://u:p@h:5433/db?sslmode=require",
            "postgresql+psycopg://u:p@h:5433/db?sslmode=require",
        ),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
        ("POSTGRES://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_normalize_url(given: str, expected: str) -> None:
    assert normalize_url(given) == expected


@pytest.mark.parametrize(
    "bad", ["", "not://a-valid-url:::broken", "mysql://u@h/db", "sqlite:///x.db"]
)
def test_normalize_url_invalid(bad: str) -> None:
    # Go: TestNewPool_InvalidConnString
    with pytest.raises(DatabaseError, match="invalid connection string"):
        normalize_url(bad)


def test_create_engines_apply_options() -> None:
    # Go: TestPoolOptions
    a = create_engine(URL, pool_size=20, pool_recycle=60)
    assert isinstance(a, AsyncEngine)
    pool = cast(QueuePool, a.pool)
    assert pool.size() == 20
    assert pool._recycle == 60
    assert pool._pre_ping is True
    s = create_sync_engine(URL)
    assert isinstance(s, Engine)
    assert cast(QueuePool, s.pool).size() == 10
    assert s.dialect.driver == "psycopg"


def test_backoff_is_capped() -> None:
    assert [_backoff(i, 0.5, 5.0) for i in range(5)] == [0.5, 1.0, 2.0, 4.0, 5.0]


async def test_ping_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # FIX: Go had no ping and no retry.
    attempts: list[int] = []
    sleeps: list[float] = []

    class FakeConn:
        async def __aenter__(self) -> FakeConn:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("refused")
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def execute(self, _stmt: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("flag_commons.database.engine.asyncio.sleep", fake_sleep)
    with caplog.at_level(logging.WARNING):
        await ping(FakeEngine(), retries=5, base_delay=0.1)  # type: ignore[arg-type]
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]
    assert caplog.text.count("retrying") == 2


async def test_ping_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConn:
        async def __aenter__(self) -> FakeConn:
            raise ConnectionError("refused")

        async def __aexit__(self, *exc: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

    async def no_sleep(_d: float) -> None:
        return None

    monkeypatch.setattr("flag_commons.database.engine.asyncio.sleep", no_sleep)
    with pytest.raises(DatabaseError, match="after 3 attempt"):
        await ping(FakeEngine(), retries=3)  # type: ignore[arg-type]


def test_ping_sync_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    class FakeConn:
        def __enter__(self) -> FakeConn:
            attempts.append(1)
            if len(attempts) < 2:
                raise ConnectionError("refused")
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, _stmt: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

    monkeypatch.setattr("flag_commons.database.engine.time.sleep", lambda _d: None)
    ping_sync(FakeEngine(), retries=3)  # type: ignore[arg-type]
    assert len(attempts) == 2
    with pytest.raises(DatabaseError):
        attempts.clear()
        ping_sync(FakeEngine(), retries=1)  # type: ignore[arg-type]


async def test_ping_dispatches_sync_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr(
        "flag_commons.database.engine.ping_sync", lambda e, **kw: seen.append(e)
    )
    engine = create_sync_engine(URL)
    await ping(engine, retries=1)
    assert seen == [engine]


async def test_connect_disposes_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[bool] = []

    async def failing_ping(engine: AsyncEngine, **kw: object) -> None:
        raise DatabaseError("nope")

    async def fake_dispose(self: AsyncEngine) -> None:
        disposed.append(True)

    monkeypatch.setattr("flag_commons.database.engine.ping", failing_ping)
    monkeypatch.setattr(AsyncEngine, "dispose", fake_dispose)
    with pytest.raises(DatabaseError, match="nope"):
        await connect(URL, connect_retries=1)
    assert disposed == [True]


async def test_connect_returns_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_ping(engine: AsyncEngine, **kw: object) -> None:
        return None

    monkeypatch.setattr("flag_commons.database.engine.ping", ok_ping)
    engine = await connect(URL, pool_size=3)
    assert cast(QueuePool, engine.pool).size() == 3
    await engine.dispose()


def test_connect_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flag_commons.database.engine.ping_sync", lambda e, **kw: None)
    engine = connect_sync(URL)
    assert isinstance(engine, Engine)
    engine.dispose()

    def failing(e: Engine, **kw: object) -> None:
        raise DatabaseError("nope")

    monkeypatch.setattr("flag_commons.database.engine.ping_sync", failing)
    with pytest.raises(DatabaseError):
        connect_sync(URL)


def test_run_migrations_bad_source(tmp_path: Path) -> None:
    # Go: TestRunMigrations_BadSource
    with pytest.raises(DatabaseError, match="failed to create migrator"):
        run_migrations(tmp_path / "nonexistent", URL)


async def test_run_migrations_async_delegates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "flag_commons.database.migrations.run_migrations",
        lambda loc, url, *, logger=None, revision="head", lock_timeout=0: calls.append(
            (loc, url, revision, lock_timeout)
        ),
    )
    await run_migrations_async(tmp_path, URL, revision="base", lock_timeout=7)
    assert calls == [(tmp_path, URL, "base", 7)]


def test_create_engine_with_nullpool() -> None:
    engine = create_engine(URL, poolclass=NullPool)
    assert isinstance(engine.pool, NullPool)
    sync_engine = create_sync_engine(URL, poolclass=NullPool)
    assert isinstance(sync_engine.pool, NullPool)


def test_migration_lock_key_is_stable() -> None:
    # Every FLAG Python service must agree on this key.
    assert MIGRATION_LOCK_KEY == 38678575
