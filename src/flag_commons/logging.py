"""Structured logging for FLAG components.

This configures the **stdlib root logger**, because KITT and DEVON use
``logging.getLogger(__name__)`` everywhere. Records are rendered either as
slog-style ``key=value`` text or as JSON whose field names match Go's
``log/slog`` (``time``, ``level``, ``msg``, ``component``, ``version`` plus
extras), so log queries work the same across BONNIE (Go) and the Python
services.

The Go ``WithContext`` / ``FromContext`` helpers are replaced by
:func:`bind`, a context manager backed by :mod:`contextvars`; the bound
fields are injected into every record emitted inside the block.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, TextIO

from flag_commons import version as flag_version

Logger = logging.Logger

FORMAT_TEXT = "text"
FORMAT_JSON = "json"

_LEVELS: Mapping[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# Go slog spells the warning level WARN.
_LEVEL_NAMES: Mapping[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "ERROR",
}

# Attributes every LogRecord carries; anything else came from ``extra=``.
_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
    | {"message", "asctime", "flag_context"}
)

_HANDLER_TAG = "_flag_commons_handler"

_EMPTY: Mapping[str, Any] = MappingProxyType({})
_bound: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "flag_commons_log_context", default=_EMPTY
)


def parse_level(name: str) -> int:
    """Map a level name to a stdlib level, defaulting to INFO like Go."""
    return _LEVELS.get(name.strip().lower(), logging.INFO)


def level_name(levelno: int) -> str:
    """Return the slog-style level name for ``levelno``."""
    if levelno in _LEVEL_NAMES:
        return _LEVEL_NAMES[levelno]
    if levelno >= logging.ERROR:
        return "ERROR"
    if levelno >= logging.WARNING:
        return "WARN"
    if levelno >= logging.INFO:
        return "INFO"
    return "DEBUG"


@contextmanager
def bind(**fields: Any) -> Iterator[None]:
    """Attach ``fields`` to every record logged inside the block."""
    merged = {**_bound.get(), **fields}
    token = _bound.set(merged)
    try:
        yield
    finally:
        _bound.reset(token)


def bound_fields() -> Mapping[str, Any]:
    """Return the fields currently bound with :func:`bind`."""
    return _bound.get()


class ContextFilter(logging.Filter):
    """Copy the bound context fields onto each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.flag_context = dict(_bound.get())
        return True


def _record_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = dict(getattr(record, "flag_context", None) or {})
    for key, value in record.__dict__.items():
        if key not in _STANDARD_ATTRS and not key.startswith("_"):
            fields[key] = value
    return fields


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    )


class _BaseFormatter(logging.Formatter):
    def __init__(self, component: str, version: str) -> None:
        super().__init__()
        self.component = component
        self.version = version

    def fields(self, record: logging.LogRecord) -> dict[str, Any]:
        out: dict[str, Any] = {
            "time": _timestamp(record),
            "level": level_name(record.levelno),
            "msg": record.getMessage(),
            "component": self.component,
            "version": self.version,
            "logger": record.name,
        }
        out.update(_record_fields(record))
        if record.exc_info and record.exc_info[1] is not None:
            out["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            out["exception"] = record.exc_text
        return out


class JSONFormatter(_BaseFormatter):
    """One JSON object per line with Go slog field names."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.fields(record), default=str, separators=(",", ":"))


def _quote(value: Any) -> str:
    text = str(value)
    if text == "" or any(c.isspace() or c in '"=' for c in text):
        return json.dumps(text)
    return text


class TextFormatter(_BaseFormatter):
    """slog-style ``key=value`` text, one record per line."""

    def format(self, record: logging.LogRecord) -> str:
        return " ".join(
            f"{key}={_quote(value)}" for key, value in self.fields(record).items()
        )


def make_formatter(component: str, fmt: str, version: str) -> logging.Formatter:
    """Return the formatter for ``fmt``; unknown formats fall back to text."""
    if fmt.strip().lower() == FORMAT_JSON:
        return JSONFormatter(component, version)
    return TextFormatter(component, version)


def setup_logging(
    component: str,
    *,
    level: str = "info",
    fmt: str = FORMAT_TEXT,
    stream: TextIO = sys.stderr,
    dist_name: str | None = None,
) -> Logger:
    """Configure the root logger and return the component's logger.

    Calling it again replaces the handler installed by the previous call, so
    tests and re-configuration are safe. ``dist_name`` is the distribution
    whose version is stamped on every record; it defaults to ``component``.
    """
    version = flag_version.get_version(dist_name or component)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter(component, fmt, version))
    handler.addFilter(ContextFilter())
    setattr(handler, _HANDLER_TAG, True)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_TAG, False):
            root.removeHandler(existing)
            existing.close()
    root.addHandler(handler)
    root.setLevel(parse_level(level))
    return logging.getLogger(component)


def uvicorn_log_config(
    component: str, level: str = "info", fmt: str = FORMAT_TEXT
) -> dict[str, Any]:
    """A ``logging.config.dictConfig`` mapping that routes uvicorn through us.

    Pass it as ``uvicorn.run(..., log_config=uvicorn_log_config(...))``. The
    uvicorn loggers propagate to the root logger configured by
    :func:`setup_logging`, so their output shares the same formatter.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"level": parse_level(level), "propagate": True, "handlers": []},
            "uvicorn.error": {
                "level": parse_level(level),
                "propagate": True,
                "handlers": [],
            },
            "uvicorn.access": {
                "level": parse_level(level),
                "propagate": True,
                "handlers": [],
            },
        },
    }
