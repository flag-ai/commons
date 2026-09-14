"""Port of Go openbao_test.go, using respx to mock httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
import respx

from flag_commons.secrets import (
    OpenBaoProvider,
    SecretNotFoundError,
    SecretsBackendError,
    SecretsError,
    parse_key,
)

ADDR = "http://bao.test:8200"


def _kv_response(data: dict[str, Any] | None) -> httpx.Response:
    return httpx.Response(200, json={"data": {"data": data or {}}})


def _bao(data: dict[str, Any] | None, token: str = "test-token") -> None:
    """Mock a KV v2 server that checks the token like the Go test server."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-Vault-Token") != "test-token":
            return httpx.Response(403, text="forbidden")
        return _kv_response(data)

    respx.route(host="bao.test").mock(side_effect=handler)


@respx.mock
def test_get_default_field() -> None:
    # Go: TestOpenBaoProvider_Get_DefaultField
    _bao({"value": "secret-password", "username": "admin"})
    assert (
        OpenBaoProvider(ADDR, "test-token").get("db/credentials") == "secret-password"
    )


@respx.mock
def test_get_explicit_field() -> None:
    # Go: TestOpenBaoProvider_Get_ExplicitField
    _bao({"value": "secret-password", "username": "admin"})
    assert OpenBaoProvider(ADDR, "test-token").get("db/credentials#username") == "admin"


@respx.mock
def test_get_missing_field() -> None:
    # Go: TestOpenBaoProvider_Get_MissingField
    _bao({"value": "secret-password"})
    with pytest.raises(SecretNotFoundError, match="not found"):
        OpenBaoProvider(ADDR, "test-token").get("db/credentials#nonexistent")


@respx.mock
def test_get_bad_token() -> None:
    # Go: TestOpenBaoProvider_Get_BadToken
    _bao(None)
    with pytest.raises(SecretsBackendError, match="403"):
        OpenBaoProvider(ADDR, "wrong-token").get("anything")


@respx.mock
def test_get_caching() -> None:
    # Go: TestOpenBaoProvider_Get_Caching
    route = respx.get(f"{ADDR}/v1/kv/data/test/path").mock(
        return_value=_kv_response({"value": "cached-secret"})
    )
    p = OpenBaoProvider(ADDR, "test-token")
    assert p.get("test/path") == "cached-secret"
    assert p.get("test/path") == "cached-secret"
    assert route.call_count == 1, "second call should use cache"


@respx.mock
def test_cache_disabled_with_zero_ttl() -> None:
    route = respx.get(f"{ADDR}/v1/kv/data/test/path").mock(
        return_value=_kv_response({"value": "v"})
    )
    p = OpenBaoProvider(ADDR, "test-token", cache_ttl=0)
    p.get("test/path")
    p.get("test/path")
    assert route.call_count == 2


@respx.mock
def test_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx.get(f"{ADDR}/v1/kv/data/test/path").mock(
        return_value=_kv_response({"value": "v"})
    )
    now = [1000.0]
    monkeypatch.setattr("flag_commons.secrets.openbao.time.monotonic", lambda: now[0])
    p = OpenBaoProvider(ADDR, "test-token", cache_ttl=60)
    p.get("test/path")
    now[0] += 30
    p.get("test/path")
    assert route.call_count == 1
    now[0] += 31
    p.get("test/path")
    assert route.call_count == 2


@respx.mock
def test_errors_are_not_cached() -> None:
    route = respx.get(f"{ADDR}/v1/kv/data/p").mock(
        side_effect=[httpx.Response(500, text="boom"), _kv_response({"value": "ok"})]
    )
    p = OpenBaoProvider(ADDR, "test-token")
    with pytest.raises(SecretsBackendError, match="500"):
        p.get("p")
    assert p.get("p") == "ok"
    assert route.call_count == 2


@respx.mock
def test_get_or_default_success() -> None:
    # Go: TestOpenBaoProvider_GetOrDefault_Success
    _bao({"value": "real"})
    assert (
        OpenBaoProvider(ADDR, "test-token").get_or_default("test/secret", "default")
        == "real"
    )


@respx.mock
def test_get_or_default_fallback_on_backend_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Go: TestOpenBaoProvider_GetOrDefault_Fallback (unreachable server)
    respx.get(f"{ADDR}/v1/kv/data/test/secret").mock(
        side_effect=httpx.ConnectError("refused")
    )
    p = OpenBaoProvider(ADDR, "token")
    with caplog.at_level(logging.WARNING, logger="flag_commons.secrets.openbao"):
        assert p.get_or_default("test/secret", "default") == "default"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@respx.mock
