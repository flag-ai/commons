"""Provider protocol and error types."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class SecretsError(Exception):
    """Base class for secrets errors."""


class SecretNotFoundError(SecretsError):
    """The key does not exist in the backend."""


class SecretsBackendError(SecretsError):
    """The backend could not be reached or returned an unusable answer."""


@runtime_checkable
class SecretsProvider(Protocol):
    """Retrieves secret values by key."""

    def get(self, key: str) -> str:
        """Return the value for ``key``.

        Raises :class:`SecretNotFoundError` when the key does not exist and
        :class:`SecretsBackendError` when the backend fails.
        """
        ...

    def get_or_default(self, key: str, default: str) -> str:
        """Return the value for ``key``, or ``default`` on any error."""
        ...
