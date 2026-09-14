"""Health check registry and the standard FLAG HTTP health contract.

* :class:`Checker` is anything with a ``name`` and a ``check()`` method.
  ``check()`` may be sync or async and raises on failure; sync checks run in
  a worker thread.
* :class:`Registry` runs every registered check concurrently and produces a
  :class:`Report` whose JSON is byte-compatible with the Go library.
* :func:`flag_commons.health.fastapi.health_router` serves ``/health``
  (liveness) and ``/ready`` (the report) for FastAPI services.

Differences from Go, on purpose: a per-check timeout (default 5 s),
exceptions are captured as failed checks instead of crashing, duplicate
checker names are rejected, and checks can be registered as non-critical so
their failure is reported without flipping ``healthy``.
"""

from flag_commons.health.checkers import DatabaseChecker, HttpChecker
from flag_commons.health.registry import (
    DEFAULT_CHECK_TIMEOUT,
    Checker,
    Registry,
    Report,
    Status,
)

__all__ = [
    "DEFAULT_CHECK_TIMEOUT",
    "Checker",
    "DatabaseChecker",
    "HttpChecker",
    "Registry",
    "Report",
    "Status",
]
