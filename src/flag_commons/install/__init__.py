"""BONNIE provisioning: install script rendering and agent self-registration.

Differences from Go, on purpose (all security fixes): every templated value
is shell-quoted and the server URL is validated (Go interpolated the
``Host`` header unquoted); ``X-Forwarded-For`` is honoured only from
trusted proxies; the systemd unit gains ``StateDirectory=bonnie`` so
BONNIE 0.2.x can start under ``ProtectSystem=strict``; the install
one-liner uses ``bash -s --`` so ``--address`` passes through the pipe.
"""

from flag_commons.install.register import (
    MAX_REGISTER_BODY,
    RegisterCallback,
    RegisterRequest,
    RegisterResult,
    RegistrationFailed,
    handle_register,
    parse_trusted_proxies,
    resolve_source_ip,
)
from flag_commons.install.render import (
    DEFAULT_PORT,
    DEFAULT_REPO,
    InstallScriptError,
    install_command,
    render_install_script,
    validate_server_url,
    validate_token,
)

__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_REPO",
    "MAX_REGISTER_BODY",
    "InstallScriptError",
    "RegisterCallback",
    "RegisterRequest",
    "RegisterResult",
    "RegistrationFailed",
    "handle_register",
    "install_command",
    "parse_trusted_proxies",
    "render_install_script",
    "resolve_source_ip",
    "validate_server_url",
    "validate_token",
]
