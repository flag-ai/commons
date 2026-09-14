"""Construct providers from the process environment."""

from __future__ import annotations

import logging
import os

from flag_commons.secrets.base import SecretsError, SecretsProvider
from flag_commons.secrets.chain import ChainProvider
from flag_commons.secrets.env import EnvProvider
from flag_commons.secrets.openbao import OpenBaoProvider

PROVIDER_ENV = "env"
PROVIDER_OPENBAO = "openbao"

ENV_OPENBAO_ADDR = "OPENBAO_ADDR"
# Variable name, not a secret value.
ENV_OPENBAO_TOKEN = "OPENBAO_TOKEN"  # nosec B105


def _openbao_from_env(logger: logging.Logger | None) -> OpenBaoProvider:
    addr = os.environ.get(ENV_OPENBAO_ADDR, "")
    if not addr:
        raise SecretsError(f"secrets: {ENV_OPENBAO_ADDR} environment variable not set")
    token = os.environ.get(ENV_OPENBAO_TOKEN, "")
    if not token:
        raise SecretsError(f"secrets: {ENV_OPENBAO_TOKEN} environment variable not set")
    return OpenBaoProvider(addr, token, logger=logger)


def new_provider(kind: str, logger: logging.Logger | None = None) -> SecretsProvider:
    """Build a single provider by name (``"env"`` or ``"openbao"``).

    ``"openbao"`` requires both ``OPENBAO_ADDR`` and ``OPENBAO_TOKEN``.
    """
    if kind == PROVIDER_ENV:
        return EnvProvider()
    if kind == PROVIDER_OPENBAO:
        return _openbao_from_env(logger)
    raise SecretsError(f"secrets: unknown provider type {kind!r}")


def provider_from_env(logger: logging.Logger | None = None) -> SecretsProvider:
    """Return ``Chain(Env, OpenBao)`` when OpenBao is configured, else ``Env``.

    Environment variables always win; OpenBao fills the gaps. This replaces
    the Go behavior where selecting OpenBao sent every key, including
    ``DATABASE_URL`` and ``LOG_LEVEL``, to OpenBao.
    """
    env = EnvProvider()
    if os.environ.get(ENV_OPENBAO_ADDR) and os.environ.get(ENV_OPENBAO_TOKEN):
        return ChainProvider([env, _openbao_from_env(logger)], logger=logger)
    return env
