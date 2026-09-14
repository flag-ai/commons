"""Port of Go install_test.go (script half) plus the shell-quoting fixes."""

from __future__ import annotations

import pytest

from flag_commons.install import (
    InstallScriptError,
    install_command,
    render_install_script,
    validate_repo,
    validate_server_url,
    validate_token,
)

TOKEN = "abc123DEF456"
URL = "https://karr.example.com"


def test_renders_template() -> None:
    # Go: TestScriptHandler_RendersTemplate
    script = render_install_script(TOKEN, URL, repo="acme/bonnie", port=9999)
    assert script.startswith("#!/usr/bin/env bash")
    assert "REPO=acme/bonnie\n" in script
    assert f"SERVER_URL={URL}\n" in script
    assert f"REGISTRATION_TOKEN={TOKEN}\n" in script
    assert "PORT=9999\n" in script
    assert "{{." not in script


def test_defaults() -> None:
    # Go: TestScriptHandler_Defaults
    script = render_install_script(
        TOKEN, "http://karr.internal:8080", allow_insecure=True
    )
    assert "REPO=flag-ai/bonnie\n" in script
    assert "PORT=7777\n" in script
    assert "SERVER_URL=http://karr.internal:8080\n" in script


def test_script_hardening() -> None:
    # FIX: StateDirectory for BONNIE 0.2.x, private temp dir, umask, tag check.
    script = render_install_script(TOKEN, URL)
    assert "StateDirectory=bonnie" in script
    assert "ReadWritePaths=/var/run/docker.sock /var/lib/bonnie" in script
    assert "ProtectSystem=strict" in script
    assert "umask 077" in script
    assert "mktemp -d" in script and "/tmp/bonnie" not in script
    assert 'install -o root -g root -m 0755 "${TMP_DIR}/bonnie"' in script
    assert "Refusing unexpected release tag" in script
    assert 'mkdir -p -m 700 "$CONFIG_DIR"' in script
    assert 'chown root:"$SERVICE_USER"' in script
    assert "curl -fsS -X POST" in script and "curl -fsSL -X POST" not in script
    assert "command -v openssl" in script


@pytest.mark.parametrize(
    "token", ["", "abc$(rm -rf /)", "tok en", "a;b", "é", "abc123\n", "None"[:0]]
)
def test_token_with_shell_metachars_rejected(token: str) -> None:
    # Go: TestScriptHandler_TokenWithShellMetachars (+ trailing newline)
    with pytest.raises(InstallScriptError, match="token"):
        render_install_script(token, URL)
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
        "https://user:pw@karr.example.com",
        "http://karr.test@evil.example",
        "https://karr.example.com:abc",
        "https://karr.example\n.com",
        "https://karr.example.com/a\tb",
        "https://evil.example$(id).com",
        "https://karr.example.com/../etc",
        "https://karr.example.com:0",
        "http://karr.example.com",
        "http://8.8.8.8",
    ],
)
def test_server_url_injection_rejected(url: str) -> None:
    # FIX: Go interpolated the Host header unquoted into the script.
    with pytest.raises(InstallScriptError, match="server_url"):
        render_install_script(TOKEN, url)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("  https://karr.example.com/ ", "https://karr.example.com"),
        ("https://karr.example.com/base/", "https://karr.example.com/base"),
        ("HTTPS://Karr.Example.com:8443", "https://karr.example.com:8443"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("http://[2001:db8::1]:7777/api", "http://[2001:db8::1]:7777/api"),
        ("http://10.0.0.5", "http://10.0.0.5"),
    ],
)
def test_server_url_normalised(given: str, expected: str) -> None:
    assert validate_server_url(given) == expected


def test_http_allowed_for_local_hosts_or_explicit_opt_in() -> None:
    # FIX: the phone-home POST carries the agent's auth token.
    assert validate_server_url("http://localhost:8080") == "http://localhost:8080"
    assert validate_server_url("http://192.168.1.10") == "http://192.168.1.10"
    assert validate_server_url("http://[::1]:8080") == "http://[::1]:8080"
    with pytest.raises(InstallScriptError, match="https"):
        validate_server_url("http://karr.example.com")
    assert (
        validate_server_url("http://karr.example.com", allow_insecure=True)
        == "http://karr.example.com"
    )
    assert "http://karr.example.com/api" in install_command(
        "http://karr.example.com", TOKEN, allow_insecure=True
    )


@pytest.mark.parametrize(
    "repo", ["", "bonnie", "a/b/c", "a/b$(x)", "../x", "flag-ai/bonnie\n"]
)
def test_repo_validation(repo: str) -> None:
    with pytest.raises(InstallScriptError, match="repo"):
        render_install_script(TOKEN, URL, repo=repo)
    with pytest.raises(InstallScriptError):
        validate_repo(repo)


@pytest.mark.parametrize("port", [0, 65536, -1, True])
def test_port_validation(port: int) -> None:
    with pytest.raises(InstallScriptError, match="port"):
        render_install_script(TOKEN, URL, port=port)


def test_values_are_shell_quoted_when_needed() -> None:
    script = render_install_script(TOKEN, URL, repo="my-org/my.repo")
    assert "REPO=my-org/my.repo\n" in script
    script = render_install_script(TOKEN, "http://[::1]:8080")
    assert "SERVER_URL='http://[::1]:8080'\n" in script  # shlex quotes the brackets


def test_install_command() -> None:
    # FIX: bash -s -- so --address passes through the pipe.
    cmd = install_command(URL, TOKEN)
    assert (
        cmd == f"curl -fsSL '{URL}/api/v1/install.sh?token={TOKEN}' | sudo bash -s --"
    )
    cmd = install_command(URL, TOKEN, address="192.168.1.50")
    assert cmd.endswith("| sudo bash -s -- --address 192.168.1.50")
    assert "/install.sh?" in install_command(URL, TOKEN, script_path="/install.sh")
    with pytest.raises(InstallScriptError, match="address"):
        install_command(URL, TOKEN, address="1.2.3.4; rm -rf /")
    with pytest.raises(InstallScriptError, match="address"):
        install_command(URL, TOKEN, address="--flag")
    with pytest.raises(InstallScriptError, match="script_path"):
        install_command(URL, TOKEN, script_path="/x;y")
