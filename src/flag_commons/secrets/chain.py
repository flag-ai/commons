"""Chain several providers so each key is resolved independently."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from flag_commons.secrets.base import (
    SecretNotFoundError,
    SecretsBackendError,
    SecretsError,
    SecretsProvider,
)

_log = logging.getLogger(__name__)


class ChainProvider:
    """Try each provider in order and return the first value found.

    A :class:`SecretNotFoundError` moves on to the next provider. A
    :class:`SecretsBackendError` is remembered and also moves on; if no later
    provider has the key, that backend error is raised, so a broken OpenBao
    is reported rather than disguised as "not found".
    """

    def __init__(
        self,
        providers: Sequence[SecretsProvider],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        if not providers:
            raise ValueError("secrets: ChainProvider needs at least one provider")
        self.providers = list(providers)
        self._log = logger or _log

    def __repr__(self) -> str:
        return f"ChainProvider({self.providers!r})"

    def get(self, key: str) -> str:
        backend_error: SecretsBackendError | None = None
        for provider in self.providers:
            try:
                return provider.get(key)
            except SecretNotFoundError:
                continue
            except SecretsBackendError as exc:
                backend_error = exc
                continue
        if backend_error is not None:
            raise backend_error
        raise SecretNotFoundError(f"secrets: key {key!r} not found in any provider")

    def get_or_default(self, key: str, default: str) -> str:
        try:
            return self.get(key)
        except SecretNotFoundError:
            return default
        except SecretsError as exc:
            self._log.warning(
                "secret lookup failed, using default: key=%s error=%s", key, exc
            )
            return default
