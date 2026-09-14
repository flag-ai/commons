"""Checker protocol, report types and the registry."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from flag_commons import version as flag_version

DEFAULT_CHECK_TIMEOUT = 5.0


@runtime_checkable
class Checker(Protocol):
    """A health check for one dependency.

    ``check()`` returns normally when healthy and raises when not. It may be a
    coroutine function; plain functions are run in a worker thread.
    """

    @property
    def name(self) -> str: ...

    def check(self) -> None | Awaitable[None]: ...


@dataclass(frozen=True)
class Status:
    """Result of one check. ``to_dict()`` matches the Go JSON field for field."""

    name: str
    healthy: bool
    latency_ms: int
    error: str | None = None
    critical: bool = True

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "healthy": self.healthy}
        if self.error is not None:
            out["error"] = self.error
        out["latency_ms"] = self.latency_ms
        if not self.critical:
            # Additive: only present when it changes the meaning of "healthy".
            out["critical"] = False
        return out


@dataclass(frozen=True)
class Report:
    """Aggregate result. Empty registries report healthy, like Go."""

    healthy: bool
    version: str
    checks: list[Status] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "version": self.version,
            "checks": [s.to_dict() for s in self.checks],
        }


@dataclass(frozen=True)
class _Entry:
    checker: Checker
    critical: bool


class Registry:
    """Holds checkers and runs them concurrently, keeping registration order."""

    def __init__(
        self, *, dist_name: str, timeout: float = DEFAULT_CHECK_TIMEOUT
    ) -> None:
        self.dist_name = dist_name
        self.timeout = timeout
        self._lock = threading.Lock()
        self._entries: list[_Entry] = []

    def register(self, checker: Checker, *, critical: bool = True) -> None:
        """Add a checker. Names must be unique."""
        with self._lock:
            if any(e.checker.name == checker.name for e in self._entries):
                raise ValueError(f"health: checker {checker.name!r} already registered")
            self._entries.append(_Entry(checker, critical))

    def names(self) -> list[str]:
        with self._lock:
            return [e.checker.name for e in self._entries]

    def _snapshot(self) -> list[_Entry]:
        with self._lock:
            return list(self._entries)

    def _new_report(self) -> Report:
        return Report(healthy=True, version=flag_version.info(self.dist_name))

    async def run_all(self) -> Report:
        """Run every check concurrently and return the report."""
        entries = self._snapshot()
        if not entries:
            return self._new_report()
        statuses = await asyncio.gather(*(self._run_one(e) for e in entries))
        healthy = all(s.healthy or not s.critical for s in statuses)
        return Report(
            healthy=healthy, version=self._new_report().version, checks=list(statuses)
        )

    def run_all_sync(self) -> Report:
        """Blocking twin of :meth:`run_all` for Flask and scripts."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_all())
        raise RuntimeError(
            "health: run_all_sync() called inside a running event loop; use run_all()"
        )

    async def _run_one(self, entry: _Entry) -> Status:
        start = time.monotonic()
        error: str | None = None
        try:
            await asyncio.wait_for(_invoke(entry.checker), timeout=self.timeout)
        except asyncio.TimeoutError:
            error = f"health: {entry.checker.name} timed out after {self.timeout:g}s"
        except Exception as exc:  # noqa: BLE001 - a failing check must never crash the report
            error = str(exc) or exc.__class__.__name__
        latency_ms = int((time.monotonic() - start) * 1000)
        return Status(
            name=entry.checker.name,
            healthy=error is None,
            latency_ms=latency_ms,
            error=error,
            critical=entry.critical,
        )


async def _invoke(checker: Checker) -> None:
    result = (
        await asyncio.to_thread(checker.check)
        if not _is_async(checker)
        else checker.check()
    )
    if inspect.isawaitable(result):
        await result


def _is_async(checker: Checker) -> bool:
    return inspect.iscoroutinefunction(checker.check)
