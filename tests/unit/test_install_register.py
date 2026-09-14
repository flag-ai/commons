"""Port of Go install_test.go (register half) plus the trusted-proxy fix."""

from __future__ import annotations

import json
import logging

import pytest

from flag_commons.install import (
    MAX_REGISTER_BODY,
    RegisterRequest,
    RegisterResult,
    RegistrationFailed,
    handle_register,
    is_trusted_proxy,
    parse_trusted_proxies,
    resolve_source_ip,
)

pytestmark = pytest.mark.anyio


async def _ok(req: RegisterRequest, source_ip: str) -> RegisterResult:
    return RegisterResult(agent_id=f"agent-for-{req.address or source_ip}:{req.port}")


def _body(**kw: object) -> bytes:
    payload: dict[str, object] = {
        "registration_token": "tok",
        "port": 7777,
        "auth_token": "auth",
    }
    payload.update(kw)
    return json.dumps({k: v for k, v in payload.items() if v is not ...}).encode()


async def test_register_success() -> None:
    # Go: TestRegisterHandler_Success
    status, body = await handle_register(_body(), "10.0.0.5", _ok)
    assert status == 201
    assert body == {
        "agent_id": "agent-for-10.0.0.5:7777",
        "message": "agent registered",
    }


async def test_register_with_address_override() -> None:
    # Go: TestRegisterHandler_WithAddressOverride
    status, body = await handle_register(_body(address="192.168.1.50"), "10.0.0.5", _ok)
    assert status == 201 and body["agent_id"] == "agent-for-192.168.1.50:7777"


@pytest.mark.parametrize(
    "body",
    [
        _body(registration_token=""),
        _body(auth_token=""),
        _body(port=...),
        _body(registration_token=...),
        _body(auth_token=...),
    ],
)
async def test_register_missing_fields(body: bytes) -> None:
    # Go: TestRegisterHandler_MissingFields
    status, payload = await handle_register(body, "1.1.1.1", _ok)
    assert status == 400
    assert payload["error"] == "registration_token, auth_token, and port are required"


@pytest.mark.parametrize("port", [0, 65536, -5])
async def test_register_invalid_port(port: int) -> None:
    # Go: TestRegisterHandler_InvalidPort
    status, payload = await handle_register(_body(port=port), "1.1.1.1", _ok)
    assert status == 400 and payload["error"] == "port must be between 1 and 65535"


async def test_register_invalid_json() -> None:
    # Go: TestRegisterHandler_InvalidJSON
    for body in (b"{not json", b"[]", b'"str"'):
        status, payload = await handle_register(body, "1.1.1.1", _ok)
        assert status == 400 and payload["error"] == "invalid JSON body"


async def test_register_field_errors_are_accurate() -> None:
    status, payload = await handle_register(_body(extra="x"), "1.1.1.1", _ok)
    assert status == 400 and payload["error"] == "unknown field(s): extra"
    status, payload = await handle_register(_body(address=5), "1.1.1.1", _ok)
    assert status == 400 and payload["error"] == "invalid field(s): address"


async def test_register_oversize_body() -> None:
    status, payload = await handle_register(
        b"x" * (MAX_REGISTER_BODY + 1), "1.1.1.1", _ok
    )
    assert status == 413 and "too large" in payload["error"]


async def test_register_rejected_by_callback(caplog: pytest.LogCaptureFixture) -> None:
    async def rejecting(req: RegisterRequest, source_ip: str) -> RegisterResult:
        raise RegistrationFailed("token expired")

    with caplog.at_level(logging.WARNING, logger="flag_commons.install.register"):
        status, payload = await handle_register(_body(), "1.1.1.1", rejecting)
    assert status == 422 and payload == {"error": "registration failed"}
    assert "token expired" in caplog.text and "Traceback" not in caplog.text


async def test_register_callback_bug_is_logged_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Go: TestRegisterHandler_CallbackError
    async def failing(req: RegisterRequest, source_ip: str) -> RegisterResult:
        raise TypeError("consumer bug")

    with caplog.at_level(logging.ERROR, logger="flag_commons.install.register"):
        status, payload = await handle_register(_body(), "1.1.1.1", failing)
    assert status == 422 and payload == {"error": "registration failed"}
    assert "consumer bug" in caplog.text and "Traceback" in caplog.text


def test_resolve_source_ip_trusted_proxy_only() -> None:
    # Go: TestRegisterHandler_XForwardedFor, TestRegisterHandler_RemoteAddrNoPort (+ FIX)
    xff = "203.0.113.9, 10.0.0.1"
    assert resolve_source_ip("10.0.0.1", xff, ["10.0.0.0/8"]) == "203.0.113.9"
    assert resolve_source_ip("10.0.0.1", xff, ["10.0.0.1"]) == "203.0.113.9"
    assert (
        resolve_source_ip("10.0.0.1", xff, []) == "10.0.0.1"
    )  # untrusted: header ignored
    assert resolve_source_ip("198.51.100.7", xff, ["10.0.0.0/8"]) == "198.51.100.7"
    assert resolve_source_ip("10.0.0.1", "", ["10.0.0.0/8"]) == "10.0.0.1"
    assert resolve_source_ip("10.0.0.1", " , ", ["10.0.0.0/8"]) == "10.0.0.1"
    assert resolve_source_ip("not-an-ip", xff, ["10.0.0.0/8"]) == "not-an-ip"


def test_resolve_source_ip_walks_from_the_right() -> None:
    # FIX: the leftmost entry is client-supplied with an appending proxy.
    proxies = ["10.0.0.0/8"]
    assert (
        resolve_source_ip("10.0.0.1", "1.2.3.4, 203.0.113.9", proxies) == "203.0.113.9"
    )
    assert (
        resolve_source_ip("10.0.0.1", "1.2.3.4, 203.0.113.9, 10.0.0.2", proxies)
        == "203.0.113.9"
    )
    assert (
        resolve_source_ip("10.0.0.1", "10.0.0.3", proxies) == "10.0.0.1"
    )  # only proxies listed
    assert resolve_source_ip("10.0.0.1", "not-an-ip\nFORGED", proxies) == "10.0.0.1"
    assert resolve_source_ip("10.0.0.1", "1.2.3.4, evil", proxies) == "10.0.0.1"


def test_trusted_proxy_helpers(caplog: pytest.LogCaptureFixture) -> None:
    assert parse_trusted_proxies(" 10.0.0.0/8, ,192.168.1.1 ") == [
        "10.0.0.0/8",
        "192.168.1.1",
    ]
    assert parse_trusted_proxies("") == []
    with pytest.raises(ValueError, match="10.0.0/8"):
        parse_trusted_proxies("10.0.0/8")
    assert is_trusted_proxy("10.1.2.3", ["10.0.0.0/8"])
    assert not is_trusted_proxy("11.1.2.3", ["10.0.0.0/8"])
    with caplog.at_level(logging.WARNING, logger="flag_commons.install.register"):
        assert not is_trusted_proxy("10.1.2.3", ["garbage"])
    assert "malformed trusted proxy" in caplog.text
