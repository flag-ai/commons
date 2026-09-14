"""Shared fixtures."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_root_logging() -> Iterator[None]:
    """Restore the root logger so tests stay isolated from setup_logging."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in saved_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(saved_level)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
