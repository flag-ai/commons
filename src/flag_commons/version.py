"""Build-time version information for FLAG components.

The Go library set ``Version``, ``Commit`` and ``Date`` through ldflags. In
Python the version is defined once, in the distribution's ``pyproject.toml``,
and read back through :mod:`importlib.metadata`. The commit and build date are
baked into the container image as the environment variables
``FLAG_BUILD_COMMIT`` and ``FLAG_BUILD_DATE``.

:func:`info` returns the exact string format the Go library produced,
``"<version> (commit: <commit>, built: <date>)"``. That string is a wire
contract: BONNIE's ``/health`` report and every FLAG service's ``/health``
endpoint emit it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

DEFAULT_VERSION = "dev"
DEFAULT_COMMIT = "unknown"
DEFAULT_DATE = "unknown"

ENV_COMMIT = "FLAG_BUILD_COMMIT"
ENV_DATE = "FLAG_BUILD_DATE"


@dataclass(frozen=True)
class VersionInfo:
    """Version, commit and build date of a FLAG component."""

    version: str = DEFAULT_VERSION
    commit: str = DEFAULT_COMMIT
    date: str = DEFAULT_DATE

    def __str__(self) -> str:
        return format_info(self.version, self.commit, self.date)


def format_info(version: str, commit: str, date: str) -> str:
    """Render the Go-compatible version string."""
    return f"{version} (commit: {commit}, built: {date})"


def get_version(dist_name: str) -> str:
    """Return the installed version of ``dist_name``, or ``"dev"``."""
    try:
        return _dist_version(dist_name)
    except PackageNotFoundError:
        return DEFAULT_VERSION


def get_info(dist_name: str) -> VersionInfo:
    """Collect version info for the distribution ``dist_name``."""
    return VersionInfo(
        version=get_version(dist_name),
        commit=os.environ.get(ENV_COMMIT) or DEFAULT_COMMIT,
        date=os.environ.get(ENV_DATE) or DEFAULT_DATE,
    )


def info(dist_name: str) -> str:
    """Return ``"<version> (commit: <commit>, built: <date>)"`` for ``dist_name``."""
    return str(get_info(dist_name))
