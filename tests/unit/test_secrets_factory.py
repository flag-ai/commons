"""Port of Go factory_test.go plus provider_from_env."""

from __future__ import annotations

import pytest

from flag_commons.secrets import (
    ChainProvider,
    EnvProvider,
    OpenBaoProvider,
    SecretsError,
    new_provider,
    provider_from_env,
)


def test_new_provider_env() -> None:
    # Go: TestNewProvider_Env
    assert isinstance(new_provider("env"), EnvProvider)


def test_new_provider_openbao_missing_addr(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestNewProvider_OpenBao / missing addr
    monkeypatch.delenv("OPENBAO_ADDR", raising=False)
    monkeypatch.delenv("OPENBAO_TOKEN", raising=False)
    with pytest.raises(SecretsError, match="OPENBAO_ADDR"):
        new_provider("openbao")


def test_new_provider_openbao_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestNewProvider_OpenBao / missing token
    monkeypatch.setenv("OPENBAO_ADDR", "http://localhost:8200")
    monkeypatch.delenv("OPENBAO_TOKEN", raising=False)
    with pytest.raises(SecretsError, match="OPENBAO_TOKEN"):
        new_provider("openbao")


def test_new_provider_openbao_success(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestNewProvider_OpenBao / success
    monkeypatch.setenv("OPENBAO_ADDR", "http://localhost:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "test-token")
    assert isinstance(new_provider("openbao"), OpenBaoProvider)


def test_new_provider_unknown() -> None:
    # Go: TestNewProvider_Unknown
    with pytest.raises(SecretsError, match="unknown provider"):
        new_provider("bogus")


def test_provider_from_env_without_openbao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBAO_ADDR", raising=False)
    monkeypatch.delenv("OPENBAO_TOKEN", raising=False)
    assert isinstance(provider_from_env(), EnvProvider)


def test_provider_from_env_with_partial_openbao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENBAO_ADDR", "http://localhost:8200")
    monkeypatch.delenv("OPENBAO_TOKEN", raising=False)
    assert isinstance(provider_from_env(), EnvProvider)


def test_provider_from_env_with_openbao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBAO_ADDR", "http://localhost:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "test-token")
    provider = provider_from_env()
    assert isinstance(provider, ChainProvider)
    assert isinstance(provider.providers[0], EnvProvider)
    assert isinstance(provider.providers[1], OpenBaoProvider)
