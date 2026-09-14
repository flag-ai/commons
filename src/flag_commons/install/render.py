"""Render the BONNIE install script."""

from __future__ import annotations

import re
import shlex
from importlib import resources
from urllib.parse import urlsplit

DEFAULT_REPO = "flag-ai/bonnie"
DEFAULT_PORT = 7777

SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9]+$")
SAFE_REPO = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
# Anything that could break out of a shell word, even though values are quoted.
_SHELL_META = re.compile(r"[\s$`\\\"';&|<>(){}*?!#~\[\]]")


class InstallScriptError(ValueError):
    """A value could not be embedded safely in the install script."""


def _script_source() -> str:
    return (
        resources.files(__package__).joinpath("script.sh").read_text(encoding="utf-8")
    )


def validate_token(token: str) -> str:
    if not SAFE_TOKEN.match(token or ""):
        raise InstallScriptError("invalid token format")
    return token


def validate_repo(repo: str) -> str:
    if not SAFE_REPO.match(repo or "") or any(
        part in (".", "..") for part in repo.split("/")
    ):
        raise InstallScriptError("invalid binary repo format")
    return repo


def validate_server_url(url: str) -> str:
    """Accept only an http(s) URL with a host and no shell metacharacters.

    Go derived this value from the ``Host`` header and interpolated it
    unquoted, which allowed ``$(...)`` injection into the rendered script.
    """
    url = (url or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InstallScriptError("server_url must be an http(s) URL with a host")
    if parts.query or parts.fragment or _SHELL_META.search(url):
        raise InstallScriptError("server_url contains unsafe characters")
    return url


def validate_port(port: int) -> int:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise InstallScriptError("port must be between 1 and 65535")
    return port


def render_install_script(
    token: str,
    server_url: str,
    *,
    repo: str = DEFAULT_REPO,
    port: int = DEFAULT_PORT,
) -> str:
    """Return ``script.sh`` with the values substituted, each shell-quoted."""
    values = {
        "{{.BinaryRepo}}": shlex.quote(validate_repo(repo)),
        "{{.ServerURL}}": shlex.quote(validate_server_url(server_url)),
        "{{.RegistrationToken}}": shlex.quote(validate_token(token)),
        "{{.Port}}": str(validate_port(port)),
    }
    script = _script_source()
    for placeholder, value in values.items():
        script = script.replace(placeholder, value)
    if "{{." in script:
        raise InstallScriptError("unrendered placeholder in install script")
    return script


def install_command(server_url: str, token: str, *, address: str | None = None) -> str:
    """The one-liner an operator pastes on the GPU host.

    Uses ``bash -s --`` so ``--address`` can be passed through the pipe.
    """
    url = f"{validate_server_url(server_url)}/api/v1/install.sh?token={validate_token(token)}"
    cmd = f"curl -fsSL {shlex.quote(url)} | sudo bash -s --"
    if address:
        if _SHELL_META.search(address):
            raise InstallScriptError("address contains unsafe characters")
        cmd += f" --address {shlex.quote(address)}"
    return cmd
