"""ChainProvider: per-key resolution across providers (K-D20 fix)."""

from __future__ import annotations

import logging

import pytest

from flag_commons.secrets import (
    ChainProvider,
    EnvProvider,
    SecretNotFoundError,
    SecretsBackendError,
)


class _Static:
    def __init__(self, values: dict[str, str], *, fail: bool = False) -> None:
        self.values = values
        self.fail = fail
        self.calls: list[str] = []

    def get(self, key: str) -> str:
        self.calls.append(key)
        if self.fail:
            raise SecretsBackendError("backend down")
        if key not in self.values:
            raise SecretNotFoundError(key)
        return self.values[key]

    def get_or_default(self, key: str, default: str) -> str:
        try:
            return self.get(key)
        except SecretNotFoundError:
            return default


def test_first_provider_wins() -> None:
    a, b = _Static({"K": "a"}), _Static({"K": "b"})
    assert ChainProvider([a, b]).get("K") == "a"
    assert b.calls == []


def test_falls_through_on_not_found() -> None:
    a, b = _Static({}), _Static({"K": "b"})
    assert ChainProvider([a, b]).get("K") == "b"


def test_not_found_everywhere() -> None:
    with pytest.raises(SecretNotFoundError, match="any provider"):
        ChainProvider([_Static({}), _Static({})]).get("K")


def test_backend_error_is_surfaced_when_no_later_provider_has_key() -> None:
    with pytest.raises(SecretsBackendError, match="backend down"):
        ChainProvider([_Static({}), _Static({}, fail=True)]).get("K")


def test_later_provider_masks_backend_error() -> None:
    assert ChainProvider([_Static({}, fail=True), _Static({"K": "v"})]).get("K") == "v"


def test_get_or_default(caplog: pytest.LogCaptureFixture) -> None:
    chain = ChainProvider([_Static({}), _Static({}, fail=True)])
    assert ChainProvider([_Static({})]).get_or_default("K", "d") == "d"
    with caplog.at_level(logging.WARNING, logger="flag_commons.secrets.chain"):
        assert chain.get_or_default("K", "d") == "d"
    assert "backend down" in caplog.text


def test_env_wins_over_openbao_shaped_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://env")
    bao = _Static({"DATABASE_URL": "postgres://bao", "ONLY_IN_BAO": "x"})
    chain = ChainProvider([EnvProvider(), bao])
    assert chain.get("DATABASE_URL") == "postgres://env"
    assert chain.get("ONLY_IN_BAO") == "x"


def test_requires_at_least_one_provider() -> None:
    with pytest.raises(ValueError):
        ChainProvider([])
    assert "EnvProvider" in repr(ChainProvider([EnvProvider()]))
