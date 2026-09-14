"""Port of Go env_test.go."""

from __future__ import annotations

import pytest

from flag_commons.secrets import EnvProvider, SecretNotFoundError, SecretsProvider


def test_env_provider_satisfies_protocol() -> None:
    assert isinstance(EnvProvider(), SecretsProvider)


def test_get_existing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestEnvProvider_Get / existing variable
    monkeypatch.setenv("FLAG_TEST_SECRET", "hunter2")
    assert EnvProvider().get("FLAG_TEST_SECRET") == "hunter2"


def test_get_missing_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestEnvProvider_Get / missing variable
    monkeypatch.delenv("FLAG_TEST_DEFINITELY_NOT_SET_12345", raising=False)
    with pytest.raises(SecretNotFoundError, match="not set"):
        EnvProvider().get("FLAG_TEST_DEFINITELY_NOT_SET_12345")


def test_get_or_default_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestEnvProvider_GetOrDefault / existing variable
    monkeypatch.setenv("FLAG_TEST_DEFAULT", "real_value")
    assert EnvProvider().get_or_default("FLAG_TEST_DEFAULT", "fallback") == "real_value"


def test_get_or_default_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestEnvProvider_GetOrDefault / missing variable returns default
    monkeypatch.delenv("FLAG_TEST_DEFINITELY_NOT_SET_67890", raising=False)
    assert (
        EnvProvider().get_or_default("FLAG_TEST_DEFINITELY_NOT_SET_67890", "fallback")
        == "fallback"
    )


def test_set_but_empty_is_empty_not_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLAG_TEST_EMPTY", "")
    assert EnvProvider().get("FLAG_TEST_EMPTY") == ""
    assert EnvProvider().get_or_default("FLAG_TEST_EMPTY", "fallback") == ""
