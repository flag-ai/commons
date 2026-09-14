"""The standard /health and /ready contract."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from flag_commons.health import Registry  # noqa: E402
from flag_commons.health.fastapi import health_router  # noqa: E402


class _Check:
    def __init__(self, name: str, ok: bool) -> None:
        self.name = name
        self.ok = ok

    def check(self) -> None:
        if not self.ok:
            raise RuntimeError("down")


def _client(*checks: _Check, critical: bool = True) -> TestClient:
    reg = Registry(dist_name="flag-commons")
    for c in checks:
        reg.register(c, critical=critical)
    app = FastAPI()
    app.include_router(health_router(reg))
    return TestClient(app)


def test_health_is_liveness() -> None:
    resp = _client(_Check("db", False)).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "(commit: " in body["version"]


def test_ready_healthy() -> None:
    resp = _client(_Check("db", True)).get("/ready")
    assert resp.status_code == 200
    assert resp.json()["healthy"] is True
    assert resp.json()["checks"][0]["name"] == "db"


def test_ready_unhealthy_is_503() -> None:
    resp = _client(_Check("db", False)).get("/ready")
    assert resp.status_code == 503
    assert resp.json()["healthy"] is False
    assert resp.json()["checks"][0]["error"] == "down"


def test_ready_non_critical_failure_is_200() -> None:
    resp = _client(_Check("agents", False), critical=False).get("/ready")
    assert resp.status_code == 200
    assert resp.json()["checks"][0]["critical"] is False


def test_dist_name_override() -> None:
    reg = Registry(dist_name="flag-commons")
    app = FastAPI()
    app.include_router(health_router(reg, dist_name="not-installed-dist"))
    assert TestClient(app).get("/health").json()["version"].startswith("dev (")
