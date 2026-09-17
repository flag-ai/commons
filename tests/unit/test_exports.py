"""Every name a package lists in ``__all__`` must resolve (a star-import must work)."""

from __future__ import annotations

import importlib

import pytest

PACKAGES = [
    "flag_commons",
    "flag_commons.secrets",
    "flag_commons.health",
    "flag_commons.database",
    "flag_commons.bonnie",
    "flag_commons.install",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_all_names_resolve(name: str) -> None:
    module = importlib.import_module(name)
    missing = [n for n in getattr(module, "__all__", []) if not hasattr(module, n)]
    assert not missing, f"{name}.__all__ names undefined attributes: {missing}"
