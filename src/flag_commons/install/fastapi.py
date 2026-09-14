"""FastAPI adapter: ``GET /install.sh`` and ``POST /agents/register``.

Requires the ``fastapi`` extra. Mount the router under the service's API
prefix (KARR uses ``/api/v1``).

The control-plane URL embedded in the script is either configured
explicitly (``server_url``) or detected from ``X-Forwarded-Proto`` /
``X-Forwarded-Host`` **only when the peer is a trusted proxy**. The plain
``Host`` header is never trusted: an attacker who can forge it would make
the installed agent phone home, auth token included, to their own server.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from flag_commons.install.register import (
    MAX_REGISTER_BODY,
    RegisterCallback,
    handle_register,
    is_trusted_proxy,
    resolve_source_ip,
)
from flag_commons.install.render import (
    DEFAULT_PORT,
    DEFAULT_REPO,
    SAFE_HOST,
    InstallScriptError,
    InvalidTokenError,
    render_install_script,
    validate_port,
    validate_repo,
    validate_server_url,
)

TokenLookup = Callable[[Request], "str | Awaitable[str]"]
ServerURL = str | Callable[[Request], str] | None

TOKEN_ERROR_STATUSES = frozenset({400, 401, 403, 404, 410})

_log = logging.getLogger(__name__)


class TokenLookupError(Exception):
    """Raised by the token lookup to answer with a specific status.

    KARR raises it with 404 for an unknown token and 410 for a claimed or
    expired one (K-D7); 400 for a missing or malformed query parameter. Any
    other status is answered as 500 with a fixed body.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def peer_ip(request: Request) -> str:
    return request.client.host if request.client and request.client.host else "unknown"


def detect_server_url(
    request: Request,
    trusted_proxies: Iterable[str],
    allowed_hosts: Iterable[str] = (),
) -> str | None:
    """Scheme and host as forwarded by a trusted proxy, else ``None``.

    The forwarded host must be a bare ``host[:port]`` (no path), and when
    ``allowed_hosts`` is given it must be one of them. Many proxies copy the
    client's own ``Host`` header into ``X-Forwarded-Host``, so the trusted
    peer alone does not vouch for the value.
    """
    if not is_trusted_proxy(peer_ip(request), trusted_proxies):
        return None
    proto = (
        request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    )
    host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    if proto not in ("http", "https") or not host:
        return None
    bare, port = host, ""
    if host.count(":") == 1:
        bare, _, port = host.rpartition(":")
    if not SAFE_HOST.fullmatch(bare) or (port and not port.isdigit()):
        return None
    allowed = list(allowed_hosts)
    if allowed and host not in allowed and bare not in allowed:
        return None
    return f"{proto}://{host}"


def install_router(
    *,
    token_lookup: TokenLookup,
    register: RegisterCallback,
    server_url: ServerURL = None,
    trusted_proxies: Iterable[str] = (),
    allowed_hosts: Iterable[str] = (),
    repo: str = DEFAULT_REPO,
    port: int = DEFAULT_PORT,
    allow_insecure: bool = False,
    logger: logging.Logger | None = None,
) -> APIRouter:
    """Build the router.

    ``token_lookup`` receives the request and returns the registration
    token to embed, or raises :class:`TokenLookupError`. ``register`` is
    awaited with the validated :class:`RegisterRequest` and the source IP.
    ``server_url`` is a fixed URL or a callable; when omitted, the URL is
    detected from trusted-proxy headers and requests from elsewhere get 500.
    Static configuration is validated here, so a bad ``repo``, ``port`` or
    ``server_url`` fails at startup rather than on every request.
    """
    validate_repo(repo)
    validate_port(port)
    if isinstance(server_url, str):
        server_url = validate_server_url(server_url, allow_insecure=allow_insecure)
    proxies = list(trusted_proxies)
    hosts = list(allowed_hosts)
    log = logger or _log
    router = APIRouter(tags=["install"])

    @router.get("/install.sh", summary="BONNIE install script", response_class=Response)
    async def install_script(request: Request) -> Response:
        try:
            token = token_lookup(request)
            if inspect.isawaitable(token):
                token = await token
        except TokenLookupError as exc:
            if exc.status_code in TOKEN_ERROR_STATUSES:
                return JSONResponse({"error": exc.message}, status_code=exc.status_code)
            log.error(
                "token lookup failed: status=%s error=%s", exc.status_code, exc.message
            )
            return JSONResponse({"error": "token lookup failed"}, status_code=500)
        if not isinstance(token, str) or not token:
            log.error("token lookup returned no token")
            return JSONResponse({"error": "token lookup failed"}, status_code=500)

        if callable(server_url):
            base: str | None = server_url(request)
        elif server_url:
            base = server_url
        else:
            base = detect_server_url(request, proxies, hosts)
        if not base:
            log.error(
                "install script requested without a server_url and not via a trusted proxy"
            )
            return JSONResponse(
                {"error": "server URL is not configured"}, status_code=500
            )

        try:
            script = render_install_script(
                token, base, repo=repo, port=port, allow_insecure=allow_insecure
            )
        except InvalidTokenError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except InstallScriptError as exc:
            log.error("install script render failed: %s", exc)
            return JSONResponse(
                {"error": "install script unavailable"}, status_code=500
            )
        # The script embeds a one-time token: never let a shared cache keep it.
        return Response(
            script,
            media_type="text/x-shellscript",
            headers={"Cache-Control": "no-store", "Vary": "*"},
        )

    @router.post("/agents/register", summary="Agent self-registration")
    async def agents_register(request: Request) -> JSONResponse:
        declared = request.headers.get("content-length")
        if (
            declared is not None
            and declared.isdigit()
            and int(declared) > MAX_REGISTER_BODY
        ):
            return JSONResponse({"error": "request body too large"}, status_code=413)
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_REGISTER_BODY:
                return JSONResponse(
                    {"error": "request body too large"}, status_code=413
                )
        source_ip = resolve_source_ip(
            peer_ip(request), request.headers.get("x-forwarded-for"), proxies
        )
        status, payload = await handle_register(
            body, source_ip, register, logger=logger
        )
        return JSONResponse(payload, status_code=status)

    return router
