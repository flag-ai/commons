"""The install router: GET /install.sh and POST /agents/register."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from flag_commons.install import RegisterRequest, RegisterResult  # noqa: E402
from flag_commons.install.fastapi import TokenLookupError, install_router  # noqa: E402

TOKEN = "abc123"


def _lookup(request: Request) -> str:
    token = request.query_params.get("token", "")
    if not token:
        raise TokenLookupError(400, "token is required")
    if token == "gone":
        raise TokenLookupError(410, "registration expired")
    if token == "unknown":
        raise TokenLookupError(404, "registration not found")
    return token


async def _register(req: RegisterRequest, source_ip: str) -> RegisterResult:
    if req.registration_token == "bad":
        raise RuntimeError("no such token")
    return RegisterResult(agent_id=f"{source_ip}:{req.port}")


PEER = "10.0.0.1"


def _client(**kw: Any) -> TestClient:
    app = FastAPI()
    app.include_router(
        install_router(token_lookup=_lookup, register=_register, **kw), prefix="/api/v1"
    )
    return TestClient(app, base_url="http://karr.test", client=(PEER, 51000))


def test_install_script_ok() -> None:
    resp = _client().get(f"/api/v1/install.sh?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/x-shellscript")
    assert f"REGISTRATION_TOKEN={TOKEN}\n" in resp.text
    assert (
        "SERVER_URL=http://karr.test\n" in resp.text
    )  # auto-detected from the request


@pytest.mark.parametrize(
    ("token", "status"),
    [("", 400), ("unknown", 404), ("gone", 410), ("bad$token", 400)],
)
def test_install_script_token_errors(token: str, status: int) -> None:
    # Go: TestScriptHandler_TokenError (+ K-D7 statuses)
    resp = _client().get(f"/api/v1/install.sh?token={token}")
    assert resp.status_code == status
    assert "error" in resp.json()


def test_async_token_lookup() -> None:
    async def lookup(request: Request) -> str:
        return TOKEN

    app = FastAPI()
    app.include_router(install_router(token_lookup=lookup, register=_register))
    assert TestClient(app).get("/install.sh").status_code == 200


def test_server_url_from_trusted_proxy_headers() -> None:
    # Go: TestScriptHandler_XForwardedProto / _XForwardedProtoInvalid (+ trusted-proxy FIX)
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "karr.public.example"}
    untrusted = _client().get(f"/api/v1/install.sh?token={TOKEN}", headers=headers)
    assert "SERVER_URL=http://karr.test\n" in untrusted.text
    trusted = _client(trusted_proxies=["10.0.0.0/8"]).get(
        f"/api/v1/install.sh?token={TOKEN}", headers=headers
    )
    assert "SERVER_URL=https://karr.public.example\n" in trusted.text
    bogus = _client(trusted_proxies=["10.0.0.0/8"]).get(
        f"/api/v1/install.sh?token={TOKEN}", headers={"X-Forwarded-Proto": "gopher"}
    )
    assert "SERVER_URL=http://karr.test\n" in bogus.text


def test_server_url_fixed_or_callable() -> None:
    assert (
        "SERVER_URL=https://fixed.example\n"
        in _client(server_url="https://fixed.example")
        .get(f"/api/v1/install.sh?token={TOKEN}")
        .text
    )
    assert (
        "SERVER_URL=https://dyn.example\n"
        in _client(server_url=lambda r: "https://dyn.example")
        .get(f"/api/v1/install.sh?token={TOKEN}")
        .text
    )
    resp = _client(server_url="https://evil.example/$(id)").get(
        f"/api/v1/install.sh?token={TOKEN}"
    )
    assert resp.status_code == 400


def test_bad_repo_is_a_server_error() -> None:
    resp = _client(repo="not a repo").get(f"/api/v1/install.sh?token={TOKEN}")
    assert resp.status_code == 500


def test_register_ok_and_statuses() -> None:
    c = _client()
    resp = c.post(
        "/api/v1/agents/register",
        json={"registration_token": "t", "port": 7777, "auth_token": "a"},
    )
    assert resp.status_code == 201
    assert resp.json()["agent_id"].endswith(":7777")
    assert (
        c.post(
            "/api/v1/agents/register",
            json={"registration_token": "bad", "port": 1, "auth_token": "a"},
        ).status_code
        == 422
    )
    assert c.post("/api/v1/agents/register", content=b"{").status_code == 400
    assert c.post("/api/v1/agents/register", content=b"x" * 70_000).status_code == 413
    assert c.get("/api/v1/agents/register").status_code == 405


def test_register_source_ip_honours_trusted_xff_only() -> None:
    body = {"registration_token": "t", "port": 7777, "auth_token": "a"}
    headers = {"X-Forwarded-For": "203.0.113.9"}
    untrusted = (
        _client().post("/api/v1/agents/register", json=body, headers=headers).json()
    )
    assert untrusted["agent_id"] == f"{PEER}:7777"
    trusted = (
        _client(trusted_proxies=["10.0.0.0/8"])
        .post("/api/v1/agents/register", json=body, headers=headers)
        .json()
    )
    assert trusted["agent_id"] == "203.0.113.9:7777"
