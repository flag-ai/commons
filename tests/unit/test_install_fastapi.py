"""The install router: GET /install.sh and POST /agents/register."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from flag_commons.install import (  # noqa: E402
    InstallScriptError,
    RegisterRequest,
    RegisterResult,
)
from flag_commons.install.fastapi import TokenLookupError, install_router  # noqa: E402

TOKEN = "abc123"
PEER = "10.0.0.1"
PROXIES = ["10.0.0.0/8"]
FIXED_URL = "https://karr.test"


def _lookup(request: Request) -> str:
    token = request.query_params.get("token", "")
    if not token:
        raise TokenLookupError(400, "token is required")
    if token == "gone":
        raise TokenLookupError(410, "registration expired")
    if token == "unknown":
        raise TokenLookupError(404, "registration not found")
    if token == "weird":
        raise TokenLookupError(999, "internal detail")
    if token == "empty":
        return ""
    return token


async def _register(req: RegisterRequest, source_ip: str) -> RegisterResult:
    if req.registration_token == "bad":
        raise RuntimeError("no such token")
    return RegisterResult(agent_id=f"{source_ip}:{req.port}")


def _client(server_url: Any = FIXED_URL, **kw: Any) -> TestClient:
    app = FastAPI()
    app.include_router(
        install_router(
            token_lookup=_lookup, register=_register, server_url=server_url, **kw
        ),
        prefix="/api/v1",
    )
    return TestClient(app, base_url="http://karr.test", client=(PEER, 51000))


def test_install_script_ok() -> None:
    resp = _client().get(f"/api/v1/install.sh?token={TOKEN}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/x-shellscript")
    assert f"REGISTRATION_TOKEN={TOKEN}\n" in resp.text
    assert f"SERVER_URL={FIXED_URL}\n" in resp.text


@pytest.mark.parametrize(
    ("token", "status"),
    [
        ("", 400),
        ("unknown", 404),
        ("gone", 410),
        ("bad$token", 400),
        ("weird", 500),
        ("empty", 500),
    ],
)
def test_install_script_token_errors(token: str, status: int) -> None:
    # Go: TestScriptHandler_TokenError (+ K-D7 statuses, status allowlist)
    resp = _client().get(f"/api/v1/install.sh?token={token}")
    assert resp.status_code == status
    assert "error" in resp.json()
    if status == 500:
        assert "internal detail" not in resp.text


def test_async_token_lookup() -> None:
    async def lookup(request: Request) -> str:
        return TOKEN

    app = FastAPI()
    app.include_router(
        install_router(token_lookup=lookup, register=_register, server_url=FIXED_URL)
    )
    assert TestClient(app).get("/install.sh").status_code == 200


def test_host_header_is_never_trusted() -> None:
    # FIX: a forged Host must not make the agent phone home elsewhere.
    resp = _client(server_url=None).get(
        f"/api/v1/install.sh?token={TOKEN}", headers={"Host": "evil.example"}
    )
    assert resp.status_code == 500
    assert "evil.example" not in resp.text


def test_server_url_from_trusted_proxy_headers() -> None:
    # Go: TestScriptHandler_XForwardedProto / _XForwardedProtoInvalid (+ trusted-proxy FIX)
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "karr.public.example"}
    untrusted = _client(server_url=None).get(
        f"/api/v1/install.sh?token={TOKEN}", headers=headers
    )
    assert untrusted.status_code == 500  # peer is not a trusted proxy
    trusted = _client(server_url=None, trusted_proxies=PROXIES).get(
        f"/api/v1/install.sh?token={TOKEN}", headers=headers
    )
    assert "SERVER_URL=https://karr.public.example\n" in trusted.text
    bogus = _client(server_url=None, trusted_proxies=PROXIES).get(
        f"/api/v1/install.sh?token={TOKEN}",
        headers={
            "X-Forwarded-Proto": "gopher",
            "X-Forwarded-Host": "karr.public.example",
        },
    )
    assert bogus.status_code == 500
    injected = _client(server_url=None, trusted_proxies=PROXIES).get(
        f"/api/v1/install.sh?token={TOKEN}",
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil$(id).example"},
    )
    assert injected.status_code == 500


def test_server_url_callable_and_startup_validation() -> None:
    dyn = _client(server_url=lambda r: "https://dyn.example")
    assert (
        "SERVER_URL=https://dyn.example\n"
        in dyn.get(f"/api/v1/install.sh?token={TOKEN}").text
    )
    bad_dyn = _client(server_url=lambda r: "https://evil.example/$(id)")
    assert bad_dyn.get(f"/api/v1/install.sh?token={TOKEN}").status_code == 500
    with pytest.raises(InstallScriptError):
        _client(server_url="https://evil.example/$(id)")
    with pytest.raises(InstallScriptError):
        _client(repo="not a repo")
    with pytest.raises(InstallScriptError):
        _client(port=0)


def test_register_ok_and_statuses() -> None:
    c = _client()
    body = {"registration_token": "t", "port": 7777, "auth_token": "a"}
    resp = c.post("/api/v1/agents/register", json=body)
    assert resp.status_code == 201
    assert resp.json()["agent_id"] == f"{PEER}:7777"
    assert (
        c.post(
            "/api/v1/agents/register", json={**body, "registration_token": "bad"}
        ).status_code
        == 422
    )
    assert c.post("/api/v1/agents/register", content=b"{").status_code == 400
    assert c.get("/api/v1/agents/register").status_code == 405


def test_register_body_cap_is_enforced_before_buffering() -> None:
    c = _client()
    declared = c.post("/api/v1/agents/register", content=b"x" * 70_000)
    assert declared.status_code == 413
    # Chunked upload without Content-Length is cut off once the cap is exceeded.
    chunks = (b"x" * 1024 for _ in range(200))
    streamed = c.post("/api/v1/agents/register", content=chunks)
    assert streamed.status_code == 413


def test_register_source_ip_honours_trusted_xff_only() -> None:
    body = {"registration_token": "t", "port": 7777, "auth_token": "a"}
    headers = {"X-Forwarded-For": "1.2.3.4, 203.0.113.9"}
    untrusted = (
        _client().post("/api/v1/agents/register", json=body, headers=headers).json()
    )
    assert untrusted["agent_id"] == f"{PEER}:7777"
    trusted = (
        _client(trusted_proxies=PROXIES)
        .post("/api/v1/agents/register", json=body, headers=headers)
        .json()
    )
    assert (
        trusted["agent_id"] == "203.0.113.9:7777"
    )  # rightmost untrusted hop, not the client-supplied 1.2.3.4
