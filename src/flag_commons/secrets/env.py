"""Environment-variable secrets provider."""

from __future__ import annotations

import os

from flag_commons.secrets.base import SecretNotFoundError


class EnvProvider:
    """Reads secrets from environment variables.

    A variable that is set but empty returns ``""``, not the default, matching
    Go's ``os.LookupEnv`` semantics.
    """

    def get(self, key: str) -> str:
        try:
            return os.environ[key]
        except KeyError:
            raise SecretNotFoundError(
                f"secrets: environment variable {key!r} not set"
            ) from None

    def get_or_default(self, key: str, default: str) -> str:
        return os.environ.get(key, default)

    def __repr__(self) -> str:
        return "EnvProvider()"
