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


def resolve_source_ip(
    peer_ip: str,
    x_forwarded_for: str | None,
    trusted_proxies: Iterable[str] = (),
) -> str:
    """Return the client IP.

    ``X-Forwarded-For`` is honoured only when the direct peer is inside one
    of ``trusted_proxies`` (CIDRs or single addresses). Go trusted the
    header unconditionally, so any client could claim any source address.
    """
    if not x_forwarded_for or not _is_trusted(peer_ip, trusted_proxies):
        return peer_ip
    first = x_forwarded_for.split(",", 1)[0].strip()
    return first or peer_ip


def _is_trusted(peer_ip: str, trusted_proxies: Iterable[str]) -> bool:
    try:
        peer = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for entry in trusted_proxies:
        try:
            if peer in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def parse_trusted_proxies(value: str) -> list[str]:
    """Split a comma-separated CIDR list, dropping empties."""
    return [part.strip() for part in value.split(",") if part.strip()]


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
    the callback fails.
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
        return 400, {"error": _describe(exc)}

    try:
        result = await callback(req, source_ip)
    except Exception as exc:  # noqa: BLE001 - the callback owns its own errors
        log.error("agent registration failed: source_ip=%s error=%s", source_ip, exc)
        return 422, {"error": "registration failed"}

    log.info(
        "agent registered via install script: agent_id=%s source_ip=%s",
        result.agent_id,
        source_ip,
    )
    return 201, result.model_dump()


def _describe(exc: ValidationError) -> str:
    errors = exc.errors()
    fields = {str(err["loc"][0]) for err in errors if err.get("loc")}
    missing = any(err.get("type") == "missing" for err in errors)
    if not missing and fields == {"port"}:
        return "port must be between 1 and 65535"
    return "registration_token, auth_token, and port are required"
