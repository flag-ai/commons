"""Agent registry: one client per BONNIE agent plus background health polls."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

from flag_commons.bonnie.client import BonnieClient
from flag_commons.bonnie.errors import BonnieUnauthorized

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_UNAUTHORIZED = "unauthorized"

DEFAULT_POLL_INTERVAL = 30.0
DEFAULT_RELOAD_INTERVAL = 60.0
DEFAULT_CONCURRENCY = 8

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Agent:
    """The shared agent record that flows through :class:`RegistryStore`."""

    id: str
    name: str
    url: str
    token: str = ""
    status: str = STATUS_OFFLINE
    last_seen_at: datetime | None = None
    last_checked_at: datetime | None = None


class RegistryStore(Protocol):
    """Persistence for agents; each service implements it over its own schema."""

    async def list(self) -> list[Agent]: ...

    async def update_status(
        self,
        agent_id: str,
        status: str,
        last_seen_at: datetime | None,
        last_checked_at: datetime,
    ) -> None: ...


class RegistryError(Exception):
    """Raised by :meth:`AgentRegistry.has_online_agent`."""


class NoAgentsRegistered(RegistryError):
    def __init__(self) -> None:
        super().__init__("bonnie: no agents registered")


class NoOnlineAgents(RegistryError):
    def __init__(self) -> None:
        super().__init__("bonnie: no online agents")


ClientFactory = Callable[[str, str], BonnieClient]


@dataclass
class _Entry:
    agent: Agent
    client: BonnieClient


class AgentRegistry:
    """Keeps a :class:`BonnieClient` per agent and polls their ``/health``.

    Differences from the Go registry, all deliberate:

    * the first poll runs immediately at :meth:`start` (Go waited a full
      interval);
    * agents are periodically reloaded from the store (Go never reloaded);
    * polls run concurrently, bounded by ``concurrency`` (Go polled serially);
    * ``last_seen_at`` moves only on success, ``last_checked_at`` on every
      probe;
    * a 401/403 sets ``unauthorized`` instead of ``offline``;
    * calling :meth:`start` twice is harmless.
    """

    def __init__(
        self,
        store: RegistryStore | None,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        reload_interval: float = DEFAULT_RELOAD_INTERVAL,
        concurrency: int = DEFAULT_CONCURRENCY,
        client_factory: ClientFactory | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self.poll_interval = poll_interval
        self.reload_interval = reload_interval
        self._semaphore_size = max(1, concurrency)
        self._factory: ClientFactory = client_factory or (
            lambda url, token: BonnieClient(url, token)
        )
        self._log = logger or _log
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Reload, poll once, then keep polling and reloading in the background."""
        if self._task is not None and not self._task.done():
            return
        try:
            await self.reload()
        except Exception as exc:  # noqa: BLE001
            self._log.warning("bonnie: registry initial reload failed: %s", exc)
        await self.poll()
        if self.poll_interval > 0:
            self._task = asyncio.create_task(self._loop(), name="bonnie-registry")

    async def stop(self) -> None:
        """Cancel the background loop and close every client."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        async with self._lock:
            entries = list(self._entries.values())
            self._entries = {}
        for entry in entries:
            await entry.client.aclose()

    async def _loop(self) -> None:
        since_reload = 0.0
        while True:
            await asyncio.sleep(self.poll_interval)
            since_reload += self.poll_interval
            if self.reload_interval > 0 and since_reload >= self.reload_interval:
                since_reload = 0.0
                try:
                    await self.reload()
                except Exception as exc:  # noqa: BLE001
                    self._log.warning("bonnie: registry reload failed: %s", exc)
            try:
                await self.poll()
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self._log.error("bonnie: registry poll failed: %s", exc)

    # --- membership -------------------------------------------------------

    async def reload(self) -> None:
        """Replace the in-memory set with the store's rows, reusing clients."""
        if self._store is None:
            return
        agents = await self._store.list()
        async with self._lock:
            stale: list[BonnieClient] = []
            next_entries: dict[str, _Entry] = {}
            for agent in agents:
                existing = self._entries.get(agent.id)
                if (
                    existing
                    and existing.agent.url == agent.url
                    and existing.agent.token == agent.token
                ):
                    next_entries[agent.id] = _Entry(agent, existing.client)
                else:
                    if existing:
                        stale.append(existing.client)
                    next_entries[agent.id] = _Entry(
                        agent, self._factory(agent.url, agent.token)
                    )
            for agent_id, entry in self._entries.items():
                if agent_id not in next_entries:
                    stale.append(entry.client)
            self._entries = next_entries
        for client in stale:
            await client.aclose()
        self._log.debug("bonnie: registry reloaded: count=%d", len(next_entries))

    async def upsert(self, agent: Agent) -> None:
        """Register or replace one agent immediately."""
        async with self._lock:
            existing = self._entries.get(agent.id)
            if (
                existing
                and existing.agent.url == agent.url
                and existing.agent.token == agent.token
            ):
                self._entries[agent.id] = _Entry(agent, existing.client)
                return
            self._entries[agent.id] = _Entry(
                agent, self._factory(agent.url, agent.token)
            )
        if existing:
            await existing.client.aclose()

    async def remove(self, agent_id: str) -> None:
        """Unregister an agent. Unknown ids are ignored."""
        async with self._lock:
            entry = self._entries.pop(agent_id, None)
        if entry:
            await entry.client.aclose()

    def get(self, agent_id: str) -> BonnieClient | None:
        entry = self._entries.get(agent_id)
        return entry.client if entry else None

    def all(self) -> dict[str, BonnieClient]:
        return {agent_id: e.client for agent_id, e in self._entries.items()}

    def agents(self) -> list[Agent]:
        return [e.agent for e in self._entries.values()]

    def has_online_agent(self) -> None:
        """Return normally when at least one agent is online, else raise."""
        if not self._entries:
            raise NoAgentsRegistered()
        if not any(e.agent.status == STATUS_ONLINE for e in self._entries.values()):
            raise NoOnlineAgents()

    # --- polling ----------------------------------------------------------

    async def poll(self) -> None:
        """Probe every agent's ``/health`` concurrently and persist the outcome."""
        entries = list(self._entries.values())
        if not entries:
            return
        semaphore = asyncio.Semaphore(self._semaphore_size)

        async def probe(entry: _Entry) -> None:
            async with semaphore:
                await self._probe(entry)

        await asyncio.gather(*(probe(e) for e in entries))

    async def _probe(self, entry: _Entry) -> None:
        now = datetime.now(timezone.utc)
        agent = entry.agent
        try:
            await entry.client.health()
            status = STATUS_ONLINE
        except BonnieUnauthorized as exc:
            status = STATUS_UNAUTHORIZED
            self._log.warning(
                "bonnie: agent rejected token: agent=%s error=%s", agent.name, exc
            )
        except Exception as exc:  # noqa: BLE001 - any failure is "offline"
            status = STATUS_OFFLINE
            self._log.debug(
                "bonnie: agent health check failed: agent=%s error=%s", agent.name, exc
            )

        last_seen = now if status == STATUS_ONLINE else agent.last_seen_at
        if self._store is not None:
            try:
                await self._store.update_status(agent.id, status, last_seen, now)
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    "bonnie: registry update status failed: agent=%s error=%s",
                    agent.name,
                    exc,
                )
        async with self._lock:
            current = self._entries.get(agent.id)
            if current is not None and current.client is entry.client:
                current.agent = replace(
                    current.agent,
                    status=status,
                    last_seen_at=last_seen,
                    last_checked_at=now,
                )


class BonnieAgentsChecker:
    """Health checker: passes when at least one agent is online.

    Register it as non-critical (``registry.register(checker, critical=False)``)
    so a control plane with no agents yet still reports ready.
    """

    name = "bonnie-agents"

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def check(self) -> None:
        self._registry.has_online_agent()
