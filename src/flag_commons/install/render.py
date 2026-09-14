"""Render the BONNIE install script."""

from __future__ import annotations

import re
import shlex
from importlib import resources
from urllib.parse import urlsplit

DEFAULT_REPO = "flag-ai/bonnie"
DEFAULT_PORT = 7777
DEFAULT_SCRIPT_PATH = "/api/v1/install.sh"

SAFE_TOKEN = re.compile(r"[a-zA-Z0-9]+")
SAFE_REPO = re.compile(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+")
SAFE_HOST = re.compile(r"[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:.]+\]")
SAFE_PATH = re.compile(r"(/[A-Za-z0-9._\-]+)*")
SAFE_ADDRESS = re.compile(r"[A-Za-z0-9.:\-]+")


class InstallScriptError(ValueError):
    """A value could not be embedded safely in the install script."""


def _script_source() -> str:
    return (
        resources.files(__package__).joinpath("script.sh").read_text(encoding="utf-8")
    )


def validate_token(token: str) -> str:
    if not isinstance(token, str) or not SAFE_TOKEN.fullmatch(token):
        raise InstallScriptError("invalid token format")
    return token


def validate_repo(repo: str) -> str:
    if not SAFE_REPO.fullmatch(repo or "") or any(
        part in (".", "..") for part in repo.split("/")
    ):
        raise InstallScriptError("invalid binary repo format")
    return repo


def validate_server_url(url: str) -> str:
    """Accept only ``http(s)://host[:port][/path]`` and return it normalised.

    The host may be a name, an IPv4 address or a bracketed IPv6 literal; no
    userinfo, query or fragment; the path is limited to plain segments. The
    value is rebuilt from its parts, so nothing outside those rules can reach
    the script. Go interpolated the ``Host`` header unquoted.
    """
    raw = (url or "").strip()
    if re.search(r"\s", raw):
        raise InstallScriptError("server_url contains unsafe characters")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise InstallScriptError("server_url must be an http(s) URL with a host")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise InstallScriptError("server_url must not contain credentials")
    if parts.query or parts.fragment:
        raise InstallScriptError("server_url must not contain a query or fragment")
    host = parts.hostname or ""
    if not host:
        raise InstallScriptError("server_url must be an http(s) URL with a host")
    if ":" in host:
        host = f"[{host}]"
    if not SAFE_HOST.fullmatch(host):
        raise InstallScriptError("server_url contains unsafe characters")
    try:
        port = parts.port
    except ValueError as exc:
        raise InstallScriptError("server_url has an invalid port") from exc
    path = parts.path.rstrip("/")
    if not SAFE_PATH.fullmatch(path):
        raise InstallScriptError("server_url contains unsafe characters")
    netloc = f"{host}:{port}" if port is not None else host
    return f"{parts.scheme}://{netloc}{path}"


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


def install_command(
    server_url: str,
    token: str,
    *,
    address: str | None = None,
    script_path: str = DEFAULT_SCRIPT_PATH,
) -> str:
    """The one-liner an operator pastes on the GPU host.

    Uses ``bash -s --`` so ``--address`` can be passed through the pipe.
    """
    if not SAFE_PATH.fullmatch(script_path) or not script_path.startswith("/"):
        raise InstallScriptError("script_path contains unsafe characters")
    url = (
        f"{validate_server_url(server_url)}{script_path}?token={validate_token(token)}"
    )
    cmd = f"curl -fsSL {shlex.quote(url)} | sudo bash -s --"
    if address:
        if not SAFE_ADDRESS.fullmatch(address):
            raise InstallScriptError("address contains unsafe characters")
        cmd += f" --address {shlex.quote(address)}"
    return cmd
