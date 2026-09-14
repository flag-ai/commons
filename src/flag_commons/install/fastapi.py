"""FastAPI adapter: ``GET /install.sh`` and ``POST /agents/register``.

Requires the ``fastapi`` extra. Mount the router under the service's API
prefix (KARR uses ``/api/v1``).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from flag_commons.install.register import (
    RegisterCallback,
    handle_register,
    resolve_source_ip,
)
from flag_commons.install.render import (
    DEFAULT_PORT,
    DEFAULT_REPO,
    InstallScriptError,
    render_install_script,
)

TokenLookup = Callable[[Request], "str | Awaitable[str]"]
ServerURL = str | Callable[[Request], str] | None


class TokenLookupError(Exception):
    """Raised by the token lookup to answer with a specific status.

    KARR raises it with 404 for an unknown token and 410 for a claimed or
    expired one (K-D7); 400 for a missing or malformed query parameter.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def peer_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def detect_server_url(request: Request, trusted_proxies: Iterable[str]) -> str:
    """Scheme and host of the control plane as seen by the caller.

    ``X-Forwarded-Proto`` and ``X-Forwarded-Host`` are honoured only when the
    peer is a trusted proxy; otherwise the request's own URL is used.
    """
    scheme = request.url.scheme
    host = request.url.netloc
    if _trusted(request, trusted_proxies):
        proto = (
            request.headers.get("x-forwarded-proto", "")
            .split(",", 1)[0]
            .strip()
            .lower()
        )
        if proto in ("http", "https"):
            scheme = proto
        forwarded_host = (
            request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
        )
        if forwarded_host:
            host = forwarded_host
    return f"{scheme}://{host}"


def _trusted(request: Request, trusted_proxies: Iterable[str]) -> bool:
    ip = peer_ip(request)
    return resolve_source_ip(ip, "x", trusted_proxies) != ip


def install_router(
    *,
    token_lookup: TokenLookup,
    register: RegisterCallback,
    server_url: ServerURL = None,
    trusted_proxies: Iterable[str] = (),
    repo: str = DEFAULT_REPO,
    port: int = DEFAULT_PORT,
    logger: logging.Logger | None = None,
) -> APIRouter:
    """Build the router.

    ``token_lookup`` receives the request and returns the registration
    token to embed, or raises :class:`TokenLookupError`. ``register`` is
    awaited with the validated :class:`RegisterRequest` and the source IP.
    """
    proxies = list(trusted_proxies)
    router = APIRouter(tags=["install"])

    @router.get("/install.sh", summary="BONNIE install script", response_class=Response)
    async def install_script(request: Request) -> Response:
        try:
            token = token_lookup(request)
            if inspect.isawaitable(token):
                token = await token
        except TokenLookupError as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status_code)
        if callable(server_url):
            base = server_url(request)
        elif server_url:
            base = server_url
        else:
            base = detect_server_url(request, proxies)
        try:
            script = render_install_script(str(token), base, repo=repo, port=port)
        except InstallScriptError as exc:
            status = 500 if "repo" in str(exc) or "placeholder" in str(exc) else 400
            return JSONResponse({"error": str(exc)}, status_code=status)
        return Response(script, media_type="text/x-shellscript")

    @router.post("/agents/register", summary="Agent self-registration")
    async def agents_register(request: Request) -> JSONResponse:
        body = await request.body()
        source_ip = resolve_source_ip(
            peer_ip(request), request.headers.get("x-forwarded-for"), proxies
        )
        status, payload = await handle_register(
            body, source_ip, register, logger=logger
        )
        return JSONResponse(payload, status_code=status)

    return router
