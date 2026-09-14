"""FastAPI adapter for the standard FLAG health contract.

* ``GET /health`` is liveness: ``{"status": "ok", "version": "<info()>"}``,
  always 200.
* ``GET /ready`` returns the :class:`~flag_commons.health.Report` JSON,
  200 when healthy and 503 otherwise.

Requires the ``fastapi`` extra.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from flag_commons import version as flag_version
from flag_commons.health.registry import Registry


def health_router(registry: Registry, dist_name: str | None = None) -> APIRouter:
    """Build a router serving ``/health`` and ``/ready`` for ``registry``."""
    name = dist_name or registry.dist_name
    router = APIRouter(tags=["health"])

    @router.get("/health", summary="Liveness")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": flag_version.info(name)}

    @router.get("/ready", summary="Readiness report")
    async def ready() -> JSONResponse:
        report = await registry.run_all()
        return JSONResponse(
            report.to_dict(), status_code=200 if report.healthy else 503
        )

    return router
