"""BONNIE provisioning: install script rendering and agent self-registration.

Differences from Go, on purpose (all security fixes): every templated value
is shell-quoted and the server URL is validated and rebuilt from its parts
(Go interpolated the ``Host`` header unquoted); the server URL is either
configured or taken from trusted-proxy headers, never from the plain
``Host`` header; ``X-Forwarded-For`` is walked from the right past trusted
proxies; the install script downloads into a private temp dir and installs
root-owned, writes its config under ``umask 077``, validates the release
tag, and its systemd unit gains ``StateDirectory=bonnie`` so BONNIE 0.2.x
can start under ``ProtectSystem=strict``; the install one-liner uses
``bash -s --`` so ``--address`` passes through the pipe.
"""

from flag_commons.install.register import (
    MAX_REGISTER_BODY,
    RegisterCallback,
    RegisterRequest,
    RegisterResult,
    RegistrationFailed,
    describe_validation_error,
    handle_register,
    is_trusted_proxy,
    parse_trusted_proxies,
    resolve_source_ip,
)
from flag_commons.install.render import (
    DEFAULT_PORT,
    DEFAULT_REPO,
    DEFAULT_SCRIPT_PATH,
    InstallScriptError,
    install_command,
    render_install_script,
    validate_port,
    validate_repo,
    validate_server_url,
    validate_token,
)

__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_REPO",
    "DEFAULT_SCRIPT_PATH",
    "MAX_REGISTER_BODY",
    "InstallScriptError",
    "RegisterCallback",
    "RegisterRequest",
    "RegisterResult",
    "RegistrationFailed",
    "describe_validation_error",
    "handle_register",
    "install_command",
    "is_trusted_proxy",
    "parse_trusted_proxies",
    "render_install_script",
    "resolve_source_ip",
    "validate_port",
    "validate_repo",
    "validate_server_url",
    "validate_token",
]
