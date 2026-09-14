"""Shared Python library for the FLAG platform."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    __version__ = _dist_version("flag-commons")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "dev"

__all__ = ["__version__"]
