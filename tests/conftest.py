"""Shared fixtures."""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_root_logging() -> None:
    """Remove handlers our setup_logging installed so tests stay isolated."""
    yield  # type: ignore[misc]
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_flag_commons_handler", False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(logging.WARNING)
