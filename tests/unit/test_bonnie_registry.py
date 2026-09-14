"""Port of Go registry_test.go plus the poll/reload fixes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from flag_commons.bonnie import (
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_UNAUTHORIZED,
    Agent,
    AgentRegistry,
    BonnieAgentsChecker,
    BonnieUnauthorized,
    BonnieUnavailable,
    HealthReport,
    NoAgentsRegistered,
    NoOnlineAgents,
)

pytestmark = pytest.mark.anyio


class FakeClient:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self.fail: Exception | None = None
        self.closed = False
        self.calls = 0

    async def health(self) -> HealthReport:
        self.calls += 1
        if self.fail:
            raise self.fail
        return HealthReport()

    async def aclose(self) -> None:
        self.closed = True


class FakeStore:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        self.agents = agents or []
        self.updates: list[tuple[str, str, datetime | None, datetime]] = []
        self.list_error: Exception | None = None
        self.update_error: Exception | None = None

    async def list(self) -> list[Agent]:
        if self.list_error:
            raise self.list_error
        return list(self.agents)

    async def update_status(
        self,
        agent_id: str,
        status: str,
        last_seen_at: datetime | None,
        last_checked_at: datetime,
    ) -> None:
        if self.update_error:
            raise self.update_error
        self.updates.append((agent_id, status, last_seen_at, last_checked_at))


def _agent(i: int, **kw: Any) -> Agent:
    return Agent(
        id=f"a{i}", name=f"agent-{i}", url=f"http://h{i}:7777", token=f"t{i}", **kw
    )


def _registry(
    store: FakeStore | None, **kw: float
) -> tuple[AgentRegistry, dict[str, Any]]:
    made: dict[str, Any] = {}

    def factory(url: str, token: str) -> FakeClient:
        c = FakeClient(url, token)
        made[url] = c
        return c

    return AgentRegistry(store, client_factory=factory, **kw), made  # type: ignore[arg-type]


async def test_reload_and_get() -> None:
    # Go: TestRegistry_ReloadAndGet, TestRegistry_Get_Missing, TestRegistry_All
    reg, made = _registry(FakeStore([_agent(1), _agent(2)]))
    await reg.reload()
    assert reg.get("a1") is made["http://h1:7777"]
    assert reg.get("missing") is None
    assert set(reg.all()) == {"a1", "a2"}
    assert {a.id for a in reg.agents()} == {"a1", "a2"}


async def test_upsert_and_remove() -> None:
    # Go: TestRegistry_Upsert, TestRegistry_Remove
    reg, made = _registry(None)
    await reg.upsert(_agent(1))
    assert reg.get("a1") is not None
    first = made["http://h1:7777"]
    await reg.upsert(_agent(1))  # same url/token: client reused
    assert id(reg.get("a1")) == id(first)
    await reg.upsert(Agent(id="a1", name="x", url="http://h1:7777", token="new"))
    assert first.closed  # the replaced client was closed
    assert id(reg.get("a1")) != id(first)
    await reg.remove("a1")
    await reg.remove("nope")
    assert reg.get("a1") is None


async def test_reload_preserves_existing_client_and_closes_stale() -> None:
    # Go: TestRegistry_ReloadPreservesExistingClient
    store = FakeStore([_agent(1), _agent(2)])
    reg, made = _registry(store)
    await reg.reload()
    c1, c2 = made["http://h1:7777"], made["http://h2:7777"]
    store.agents = [
        _agent(1),
        Agent(id="a2", name="agent-2", url="http://h2:7777", token="rotated"),
    ]
    await reg.reload()
    assert reg.get("a1") is c1
    assert reg.get("a2") is not c2 and c2.closed
    store.agents = [_agent(1)]
    await reg.reload()
    assert reg.get("a2") is None


async def test_nil_store_reload_noop() -> None:
    # Go: TestRegistry_NilStoreReloadNoop
    reg, _ = _registry(None)
    await reg.reload()
    assert reg.agents() == []


async def test_poll_online_offline_unauthorized() -> None:
    # Go: TestRegistry_Poll_OnlineAndOffline (+ unauthorized FIX, last_seen FIX)
    store = FakeStore([_agent(1), _agent(2), _agent(3)])
    reg, made = _registry(store)
    await reg.reload()
    made["http://h2:7777"].fail = BonnieUnavailable("health", "refused")
    made["http://h3:7777"].fail = BonnieUnauthorized(
        "health", 401, '{"error":"bad token"}'
    )
    await reg.poll()
    by_id = {a.id: a for a in reg.agents()}
    assert by_id["a1"].status == STATUS_ONLINE and by_id["a1"].last_seen_at is not None
    assert by_id["a2"].status == STATUS_OFFLINE and by_id["a2"].last_seen_at is None
    assert by_id["a3"].status == STATUS_UNAUTHORIZED
    assert all(a.last_checked_at is not None for a in by_id.values())
    assert {u[0]: u[1] for u in store.updates} == {
        "a1": STATUS_ONLINE,
        "a2": STATUS_OFFLINE,
        "a3": STATUS_UNAUTHORIZED,
    }
    # last_seen_at persists across a later failure
    made["http://h1:7777"].fail = RuntimeError("down")
    seen_before = by_id["a1"].last_seen_at
    await reg.poll()
    a1 = {a.id: a for a in reg.agents()}["a1"]
    assert a1.status == STATUS_OFFLINE and a1.last_seen_at == seen_before


async def test_poll_runs_concurrently_and_bounded() -> None:
    store = FakeStore([_agent(i) for i in range(6)])
    reg, made = _registry(store, concurrency=2)
    await reg.reload()
    active = 0
    peak = 0

    async def slow_health(self: FakeClient) -> HealthReport:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return HealthReport()

    for c in made.values():
        c.health = slow_health.__get__(c)
    await reg.poll()
    assert peak == 2


async def test_poll_store_error_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeStore([_agent(1)])
    store.update_error = RuntimeError("db down")
    reg, _ = _registry(store)
    await reg.reload()
    await reg.poll()
    assert "update status failed" in caplog.text
    assert reg.agents()[0].status == STATUS_ONLINE


async def test_start_polls_immediately_and_is_idempotent() -> None:
    # Go: TestRegistry_Start_RunsHealthLoop; FIX: immediate first poll, double start harmless
    store = FakeStore([_agent(1)])
    reg, made = _registry(store, poll_interval=0.01, reload_interval=0.02)
    await reg.start()
    assert made["http://h1:7777"].calls == 1
    task = reg._task
    await reg.start()
    assert reg._task is task
    store.agents = [_agent(1), _agent(2)]
    await asyncio.sleep(0.08)
    assert made["http://h1:7777"].calls >= 3
    assert reg.get("a2") is not None  # FIX: periodic reload picked up the new agent
    await reg.stop()
    assert reg._task is None and made["http://h1:7777"].closed
    assert reg.agents() == []


async def test_start_reload_error_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Go: TestRegistry_Start_ReloadError
    store = FakeStore()
    store.list_error = RuntimeError("db down")
    reg, _ = _registry(store, poll_interval=0)
    await reg.start()
    assert "initial reload failed" in caplog.text
    assert reg._task is None


async def test_has_online_agent() -> None:
    # Go: TestRegistry_HasOnlineAgent, TestRegistry_HasOnlineAgent_Empty
    reg, made = _registry(None)
    checker = BonnieAgentsChecker(reg)
    assert checker.name == "bonnie-agents"
    with pytest.raises(NoAgentsRegistered, match="no agents registered"):
        await checker.check()
    await reg.upsert(_agent(1))
    with pytest.raises(NoOnlineAgents, match="no online agents"):
        reg.has_online_agent()
    await reg.poll()
    reg.has_online_agent()


async def test_concurrent_access() -> None:
    # Go: TestRegistry_ConcurrentAccess
    store = FakeStore([_agent(i) for i in range(5)])
    reg, _ = _registry(store)
    await reg.reload()

    async def churn() -> None:
        for i in range(20):
            await reg.upsert(_agent(100 + i))
            await reg.remove(f"a{100 + i}")

    await asyncio.gather(churn(), reg.poll(), reg.reload(), churn())
    assert len(reg.agents()) == 5


def test_agent_defaults_and_repr_hides_token() -> None:
    a = Agent(id="x", name="n", url="u", token="s3cret")
    assert a.status == STATUS_OFFLINE and a.token == "s3cret"
    assert "s3cret" not in repr(a) and "s3cret" not in str(a)
    assert datetime.now(timezone.utc).tzinfo is timezone.utc


async def test_unhealthy_report_is_offline() -> None:
    reg, made = _registry(None)
    await reg.upsert(_agent(1))
    client = made["http://h1:7777"]

    async def unhealthy() -> HealthReport:
        return HealthReport(healthy=False)

    client.health = unhealthy
    await reg.poll()
    assert reg.agents()[0].status == STATUS_OFFLINE


async def test_concurrent_start_creates_one_loop() -> None:
    # FIX: two overlapping start() calls must not leak a second polling loop.
    class SlowStore(FakeStore):
        async def list(self) -> list[Agent]:
            await asyncio.sleep(0.01)
            return await super().list()

    reg, _ = _registry(SlowStore([_agent(1)]), poll_interval=0.01)
    await asyncio.gather(reg.start(), reg.start())
    tasks = [t for t in asyncio.all_tasks() if t.get_name() == "bonnie-registry"]
    assert len(tasks) == 1
    await reg.stop()
    await asyncio.sleep(0)
    assert not [
        t
        for t in asyncio.all_tasks()
        if t.get_name() == "bonnie-registry" and not t.done()
    ]


async def test_stop_propagates_caller_cancellation() -> None:
    reg, _ = _registry(FakeStore([_agent(1)]), poll_interval=0.01)
    await reg.start()

    async def slow_close() -> None:
        await asyncio.sleep(10)

    made["http://h1:7777"].aclose = slow_close
    stopper = asyncio.create_task(reg.stop())
    await asyncio.sleep(0.01)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper


async def test_loop_survives_poll_and_reload_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeStore([_agent(1)])
    reg, made = _registry(store, poll_interval=0.01, reload_interval=0.01)
    await reg.start()
    store.list_error = RuntimeError("db flake")
    store.update_error = RuntimeError("db flake")
    await asyncio.sleep(0.05)
    assert reg._task is not None and not reg._task.done()
    assert "reload failed" in caplog.text
    await reg.stop()


async def test_close_all_keeps_going_after_a_failure() -> None:
    reg, made = _registry(FakeStore([_agent(1), _agent(2)]))
    await reg.reload()

    async def boom() -> None:
        raise RuntimeError("close failed")

    made["http://h1:7777"].aclose = boom
    await reg.stop()
    assert made["http://h2:7777"].closed