def test_get_or_default_fallback_on_not_found(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(f"{ADDR}/v1/kv/data/missing").mock(
        return_value=httpx.Response(404, json={"errors": []})
    )
    with caplog.at_level(logging.DEBUG, logger="flag_commons.secrets.openbao"):
        assert (
            OpenBaoProvider(ADDR, "token").get_or_default("missing", "default")
            == "default"
        )
    assert all(r.levelno < logging.WARNING for r in caplog.records)


@pytest.mark.parametrize(
    ("key", "message"),
    [("", "empty key"), ("#field", "empty path"), ("path#", "empty field")],
)
def test_get_rejects_malformed_keys(key: str, message: str) -> None:
    # Go: TestOpenBaoProvider_Get_EmptyKey / _EmptyPath / _EmptyField
    with pytest.raises(SecretsError, match=message):
        OpenBaoProvider("http://localhost:1", "token").get(key)


def test_parse_key() -> None:
    assert parse_key("db/creds") == ("db/creds", "value")
    assert parse_key("db/creds#password") == ("db/creds", "password")
    assert parse_key("a#b#c") == ("a", "b#c")


@respx.mock
def test_with_mount_and_slashes_preserved() -> None:
    # Go: TestOpenBaoProvider_WithMount (with the %2F FIX: slashes stay slashes)
    route = respx.get(f"{ADDR}/v1/secret/data/my/path").mock(
        return_value=_kv_response({"value": "ok"})
    )
    OpenBaoProvider(ADDR + "/", "token", mount="secret").get("my/path")
    assert route.called
    assert route.calls[0].request.url.path == "/v1/secret/data/my/path"


@respx.mock
def test_non_string_value_is_backend_error() -> None:
    respx.get(f"{ADDR}/v1/kv/data/p").mock(return_value=_kv_response({"value": 42}))
    with pytest.raises(SecretsBackendError, match="not a string"):
        OpenBaoProvider(ADDR, "token").get("p")


@respx.mock
def test_malformed_json_is_backend_error() -> None:
    respx.get(f"{ADDR}/v1/kv/data/p").mock(
        return_value=httpx.Response(200, text="not json")
    )
    with pytest.raises(SecretsBackendError, match="decode"):
        OpenBaoProvider(ADDR, "token").get("p")
    respx.get(f"{ADDR}/v1/kv/data/q").mock(
        return_value=httpx.Response(200, json={"data": {"data": []}})
    )
    with pytest.raises(SecretsBackendError, match="not an object"):
        OpenBaoProvider(ADDR, "token").get("q")


@respx.mock
def test_error_body_is_truncated() -> None:
    respx.get(f"{ADDR}/v1/kv/data/p").mock(
        return_value=httpx.Response(500, text="x" * 10000)
    )
    with pytest.raises(SecretsBackendError) as exc_info:
        OpenBaoProvider(ADDR, "token").get("p")
    assert len(str(exc_info.value)) < 5000


def test_repr_hides_token_and_close() -> None:
    p = OpenBaoProvider(ADDR, "s3cret")
    assert "s3cret" not in repr(p)
    p.close()


def test_sends_vault_token_header() -> None:
    with respx.mock:
        route = respx.get(f"{ADDR}/v1/kv/data/p").mock(
            return_value=_kv_response({"value": "v"})
        )
        OpenBaoProvider(ADDR, "tok").get("p")
        assert route.calls[0].request.headers["X-Vault-Token"] == "tok"
        assert json.loads(route.calls[0].response.text)["data"]["data"]["value"] == "v"


@pytest.mark.parametrize(
    "key", ["../../sys/seal", "a/../../v1/sys/mounts", "/abs/path", "a//b", "./a"]
)
def test_parse_key_rejects_traversal(key: str) -> None:
    # FIX: slashes are real path separators now, so dot segments must be refused.
    with pytest.raises(SecretsError, match="path"):
        parse_key(key)


def test_parse_key_allows_nested_paths() -> None:
    assert parse_key("infra/karr/db#password") == ("infra/karr/db", "password")


def test_context_manager_closes_client() -> None:
    client = httpx.Client()
    with OpenBaoProvider(ADDR, "t", client=client) as p:
        assert p.addr == ADDR
    assert client.is_closed


def test_default_client_does_not_follow_redirects() -> None:
    with respx.mock:
        respx.get(f"{ADDR}/v1/kv/data/p").mock(
            return_value=httpx.Response(
                302, headers={"Location": "http://evil.test/steal"}
            )
        )
        with pytest.raises(SecretsBackendError, match="302"):
            OpenBaoProvider(ADDR, "tok").get("p")
