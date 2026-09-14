"""Built-in checkers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine

DEFAULT_HTTP_TIMEOUT = 5.0


class DatabaseChecker:
    """Runs ``SELECT 1`` on a SQLAlchemy engine (sync or async)."""

    name = "database"

    def __init__(self, engine: AsyncEngine | Engine | None) -> None:
        self._engine = engine

    async def check(self) -> None:
        if self._engine is None:
            raise RuntimeError("health: database engine is nil")
        from flag_commons.database.engine import ping

        await ping(self._engine, retries=1)


class HttpChecker:
    """GETs ``url`` and expects a 2xx response.

    Redirects are followed, as Go's default ``http.Client`` did. Only the
    status line is read; the body is never buffered. When a ``client`` is
    injected, ``timeout`` is still applied per request.
    """

    def __init__(
        self,
        name: str,
        url: str,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self.timeout = timeout
        self._client = client

    async def check(self) -> None:
        if self._client is not None:
            await self._request(self._client)
            return
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await self._request(client)

    async def _request(self, client: httpx.AsyncClient) -> None:
        try:
            async with client.stream(
                "GET", self.url, timeout=self.timeout, follow_redirects=True
            ) as resp:
                status = resp.status_code
        except httpx.HTTPError as exc:
            raise RuntimeError(f"health: request to {self.name} failed: {exc}") from exc
        if not 200 <= status < 300:
            raise RuntimeError(f"health: {self.name} returned status {status}")

    def __repr__(self) -> str:
        try:
            url = httpx.URL(self.url)
        except httpx.InvalidURL:
            url = None
        if url is None or not url.host:
            safe = "<invalid url>"
        else:
            safe = f"{url.scheme}://{url.host}{url.path}"
        return f"HttpChecker(name={self.name!r}, url={safe!r})"
