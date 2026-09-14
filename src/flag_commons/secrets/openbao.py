"""OpenBao (Vault-compatible) KV v2 secrets provider."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

from flag_commons.secrets.base import (
    SecretNotFoundError,
    SecretsBackendError,
    SecretsError,
)

DEFAULT_MOUNT = "kv"
DEFAULT_CACHE_TTL = 300.0
DEFAULT_TIMEOUT = 10.0
DEFAULT_FIELD = "value"
MAX_ERROR_BODY = 4096

_log = logging.getLogger(__name__)


def parse_key(key: str) -> tuple[str, str]:
    """Split ``"path#field"`` into ``(path, field)``.

    The field defaults to ``"value"`` when no ``#`` is present. The split is
    on the first ``#``. An empty key, path or field is an error.
    """
    if key == "":
        raise SecretsError("secrets: empty key")
    path, sep, field = key.partition("#")
    if not sep:
        return key, DEFAULT_FIELD
    if path == "":
        raise SecretsError(f"secrets: empty path in key {key!r}")
    if field == "":
        raise SecretsError(f"secrets: empty field in key {key!r}")
    return path, field


class OpenBaoProvider:
    """Reads secrets from an OpenBao KV v2 engine with static-token auth.

    Requests are ``GET {addr}/v1/{mount}/data/{path}`` with the token in the
    ``X-Vault-Token`` header; the value is ``data.data[field]`` and must be a
    string. Values are cached in memory for ``cache_ttl`` seconds (``0``
    disables the cache); errors are never cached.
    """

    def __init__(
        self,
        addr: str,
        token: str,
        *,
        mount: str = DEFAULT_MOUNT,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.addr = addr.rstrip("/")
        self.mount = mount.strip("/")
        self.cache_ttl = cache_ttl
        self._token = token
        self._client = client or httpx.Client(timeout=timeout)
        self._log = logger or _log
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str, float]] = {}

    def __repr__(self) -> str:
        return f"OpenBaoProvider(addr={self.addr!r}, mount={self.mount!r})"

    def close(self) -> None:
        self._client.close()

    def get(self, key: str) -> str:
        path, field = parse_key(key)
        cached = self._from_cache(key)
        if cached is not None:
            return cached
        value = self._fetch(path, field)
        if self.cache_ttl > 0:
            self._to_cache(key, value)
        return value

    def get_or_default(self, key: str, default: str) -> str:
        try:
            return self.get(key)
        except SecretNotFoundError as exc:
            self._log.debug(
                "openbao secret not found, using default: key=%s error=%s", key, exc
            )
        except SecretsError as exc:
            self._log.warning(
                "openbao lookup failed, using default: key=%s error=%s", key, exc
            )
        return default

    def url_for(self, path: str) -> str:
        """The request URL for a secret path. Slashes stay slashes."""
        return f"{self.addr}/v1/{self.mount}/data/{quote(path, safe='/')}"

    def _fetch(self, path: str, field: str) -> str:
        try:
            resp = self._client.get(
                self.url_for(path), headers={"X-Vault-Token": self._token}
            )
        except httpx.HTTPError as exc:
            raise SecretsBackendError(
                f"secrets: openbao request failed: {exc}"
            ) from exc

        if resp.status_code == 404:
            raise SecretNotFoundError(
                f"secrets: openbao returned 404 for secret {path!r}"
            )
        if resp.status_code != 200:
            body = resp.text[:MAX_ERROR_BODY]
            raise SecretsBackendError(
                f"secrets: openbao returned {resp.status_code}: {body}"
            )

        try:
            payload: Any = resp.json()
            data = payload["data"]["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise SecretsBackendError(
                f"secrets: failed to decode openbao response: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise SecretsBackendError(
                "secrets: failed to decode openbao response: data is not an object"
            )
        if field not in data:
            raise SecretNotFoundError(
                f"secrets: field {field!r} not found in secret {path!r}"
            )
        value = data[field]
        if not isinstance(value, str):
            raise SecretsBackendError(
                f"secrets: field {field!r} in secret {path!r} is not a string"
            )
        return value

    def _from_cache(self, key: str) -> str | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expires = entry
            if time.monotonic() >= expires:
                del self._cache[key]
                return None
            return value

    def _to_cache(self, key: str, value: str) -> None:
        with self._lock:
            self._cache[key] = (value, time.monotonic() + self.cache_ttl)
