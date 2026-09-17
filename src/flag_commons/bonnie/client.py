"""Async HTTP client for the BONNIE agent API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from flag_commons.bonnie.errors import (
    MAX_ERROR_BODY,
    BonnieError,
    BonnieUnavailable,
    error_for,
)
from flag_commons.bonnie.models import (
    BenchmarkEvent,
    BenchmarkResult,
    ContainerInfo,
    CreateContainerRequest,
    ExecRequest,
    ExecResult,
    FetchModelRequest,
    GPUMetrics,
    GPUSnapshot,
    HealthReport,
    ModelEntry,
    PairedRunSpec,
    SystemInfoResponse,
)
from flag_commons.bonnie.sse import parse_sse

DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 3
DEFAULT_FETCH_TIMEOUT = 3600.0
RETRY_BASE_DELAY = 0.1
RETRY_MAX_DELAY = 5.0
RETRY_JITTER = 0.25
RETRY_AFTER_MAX = 30.0  # a server-supplied Retry-After is clamped to this
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})

_M = TypeVar("_M", bound=BaseModel)

_log = logging.getLogger(__name__)


def backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    """Delay before retry ``attempt`` (0-based): Retry-After, else jittered backoff."""
    if retry_after:
        try:
            secs = int(retry_after)
        except ValueError:
            secs = 0
        if secs > 0:
            return float(min(secs, RETRY_AFTER_MAX))
    base = min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * (2**attempt))
    jitter = (random.random() * 2 - 1) * RETRY_JITTER  # nosec B311
    return float(max(0.0, base * (1 + jitter)))


class BonnieClient:
    """Talks to one BONNIE agent.

    * ``Authorization: Bearer <token>`` is sent only when ``token`` is set.
    * Idempotent calls are retried on network errors and on 429/502/503/504
      with 100 ms·2ⁿ backoff (cap 5 s, ±25 % jitter, integer ``Retry-After``
      honoured); ``retries`` counts total attempts and there is no sleep after
      the final one. Non-idempotent calls (create, start/stop/restart, exec,
      benchmark) are never retried.
    * ``fetch_model`` uses its own long ``fetch_timeout`` and is not retried
      on timeout, so a slow download is never cancelled and restarted.
    * Streaming calls use no read timeout; cancel the task to stop them.
    """

    def __init__(  # nosec B107
        self,
        base_url: str,
        token: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        fetch_timeout: float = DEFAULT_FETCH_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = max(1, retries)
        self.timeout = timeout
        self.fetch_timeout = fetch_timeout
        self._token = token
        self._log = logger or _log
        if token and _plaintext_remote(self.base_url):
            self._log.warning(
                "bonnie: sending a bearer token over plaintext http: url=%s",
                self.base_url,
            )
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )
        self._sleep: Callable[[float], Any] = asyncio.sleep

    def __repr__(self) -> str:
        return f"BonnieClient(base_url={self.base_url!r})"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> BonnieClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- core request -----------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        op: str,
        idempotent: bool,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        retry_on_timeout: bool = True,
    ) -> httpx.Response:
        attempts = self.retries if idempotent else 1
        for attempt in range(attempts):
            last = attempt + 1 >= attempts
            if attempt:
                self._log.info(
                    "bonnie: retrying request: op=%s attempt=%d of=%d",
                    op,
                    attempt + 1,
                    attempts,
                )
            try:
                resp = await self._client.request(
                    method,
                    path,
                    json=json_body,
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except httpx.TimeoutException as exc:
                error: BonnieError = BonnieUnavailable(op, f"timeout: {exc}")
                if not retry_on_timeout or last:
                    self._fail(op, 1 if not retry_on_timeout else attempts, error)
                    raise error from exc
                await self._sleep(backoff_delay(attempt))
                continue
            except httpx.HTTPError as exc:
                error = BonnieUnavailable(op, str(exc) or exc.__class__.__name__)
                if last:
                    self._fail(op, attempts, error)
                    raise error from exc
                await self._sleep(backoff_delay(attempt))
                continue

            self._log.debug(
                "bonnie: request: op=%s method=%s path=%s status=%d",
                op,
                method,
                path,
                resp.status_code,
            )
            if resp.status_code < 300:
                return resp
            error = error_for(op, resp.status_code, resp.text[:MAX_ERROR_BODY])
            if idempotent and resp.status_code in RETRYABLE_STATUSES:
                if not last:
                    await self._sleep(
                        backoff_delay(attempt, resp.headers.get("Retry-After"))
                    )
                    continue
                self._fail(op, attempts, error)
            raise error
        raise BonnieUnavailable(
            op, "no attempts made"
        )  # pragma: no cover - retries >= 1

    def _fail(self, op: str, attempts: int, error: BonnieError) -> None:
        if attempts > 1:
            self._log.warning(
                "bonnie: request failed after retries: op=%s attempts=%d error=%s",
                op,
                attempts,
                error,
            )

    @asynccontextmanager
    async def _stream(
        self,
        method: str,
        path: str,
        *,
        op: str,
        json_body: dict[str, Any] | None = None,
    ) -> AsyncIterator[httpx.Response]:
        timeout = httpx.Timeout(
            connect=self.timeout, read=None, write=self.timeout, pool=self.timeout
        )
        try:
            async with self._client.stream(
                method,
                path,
                json=json_body,
                headers={"Accept": "text/event-stream"},
                timeout=timeout,
            ) as resp:
                if resp.status_code >= 300:
                    chunks = b""
                    async for chunk in resp.aiter_bytes():
                        chunks += chunk
                        if len(chunks) >= MAX_ERROR_BODY:
                            break
                    body = chunks[:MAX_ERROR_BODY].decode("utf-8", "replace")
                    raise error_for(op, resp.status_code, body)
                self._log.debug("bonnie: stream open: op=%s", op)
                yield resp
        except httpx.HTTPError as exc:
            raise BonnieUnavailable(op, str(exc) or exc.__class__.__name__) from exc

    @staticmethod
    def _json(resp: httpx.Response, op: str) -> Any:
        if not resp.content.strip():
            return None
        try:
            return resp.json()
        except ValueError as exc:
            raise BonnieError(
                op, resp.status_code, resp.text[:MAX_ERROR_BODY], f"decode {op}: {exc}"
            ) from exc

    @staticmethod
    def _decode(model: type[_M], data: Any, resp: httpx.Response, op: str) -> _M:
        """Validate ``data`` into ``model``; a wrong shape is a typed decode error."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise BonnieError(
                op,
                resp.status_code,
                resp.text[:MAX_ERROR_BODY],
                f"decode {op}: {exc.error_count()} invalid field(s)",
            ) from exc

    def _decode_list(
        self, model: type[_M], data: Any, resp: httpx.Response, op: str
    ) -> list[_M]:
        if data is None:
            return []
        if not isinstance(data, list):
            raise BonnieError(
                op,
                resp.status_code,
                resp.text[:MAX_ERROR_BODY],
                f"decode {op}: expected a list",
            )
        return [self._decode(model, item, resp, op) for item in data]

    # --- health, system, GPU ------------------------------------------------

    async def health(self) -> HealthReport:
        """Fetch the agent's health report. A 2xx with a non-report body is a decode error."""
        resp = await self._request("GET", "/health", op="health", idempotent=True)
        return self._decode(HealthReport, self._json(resp, "health"), resp, "health")

    async def system_info(self) -> SystemInfoResponse:
        resp = await self._request(
            "GET", "/api/v1/system/info", op="system info", idempotent=True
        )
        return self._decode(
            SystemInfoResponse, self._json(resp, "system info"), resp, "system info"
        )

    async def gpu_status(self) -> GPUSnapshot:
        resp = await self._request(
            "GET", "/api/v1/gpu/status", op="gpu status", idempotent=True
        )
        return self._decode(
            GPUSnapshot, self._json(resp, "gpu status"), resp, "gpu status"
        )

    async def gpu_metrics(self) -> GPUMetrics:
        resp = await self._request(
            "GET", "/api/v1/gpu/metrics", op="gpu metrics", idempotent=True
        )
        return GPUMetrics(
            content_type=resp.headers.get("Content-Type", ""), body=resp.text
        )

    # --- containers -------------------------------------------------------

    async def list_containers(self) -> list[ContainerInfo]:
        resp = await self._request(
            "GET", "/api/v1/containers", op="list containers", idempotent=True
        )
        return self._decode_list(
            ContainerInfo, self._json(resp, "list containers"), resp, "list containers"
        )

    async def inspect_container(self, container_id: str) -> dict[str, Any]:
        resp = await self._request(
            "GET",
            f"/api/v1/containers/{quote(container_id, safe='')}",
            op="inspect container",
            idempotent=True,
        )
        data = self._json(resp, "inspect container")
        return data if isinstance(data, dict) else {}

    async def create_container(self, req: CreateContainerRequest) -> str:
        resp = await self._request(
            "POST",
            "/api/v1/containers",
            op="create container",
            idempotent=False,
            json_body=req.to_wire(),
        )
        data = self._json(resp, "create container")
        container_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(container_id, str) or not container_id:
            raise BonnieError(
                "create container",
                resp.status_code,
                resp.text[:MAX_ERROR_BODY],
                "response has no id",
            )
        return container_id

    async def _container_action(self, container_id: str, action: str) -> None:
        await self._request(
            "POST",
            f"/api/v1/containers/{quote(container_id, safe='')}/{action}",
            op=f"{action} container",
            idempotent=False,
        )

    async def start_container(self, container_id: str) -> None:
        await self._container_action(container_id, "start")

    async def stop_container(self, container_id: str) -> None:
        await self._container_action(container_id, "stop")

    async def restart_container(self, container_id: str) -> None:
        await self._container_action(container_id, "restart")

    async def remove_container(self, container_id: str) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/containers/{quote(container_id, safe='')}",
            op="remove container",
            idempotent=True,
        )

    async def stream_container_logs(
        self, container_id: str, *, demux: bool = True
    ) -> AsyncIterator[str]:
        """Yield log lines from the container's SSE stream until it closes."""
        path = f"/api/v1/containers/{quote(container_id, safe='')}/logs"
        async with self._stream("GET", path, op="stream container logs") as resp:
            async for frame in parse_sse(resp.aiter_bytes(), demux=demux):
                for line in frame.lines:
                    yield line

    # --- exec -------------------------------------------------------------

    async def exec(
        self, req: ExecRequest, on_line: Callable[[str], None] | None = None
    ) -> ExecResult:
        """Run a command on the host, delivering output lines via ``on_line``.

        BONNIE currently always reports ``exit_code: 0``; the value is passed
        through as received.
        """
        result = ExecResult()
        async with self._stream(
            "POST", "/api/v1/exec", op="exec", json_body=req.to_wire()
        ) as resp:
            async for frame in parse_sse(resp.aiter_bytes()):
                if frame.event == "done":
                    payload = _try_json(frame.data)
                    if isinstance(payload, dict):
                        result = ExecResult.model_validate(payload)
                        if payload.get("error"):
                            raise BonnieError(
                                "exec", None, frame.data, str(payload["error"])
                            )
                    continue
                payload = _try_json(frame.data)
                if isinstance(payload, dict) and payload.get("error"):
                    raise BonnieError("exec", None, frame.data, str(payload["error"]))
                if on_line is not None:
                    for line in frame.lines:
                        on_line(line)
        return result

    # --- models -----------------------------------------------------------

    async def fetch_model(self, req: FetchModelRequest) -> ModelEntry:
        resp = await self._request(
            "POST",
            "/api/v1/models/fetch",
            op="fetch model",
            idempotent=True,
            json_body=req.to_wire(),
            timeout=self.fetch_timeout,
            retry_on_timeout=False,
        )
        return self._decode(
            ModelEntry, self._json(resp, "fetch model"), resp, "fetch model"
        )

    async def list_models(self) -> list[ModelEntry]:
        resp = await self._request(
            "GET", "/api/v1/models", op="list models", idempotent=True
        )
        return self._decode_list(
            ModelEntry, self._json(resp, "list models"), resp, "list models"
        )

    async def delete_model(self, model_id: str) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/models/{quote(model_id, safe='')}",
            op="delete model",
            idempotent=True,
        )

    # --- paired benchmark runs --------------------------------------------

    async def iter_benchmark_events(
        self, spec: PairedRunSpec
    ) -> AsyncIterator[BenchmarkEvent]:
        """Yield every well-formed event of a paired run; malformed ones are skipped."""
        async with self._stream(
            "POST", "/api/v1/benchmark", op="run benchmark", json_body=spec.to_wire()
        ) as resp:
            async for frame in parse_sse(resp.aiter_bytes()):
                payload = _try_json(frame.data)
                if not isinstance(payload, dict):
                    self._log.debug(
                        "bonnie: skipping malformed sse event: op=run benchmark"
                    )
                    continue
                try:
                    yield BenchmarkEvent.model_validate(payload)
                except ValidationError as exc:
                    self._log.debug(
                        "bonnie: skipping malformed sse event: op=run benchmark error=%s",
                        exc,
                    )

    async def run_benchmark(
        self,
        spec: PairedRunSpec,
        on_event: Callable[[BenchmarkEvent], None] | None = None,
    ) -> BenchmarkResult:
        """Run a paired benchmark and return the terminal ``result`` event.

        An ``error`` event fails the run only if no result was seen; a stream
        that ends without a result is an error.
        """
        result: BenchmarkResult | None = None
        stream_error: BonnieError | None = None
        async for event in self.iter_benchmark_events(spec):
            if on_event is not None:
                on_event(event)
            if event.type == "result":
                result = BenchmarkResult(
                    phase=event.phase,
                    results=event.results,
                    duration_ms=event.duration_ms,
                )
            elif event.type == "error":
                stream_error = BonnieError(
                    "run benchmark", None, "", f"benchmark {event.phase}: {event.error}"
                )
        if result is None:
            if stream_error is not None:
                raise stream_error
            raise BonnieError(
                "run benchmark", None, "", "benchmark stream ended without result"
            )
        return result


def _plaintext_remote(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "http" and parts.hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    )


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None
