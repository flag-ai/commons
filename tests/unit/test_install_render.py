"""Port of Go install_test.go (script half) plus the shell-quoting fixes."""

from __future__ import annotations

import pytest

from flag_commons.install import (
    InstallScriptError,
    install_command,
    render_install_script,
    validate_server_url,
    validate_token,
)

TOKEN = "abc123DEF456"


def test_renders_template() -> None:
    # Go: TestScriptHandler_RendersTemplate
    script = render_install_script(
        TOKEN, "https://karr.example.com", repo="acme/bonnie", port=9999
    )
    assert script.startswith("#!/usr/bin/env bash")
    assert "REPO=acme/bonnie\n" in script
    assert "SERVER_URL=https://karr.example.com\n" in script
    assert f"REGISTRATION_TOKEN={TOKEN}\n" in script
    assert "PORT=9999\n" in script
    assert "{{." not in script


def test_defaults() -> None:
    # Go: TestScriptHandler_Defaults
    script = render_install_script(TOKEN, "http://karr.internal:8080")
    assert "REPO=flag-ai/bonnie\n" in script
    assert "PORT=7777\n" in script


def test_systemd_unit_has_state_directory() -> None:
    # FIX: BONNIE 0.2.x needs /var/lib/bonnie under ProtectSystem=strict.
    script = render_install_script(TOKEN, "https://karr.example.com")
    assert "StateDirectory=bonnie" in script
    assert "ReadWritePaths=/var/run/docker.sock /var/lib/bonnie" in script
    assert "ProtectSystem=strict" in script


@pytest.mark.parametrize("token", ["", "abc$(rm -rf /)", "tok en", "a;b", "é"])
def test_token_with_shell_metachars_rejected(token: str) -> None:
    # Go: TestScriptHandler_TokenWithShellMetachars
    with pytest.raises(InstallScriptError, match="token"):
        render_install_script(token, "https://karr.example.com")
    with pytest.raises(InstallScriptError):
        validate_token(token)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "karr.example.com",
        "ftp://karr.example.com",
        "https://",
        "https://karr.example.com/$(id)",
        "https://karr.example.com/`id`",
        "https://karr.example.com/a b",
        "https://karr.example.com/?x=1",
        "https://karr.example.com/#frag",
        "https://karr.example.com/;ls",
        "https://karr.example.com/'",
    ],
)
def test_server_url_injection_rejected(url: str) -> None:
    # FIX: Go interpolated the Host header unquoted into the script.
    with pytest.raises(InstallScriptError, match="server_url"):
        render_install_script(TOKEN, url)


def test_server_url_normalised() -> None:
    assert (
        validate_server_url("  https://karr.example.com/ ")
        == "https://karr.example.com"
    )
    assert (
        validate_server_url("https://karr.example.com/base/")
        == "https://karr.example.com/base"
    )


@pytest.mark.parametrize("repo", ["", "bonnie", "a/b/c", "a/b$(x)", "../x"])
def test_repo_validation(repo: str) -> None:
    with pytest.raises(InstallScriptError, match="repo"):
        render_install_script(TOKEN, "https://karr.example.com", repo=repo)


@pytest.mark.parametrize("port", [0, 65536, -1, True])
def test_port_validation(port: int) -> None:
    with pytest.raises(InstallScriptError, match="port"):
        render_install_script(TOKEN, "https://karr.example.com", port=port)


def test_values_are_shell_quoted_when_needed() -> None:
    script = render_install_script(
        TOKEN, "https://karr.example.com", repo="my-org/my.repo"
    )
    assert "REPO=my-org/my.repo\n" in script
    # A value that needs quoting gets single quotes (shlex), never bare.
    script = render_install_script(TOKEN, "https://karr.example.com:8443")
    assert "SERVER_URL=https://karr.example.com:8443\n" in script


def test_install_command() -> None:
    # FIX: bash -s -- so --address passes through the pipe.
    cmd = install_command("https://karr.example.com", TOKEN)
    assert (
        cmd
        == f"curl -fsSL 'https://karr.example.com/api/v1/install.sh?token={TOKEN}' | sudo bash -s --"
    )
    cmd = install_command("https://karr.example.com", TOKEN, address="192.168.1.50")
    assert cmd.endswith("| sudo bash -s -- --address 192.168.1.50")
    with pytest.raises(InstallScriptError, match="address"):
        install_command("https://karr.example.com", TOKEN, address="1.2.3.4; rm -rf /")
