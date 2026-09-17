"""Port of Go registry_test.go, database_test.go and http_test.go, plus fixes."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest
import respx

from flag_commons.health import (
    Checker,
    DatabaseChecker,
    HttpChecker,
    Registry,
    Report,
    Status,
)

pytestmark = pytest.mark.anyio


class _Sync:
    def __init__(self, name: str, error: str | None = None) -> None:
        self.name = name
        self.error = error

    def check(self) -> None:
        if self.error:
            raise RuntimeError(self.error)


class _Async:
    def __init__(self, name: str, error: str | None = None, delay: float = 0) -> None:
        self.name = name
        self.error = error
        self.delay = delay

    async def check(self) -> None:
        await asyncio.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)


def _registry(**kw: float) -> Registry:
    return Registry(dist_name="flag-commons", **kw)


async def test_registry_empty() -> None:
    # Go: TestRegistry_Empty
    report = await _registry().run_all()
    assert report.healthy is True
    assert report.checks == []
    assert "(commit: " in report.version


async def test_registry_all_healthy() -> None:
    # Go: TestRegistry_AllHealthy
    reg = _registry()
    reg.register(_Sync("db"))
    reg.register(_Async("cache"))
    report = await reg.run_all()
    assert report.healthy
    assert [s.name for s in report.checks] == ["db", "cache"]
    assert all(s.healthy and s.error is None for s in report.checks)


async def test_registry_one_unhealthy() -> None:
    # Go: TestRegistry_OneUnhealthy
    reg = _registry()
    reg.register(_Sync("db"))
    reg.register(_Sync("cache", error="connection refused"))
    report = await reg.run_all()
    assert report.healthy is False
    unhealthy = [s for s in report.checks if not s.healthy]
    assert len(unhealthy) == 1
    assert "connection refused" in (unhealthy[0].error or "")


async def test_registry_concurrent_register() -> None:
    # Go: TestRegistry_ConcurrentRegister
    reg = _registry()

    def add() -> None:
        for i in range(100):
            reg.register(_Sync(f"concurrent-{i}"))

    t = threading.Thread(target=add)
    t.start()
    for _ in range(10):
        await reg.run_all()
    t.join()
    assert len(reg.names()) == 100


async def test_checks_run_concurrently_and_keep_order() -> None:
    reg = _registry()
    reg.register(_Async("slow", delay=0.2))
    reg.register(_Async("fast"))
    start = time.monotonic()
    report = await reg.run_all()
    assert time.monotonic() - start < 0.4
    assert [s.name for s in report.checks] == ["slow", "fast"]
    assert report.checks[0].latency_ms >= 150


async def test_per_check_timeout() -> None:
    # FIX: Go had no per-check timeout.
    reg = _registry(timeout=0.05)
    reg.register(_Async("hang", delay=5))
    report = await reg.run_all()
    assert not report.healthy
    assert "timed out" in (report.checks[0].error or "")


async def test_exception_is_captured_not_raised() -> None:
    # FIX: a panicking checker crashed the Go process.
    class Boom:
        name = "boom"

        def check(self) -> None:
            raise ValueError

    reg = _registry()
    reg.register(Boom())
    report = await reg.run_all()
    assert report.checks[0].error == "ValueError"


def test_duplicate_names_rejected() -> None:
    reg = _registry()
    reg.register(_Sync("db"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_Sync("db"))


async def test_non_critical_failure_keeps_healthy() -> None:
    # FIX: used by KARR so "no BONNIE agents yet" does not 503 /ready forever.
    reg = _registry()
    reg.register(_Sync("db"))
    reg.register(_Sync("bonnie-agents", error="no agents registered"), critical=False)
    report = await reg.run_all()
    assert report.healthy is True
    data = report.to_dict()
    assert data["checks"][1] == {
        "name": "bonnie-agents",
        "healthy": False,
        "error": "no agents registered",
        "latency_ms": data["checks"][1]["latency_ms"],
        "critical": False,
    }
    assert "critical" not in data["checks"][0]


def test_report_json_matches_go_shape() -> None:
    report = Report(
        healthy=False,
        version="1.0.0 (commit: abc, built: today)",
        checks=[
            Status("db", True, 3, error=""),
            Status("cache", False, 12, error="refused"),
        ],
    )
    assert json.loads(json.dumps(report.to_dict())) == {
        "healthy": False,
        "version": "1.0.0 (commit: abc, built: today)",
        "checks": [
            {"name": "db", "healthy": True, "latency_ms": 3},
            {"name": "cache", "healthy": False, "error": "refused", "latency_ms": 12},
        ],
    }


def test_run_all_sync() -> None:
    reg = _registry()
    reg.register(_Sync("db"))
    reg.register(_Async("api"))
    assert reg.run_all_sync().healthy


def test_run_all_sync_returns_at_timeout_despite_hung_thread() -> None:
    # A stuck sync check must not hold up the Flask worker calling us.
    release = threading.Event()

    class Hang:
        name = "hang"

        def check(self) -> None:
            release.wait(5)

    reg = _registry(timeout=0.1)
    reg.register(Hang())
    start = time.monotonic()
    report = reg.run_all_sync()
    elapsed = time.monotonic() - start
    release.set()
    assert not report.healthy
    assert "timed out" in (report.checks[0].error or "")
    assert elapsed < 2


async def test_run_all_sync_inside_loop_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="running event loop"):
        _registry().run_all_sync()


def test_checker_protocol() -> None:
    assert isinstance(_Sync("x"), Checker)
    assert isinstance(HttpChecker("n", "http://x"), Checker)


def test_database_checker_name() -> None:
    # Go: TestDatabaseChecker_Name
    assert DatabaseChecker(None).name == "database"


async def test_database_checker_nil_engine() -> None:
    # Go: TestDatabaseChecker_NilPool
    with pytest.raises(RuntimeError, match="nil"):
        await DatabaseChecker(None).check()


async def test_database_checker_pings_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    async def fake_ping(engine: object, *, retries: int) -> None:
        calls.append((engine, retries))

    monkeypatch.setattr("flag_commons.database.engine.ping", fake_ping)
    sentinel = object()
    await DatabaseChecker(sentinel).check()  # type: ignore[arg-type]
    assert calls == [(sentinel, 1)]


@respx.mock
async def test_http_checker_healthy() -> None:
    # Go: TestHTTPChecker_Healthy
    respx.get("http://svc.test/health").mock(return_value=httpx.Response(200))
    c = HttpChecker("test-svc", "http://svc.test/health")
    assert c.name == "test-svc"
    await c.check()


@respx.mock
async def test_http_checker_unhealthy() -> None:
    # Go: TestHTTPChecker_Unhealthy
    respx.get("http://svc.test/health").mock(return_value=httpx.Response(503))
    with pytest.raises(RuntimeError, match="503"):
        await HttpChecker("test-svc", "http://svc.test/health").check()


@respx.mock
async def test_http_checker_connection_refused() -> None:
    # Go: TestHTTPChecker_ConnectionRefused
    respx.get("http://dead.test/").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="dead-svc"):
        await HttpChecker("dead-svc", "http://dead.test/").check()


@respx.mock
async def test_http_checker_injected_client() -> None:
    route = respx.get("http://svc.test/").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as client:
        await HttpChecker("svc", "http://svc.test/", client=client).check()
    assert route.called


@respx.mock
async def test_http_checker_follows_redirects_like_go() -> None:
    respx.get("http://svc.test/old").mock(
        return_value=httpx.Response(301, headers={"Location": "http://svc.test/new"})
    )
    respx.get("http://svc.test/new").mock(return_value=httpx.Response(200))
    await HttpChecker("svc", "http://svc.test/old").check()


def test_http_checker_repr_redacts_credentials_and_query() -> None:
    text = repr(HttpChecker("svc", "https://user:pw@svc.test/health?token=abc"))
    assert "pw" not in text and "token" not in text
    assert "https://svc.test/health" in text
    assert "invalid url" in repr(HttpChecker("svc", "not a url"))
