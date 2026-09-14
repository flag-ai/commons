"""Typed errors for the BONNIE client."""

from __future__ import annotations

import json
import re

MAX_ERROR_BODY = 4096
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


def sanitize(text: str) -> str:
    """Strip control characters so server-controlled text cannot forge log lines."""
    return _CONTROL.sub(" ", text)


class BonnieError(Exception):
    """A non-2xx response from BONNIE.

    ``message`` is the ``error`` field of a ``{"error": "..."}`` body when
    present, otherwise the (truncated) raw body.
    """

    def __init__(
        self, op: str, status: int | None, body: str = "", message: str | None = None
    ) -> None:
        self.op = op
        self.status = status
        self.body = body[:MAX_ERROR_BODY]
        self.message = sanitize(
            message if message is not None else _extract_message(self.body)
        )
        super().__init__(self._render())

    def _render(self) -> str:
        if self.status is None:
            return f"bonnie: {self.op}: {self.message}"
        return f"bonnie: {self.op} returned {self.status}: {self.message}"


class BonnieUnauthorized(BonnieError):
    """HTTP 401 or 403: the bearer token was rejected."""


class BonnieNotFound(BonnieError):
    """HTTP 404: the container, model or route does not exist."""


class BonnieBadRequest(BonnieError):
    """HTTP 400: BONNIE rejected the request body or parameters."""


class BonnieUnavailable(BonnieError):
    """The agent could not be reached (network error, timeout, retries exhausted)."""

    def __init__(self, op: str, message: str) -> None:
        super().__init__(op, None, "", message)


def _extract_message(body: str) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        return body
    if isinstance(parsed, dict):
        message = parsed.get("error")
        if isinstance(message, str):
            return message
    return body


def error_for(op: str, status: int, body: str) -> BonnieError:
    """Build the most specific error class for ``status``."""
    if status in (401, 403):
        return BonnieUnauthorized(op, status, body)
    if status == 404:
        return BonnieNotFound(op, status, body)
    if status == 400:
        return BonnieBadRequest(op, status, body)
    return BonnieError(op, status, body)
