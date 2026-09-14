"""Agent self-registration: request validation, source IP, status codes."""

from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_REGISTER_BODY = 64 * 1024

_log = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    """Body the install script POSTs after BONNIE comes up."""

    model_config = ConfigDict(extra="forbid")

    registration_token: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    auth_token: str = Field(min_length=1)
    address: str | None = None


class RegisterResult(BaseModel):
    agent_id: str
    message: str = "agent registered"


RegisterCallback = Callable[[RegisterRequest, str], Awaitable[RegisterResult]]


class RegistrationFailed(Exception):
    """Raised by a callback to reject a registration (answered as 422)."""


def parse_trusted_proxies(value: str) -> list[str]:
    """Split a comma-separated CIDR list and validate every entry."""
    entries = [part.strip() for part in value.split(",") if part.strip()]
    for entry in entries:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ValueError(
                f"trusted proxy {entry!r} is not an IP address or CIDR"
            ) from exc
    return entries


def is_trusted_proxy(peer_ip: str, trusted_proxies: Iterable[str]) -> bool:
    """True when ``peer_ip`` falls inside one of the configured networks."""
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for entry in trusted_proxies:
        try:
            if peer in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            _log.warning("ignoring malformed trusted proxy entry: %r", entry)
    return False


def resolve_source_ip(
    peer_ip: str,
    x_forwarded_for: str | None,
    trusted_proxies: Iterable[str] = (),
) -> str:
    """Return the client IP.

    ``X-Forwarded-For`` is honoured only when the direct peer is a trusted
    proxy. The chain is walked from the right, skipping trusted proxies, and
    the first untrusted entry wins; the leftmost entry is client-supplied
    with an appending proxy, so it is never trusted blindly. Anything that is
    not an IP address falls back to the peer. Go trusted the header
    unconditionally.
    """
    proxies = list(trusted_proxies)
    if not x_forwarded_for or not is_trusted_proxy(peer_ip, proxies):
        return peer_ip
    hops = [hop.strip() for hop in x_forwarded_for.split(",")]
    for hop in reversed(hops):
        if not hop:
            continue
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer_ip
        if not is_trusted_proxy(hop, proxies):
            return hop
    return peer_ip


async def handle_register(
    body: bytes,
    source_ip: str,
    callback: RegisterCallback,
    *,
    logger: logging.Logger | None = None,
) -> tuple[int, dict[str, Any]]:
    """Validate ``body`` and run ``callback``; return ``(status, json_body)``.

    Status codes match the Go handler: 201 on success, 400 for bad input,
    413 for an oversize body, 422 ``{"error": "registration failed"}`` when
    the callback raises. Unexpected callback exceptions are logged with a
    traceback so a consumer bug is not mistaken for a rejected token.
    """
    log = logger or _log
    if len(body) > MAX_REGISTER_BODY:
        return 413, {"error": "request body too large"}
    try:
        payload = json.loads(body)
    except ValueError:
        return 400, {"error": "invalid JSON body"}
    if not isinstance(payload, dict):
        return 400, {"error": "invalid JSON body"}
    try:
        req = RegisterRequest.model_validate(payload)
    except ValidationError as exc:
        return 400, {"error": describe_validation_error(exc)}

    try:
        result = await callback(req, source_ip)
    except RegistrationFailed as exc:
        log.warning(
            "agent registration rejected: source_ip=%s reason=%s", source_ip, exc
        )
        return 422, {"error": "registration failed"}
    except Exception as exc:  # noqa: BLE001 - never leak a consumer bug to the caller
        log.error(
            "agent registration failed: source_ip=%s error=%s",
            source_ip,
            exc,
            exc_info=True,
        )
        return 422, {"error": "registration failed"}

    log.info(
        "agent registered via install script: agent_id=%s source_ip=%s",
        result.agent_id,
        source_ip,
    )
    return 201, result.model_dump()


def describe_validation_error(exc: ValidationError) -> str:
    """Go-compatible messages for the common cases, accurate ones otherwise."""
    errors = exc.errors()
    if any(err.get("type") == "extra_forbidden" for err in errors):
        names = ", ".join(
            sorted(str(err["loc"][0]) for err in errors if err.get("loc"))
        )
        return f"unknown field(s): {names}"
    if any(err.get("type") == "missing" for err in errors):
        return "registration_token, auth_token, and port are required"
    fields = {str(err["loc"][0]) for err in errors if err.get("loc")}
    if fields == {"port"}:
        return "port must be between 1 and 65535"
    if fields <= {"registration_token", "auth_token", "port"}:
        return "registration_token, auth_token, and port are required"
    names = ", ".join(sorted(fields))
    return f"invalid field(s): {names}"
