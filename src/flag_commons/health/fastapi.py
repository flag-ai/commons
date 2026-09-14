"""FastAPI adapter for the standard FLAG health contract.

* ``GET /health`` is liveness: ``{"status": "ok", "version": "<info()>"}``,
  always 200.
* ``GET /ready`` returns the :class:`~flag_commons.health.Report` JSON,
  200 when healthy and 503 otherwise.

By default ``/ready`` carries each failing check's error text, as the Go
services did. Pass ``redact_errors=True`` to replace it with ``"check
failed"`` on the wire (the full text is still logged), for deployments where
``/ready`` is reachable by untrusted callers.

Requires the ``fastapi`` extra.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from flag_commons import version as flag_version
from flag_commons.health.registry import Registry

REDACTED_ERROR = "check failed"

_log = logging.getLogger(__name__)


def health_router(
    registry: Registry,
    dist_name: str | None = None,
    *,
    redact_errors: bool = False,
) -> APIRouter:
    """Build a router serving ``/health`` and ``/ready`` for ``registry``."""
    name = dist_name or registry.dist_name
    router = APIRouter(tags=["health"])

    @router.get("/health", summary="Liveness")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": flag_version.info(name)}

    @router.get("/ready", summary="Readiness report")
    async def ready() -> JSONResponse:
        report = await registry.run_all()
        body = report.to_dict()
        for status in report.checks:
            if status.error:
                _log.warning(
                    "readiness check failed: check=%s error=%s",
                    status.name,
                    status.error,
                )
        if redact_errors:
            for check in body["checks"]:
                if "error" in check:
                    check["error"] = REDACTED_ERROR
        return JSONResponse(body, status_code=200 if report.healthy else 503)

    return router
