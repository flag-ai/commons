"""Port of Go version_test.go."""

from __future__ import annotations

import pytest

from flag_commons import version


def test_info_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestInfo_Defaults
    monkeypatch.delenv(version.ENV_COMMIT, raising=False)
    monkeypatch.delenv(version.ENV_DATE, raising=False)
    text = version.info("definitely-not-an-installed-distribution")
    assert "dev" in text
    assert "unknown" in text
    assert text == "dev (commit: unknown, built: unknown)"


def test_info_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # Go: TestInfo_CustomValues
    monkeypatch.setenv(version.ENV_COMMIT, "abc123")
    monkeypatch.setenv(version.ENV_DATE, "2025-06-01")
    monkeypatch.setattr(version, "get_version", lambda _dist: "1.2.3")
    assert version.info("anything") == "1.2.3 (commit: abc123, built: 2025-06-01)"


def test_get_info_reads_installed_distribution() -> None:
    info = version.get_info("flag-commons")
    assert info.version not in ("", "dev")
    assert str(info).startswith(f"{info.version} (commit: ")


def test_empty_env_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(version.ENV_COMMIT, "")
    monkeypatch.setenv(version.ENV_DATE, "")
    info = version.get_info("flag-commons")
    assert info.commit == "unknown"
    assert info.date == "unknown"


def test_version_info_is_immutable() -> None:
    info = version.VersionInfo("1.0.0", "c", "d")
    with pytest.raises(AttributeError):
        info.version = "2.0.0"  # type: ignore[misc]
