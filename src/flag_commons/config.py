"""Base configuration loading for FLAG components.

Mirrors the Go ``config.Base`` / ``config.LoadBase`` contract: every FLAG
component reads ``DATABASE_URL``, ``LOG_LEVEL``, ``LOG_FORMAT`` and
``LISTEN_ADDR`` through a :class:`~flag_commons.secrets.SecretsProvider`.
Components subclass :class:`BaseConfig` and read their own keys through the
same provider (see :meth:`BaseConfig.base_fields`).

Differences from Go, on purpose:

* An empty ``DATABASE_URL`` is rejected when the database is required.
* ``require_database=False`` exists for components without a database
  (BONNIE could not use ``LoadBase`` at all).
* ``database_url`` is a :class:`pydantic.SecretStr`; call
  ``cfg.database_url.get_secret_value()`` to read it.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from flag_commons import logging as flag_logging
from flag_commons.secrets import SecretsError, SecretsProvider

DEFAULT_LOG_LEVEL = "info"
DEFAULT_LOG_FORMAT = "text"
DEFAULT_LISTEN_ADDR = ":8080"


class ConfigError(ValueError):
    """Raised when required configuration is missing or malformed."""


class BaseConfig(BaseModel):
    """Configuration common to all FLAG components."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str = Field(min_length=1)
    log_level: str = DEFAULT_LOG_LEVEL
    log_format: str = DEFAULT_LOG_FORMAT
    database_url: SecretStr = SecretStr("")
    listen_addr: str = DEFAULT_LISTEN_ADDR

    @staticmethod
    def base_fields(
        component: str,
        provider: SecretsProvider,
        *,
        require_database: bool = True,
    ) -> dict[str, Any]:
        """Read the base keys from ``provider`` and return them as kwargs.

        Subclasses call this and add their own keys::

            class KarrConfig(BaseConfig):
                admin_token: SecretStr

                @classmethod
                def load(cls, provider):
                    return cls(
                        **cls.base_fields("karr", provider),
                        admin_token=SecretStr(provider.get("KARR_ADMIN_TOKEN")),
                    )

        Secrets are typed :class:`pydantic.SecretStr` so ``repr()`` and
        ``model_dump()`` never leak them; read them with
        ``.get_secret_value()`` at the point of use.
        """
        if not component:
            raise ConfigError("config: component name is required")

        if require_database:
            try:
                database_url = provider.get("DATABASE_URL")
            except SecretsError as exc:
                raise ConfigError(f"config: DATABASE_URL is required: {exc}") from exc
            if not database_url:
                raise ConfigError("config: DATABASE_URL is required: value is empty")
        else:
            database_url = provider.get_or_default("DATABASE_URL", "")

        return {
            "component": component,
            "log_level": provider.get_or_default("LOG_LEVEL", DEFAULT_LOG_LEVEL),
            "log_format": provider.get_or_default("LOG_FORMAT", DEFAULT_LOG_FORMAT),
            "database_url": SecretStr(database_url),
            "listen_addr": provider.get_or_default("LISTEN_ADDR", DEFAULT_LISTEN_ADDR),
        }

    def setup_logging(
        self,
        *,
        stream: TextIO = sys.stderr,
        dist_name: str | None = None,
    ) -> flag_logging.Logger:
        """Configure the root logger from ``log_level`` and ``log_format``."""
        return flag_logging.setup_logging(
            self.component,
            level=self.log_level,
            fmt=self.log_format,
            stream=stream,
            dist_name=dist_name,
        )

    def bind_address(self) -> tuple[str, int]:
        """Split ``listen_addr`` into a ``(host, port)`` pair for uvicorn.

        ``":8080"`` (the Go convention for "all interfaces") becomes
        ``("0.0.0.0", 8080)``. IPv6 literals use the ``[::1]:8080`` form.
        """
        return parse_listen_addr(self.listen_addr)


def parse_listen_addr(addr: str) -> tuple[str, int]:
    """Parse a Go-style ``host:port`` listen address."""
    addr = addr.strip()
    if not addr:
        raise ConfigError("config: LISTEN_ADDR is empty")
    host, sep, port_str = addr.rpartition(":")
    if not sep:
        raise ConfigError(f"config: LISTEN_ADDR {addr!r} has no port")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        # ":port" means all interfaces, as in Go.
        host = "0.0.0.0"  # nosec B104
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ConfigError(
            f"config: LISTEN_ADDR {addr!r} has a non-numeric port"
        ) from exc
    if not 0 < port < 65536:
        raise ConfigError(f"config: LISTEN_ADDR {addr!r} port out of range")
    return host, port


def load_base(
    component: str,
    provider: SecretsProvider,
    *,
    require_database: bool = True,
) -> BaseConfig:
    """Build a :class:`BaseConfig` by reading keys through ``provider``."""
    return BaseConfig(
        **BaseConfig.base_fields(component, provider, require_database=require_database)
    )
