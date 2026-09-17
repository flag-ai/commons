"""Unified secrets retrieval for FLAG components.

Providers implement :class:`SecretsProvider`. The interface is synchronous:
secrets are read at startup, and KITT is a Flask application.

* :class:`EnvProvider` reads environment variables.
* :class:`OpenBaoProvider` reads an OpenBao (Vault-compatible) KV v2 engine.
* :class:`ChainProvider` resolves each key through a list of providers in
  order, so environment variables win and OpenBao fills the gaps.
* :func:`provider_from_env` builds the right provider from ``OPENBAO_ADDR``
  and ``OPENBAO_TOKEN``.
"""

from flag_commons.secrets.base import (
    SecretNotFoundError,
    SecretsBackendError,
    SecretsError,
    SecretsProvider,
)
from flag_commons.secrets.chain import ChainProvider
from flag_commons.secrets.env import EnvProvider
from flag_commons.secrets.factory import (
    PROVIDER_ENV,
    PROVIDER_OPENBAO,
    new_provider,
    provider_from_env,
)
from flag_commons.secrets.openbao import OpenBaoProvider, parse_key

__all__ = [
    "PROVIDER_ENV",
    "PROVIDER_OPENBAO",
    "ChainProvider",
    "EnvProvider",
    "OpenBaoProvider",
    "SecretNotFoundError",
    "SecretsBackendError",
    "SecretsError",
    "SecretsProvider",
    "new_provider",
    "parse_key",
    "provider_from_env",
]
