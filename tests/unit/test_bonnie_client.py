"""Port of Go client_test.go, models_test.go and benchmark_test.go via respx."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx

from flag_commons.bonnie import (
    BenchmarkEvent,
    BenchmarkSpec,
    BonnieBadRequest,
    BonnieClient,
    BonnieError,
    BonnieNotFound,
    BonnieUnauthorized,
    BonnieUnavailable,
    CreateContainerRequest,
    EngineSpec,
    ExecRequest,
    FetchModelRequest,
    HealthCheck,
    PairedRunSpec,
    backoff_delay,
)

pytestmark = pytest.mark.anyio

BASE = "http://bonnie.test:7777"


async def _sse(*frames: str) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame.encode()


def _stream(*frames: str) -> httpx.Response:
    return httpx.Response(
        200,
        stream=_ByteStream(_sse(*frames)),
        headers={"Content-Type": "text/event-stream"},
    )


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, source: AsyncIterator[bytes]) -> None:
        self._source = source

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._source:
            yield chunk


@pytest.fixture
def client() -> Iterator[BonnieClient]:
    c = BonnieClient(BASE + "/", "tok", retries=3)

    async def no_sleep(_d: float) -> None:
        return None

    c._sleep = no_sleep
    yield c
    asyncio.run(c.aclose())


def test_new_trims_trailing_slash(client: BonnieClient) -> None:
    # Go: TestNew_TrimsTrailingSlash
    assert client.base_url == BASE
    assert "tok" not in repr(client)


@respx.mock
async def test_health_ok(client: BonnieClient) -> None:
    # Go: TestHealth_OK
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "healthy": True,
                "version": "0.2.1 (commit: x, built: y)",
                "checks": [],
            },
        )
    )
    report = await client.health()
    assert report.healthy and report.version.startswith("0.2.1")
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_health_non_json_body_is_still_ok(client: BonnieClient) -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, text="ok"))
    assert (await client.health()).healthy is True


@respx.mock
async def test_no_auth_header_without_token() -> None:
    route = respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={}))
    async with BonnieClient(BASE) as c:
        await c.health()
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, BonnieUnauthorized),
        (403, BonnieUnauthorized),
        (404, BonnieNotFound),
        (400, BonnieBadRequest),
        (500, BonnieError),
    ],
)
async def test_health_error_classes(
    client: BonnieClient, status: int, exc: type[BonnieError]
) -> None:
    # Go: TestHealth_Unauthorized / _NotFound / _BadRequest, TestBonnieError_Fields
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(status, json={"error": "nope"})
    )
    with pytest.raises(exc) as info:
        await client.health()
    assert info.value.status == status
    assert info.value.message == "nope"
    assert info.value.op == "health"
    assert f"returned {status}" in str(info.value)


@respx.mock
async def test_system_info(client: BonnieClient) -> None:
    # Go: TestSystemInfo
    respx.get(f"{BASE}/api/v1/system/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "system": {"hostname": "gpu-01", "cpu_cores": 32, "memory_mb": 65536},
                "disk": {
                    "total_gb": 1000.0,
                    "used_gb": 10.5,
                    "available_gb": 989.5,
                    "used_percent": "1%",
                },
            },
        )
    )
    info = await client.system_info()
    assert info.system.hostname == "gpu-01"
    assert info.disk is not None and info.disk.used_gb == 10.5


@respx.mock
async def test_gpu_status(client: BonnieClient) -> None:
    # Go: TestGPUStatus
    respx.get(f"{BASE}/api/v1/gpu/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "vendor": "nvidia",
                "gpus": [
                    {
                        "index": 0,
                        "name": "RTX",
                        "vendor": "nvidia",
                        "memory_total_mib": 24576,
                        "memory_free_mib": 1024,
                        "utilization_percent": 55,
                    }
                ],
                "timestamp": "2026-09-14T00:00:00Z",
            },
        )
    )
    snap = await client.gpu_status()
    assert snap.gpus is not None and snap.gpus[0].utilization_percent == 55


@respx.mock
async def test_gpu_metrics(client: BonnieClient) -> None:
    # Go: TestGPUMetrics
    respx.get(f"{BASE}/api/v1/gpu/metrics").mock(
        return_value=httpx.Response(
            200,
            text="gpu_util 55\n",
            headers={"Content-Type": "text/plain; version=0.0.4"},
        )
    )
    metrics = await client.gpu_metrics()
    assert metrics.body == "gpu_util 55\n"
    assert metrics.content_type.startswith("text/plain")


@respx.mock
async def test_list_and_inspect_containers(client: BonnieClient) -> None:
    # Go: TestListContainers, TestInspectContainer
    respx.get(f"{BASE}/api/v1/containers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc",
                    "name": "env-1",
                    "image": "img",
                    "state": "running",
                    "status": "Up 2h",
                    "created": 1,
                }
            ],
        )
    )
    containers = await client.list_containers()
    assert containers[0].id == "abc" and containers[0].state == "running"
    respx.get(f"{BASE}/api/v1/containers/abc%2Fx").mock(
        return_value=httpx.Response(200, json={"Id": "abc", "State": {"Running": True}})
    )
    raw = await client.inspect_container("abc/x")
    assert raw["State"]["Running"] is True
    respx.get(f"{BASE}/api/v1/containers").mock(
        return_value=httpx.Response(200, json=None)
    )
    assert await client.list_containers() == []


@respx.mock
async def test_create_container(client: BonnieClient) -> None:
    # Go: TestCreateContainer
    route = respx.post(f"{BASE}/api/v1/containers").mock(
        return_value=httpx.Response(201, json={"id": "new-id"})
    )
    cid = await client.create_container(
        CreateContainerRequest(name="n", image="img", gpu=True)
    )
    assert cid == "new-id"
    assert json.loads(route.calls[0].request.content) == {
        "name": "n",
        "image": "img",
        "gpu": True,
    }
    respx.post(f"{BASE}/api/v1/containers").mock(
        return_value=httpx.Response(201, json={})
    )
    with pytest.raises(BonnieError, match="no id"):
        await client.create_container(CreateContainerRequest(name="n", image="img"))


@respx.mock
async def test_container_actions(client: BonnieClient) -> None:
    # Go: TestContainerActions
    for action in ("start", "stop", "restart"):
        route = respx.post(f"{BASE}/api/v1/containers/c1/{action}").mock(
            return_value=httpx.Response(204)
        )
        await getattr(client, f"{action}_container")("c1")
        assert route.called


@respx.mock
async def test_remove_container(client: BonnieClient) -> None:
    # Go: TestRemoveContainer
    route = respx.delete(f"{BASE}/api/v1/containers/c1").mock(
        return_value=httpx.Response(204)
    )
    await client.remove_container("c1")
    assert route.called


@respx.mock
async def test_stream_container_logs(client: BonnieClient) -> None:
    # Go: TestStreamContainerLogs (+ raw multi-line FIX)
    respx.get(f"{BASE}/api/v1/containers/c1/logs").mock(
        return_value=_stream(
            "data: line 1\n\n", ": keepalive\n", "data: line 2\nline 3\n\n"
        )
    )
    lines = [ln async for ln in client.stream_container_logs("c1")]
    assert lines == ["line 1", "line 2", "line 3"]


@respx.mock
async def test_stream_error_status(client: BonnieClient) -> None:
    respx.get(f"{BASE}/api/v1/containers/c1/logs").mock(
        return_value=httpx.Response(404, json={"error": "no such container"})
    )
    with pytest.raises(BonnieNotFound, match="no such container"):
        async for _ in client.stream_container_logs("c1"):
            pass


@respx.mock
async def test_stream_transport_error(client: BonnieClient) -> None:
    respx.get(f"{BASE}/api/v1/containers/c1/logs").mock(
        side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(BonnieUnavailable):
        async for _ in client.stream_container_logs("c1"):
            pass


@respx.mock
async def test_exec(client: BonnieClient) -> None:
    # Go: TestExec
    route = respx.post(f"{BASE}/api/v1/exec").mock(
        return_value=_stream(
            "data: out1\n\n",
            "data: out2\n\n",
            'event: done\ndata: {"exit_code": 3}\n\n',
        )
    )
    lines: list[str] = []
    result = await client.exec(ExecRequest(command="ls", args=["-l"]), lines.append)
    assert lines == ["out1", "out2"]
    assert result.exit_code == 3
    assert json.loads(route.calls[0].request.content) == {
        "command": "ls",
        "args": ["-l"],
    }


@respx.mock
async def test_exec_error_envelope(client: BonnieClient) -> None:
    # Go: TestExec_ErrorEnvelope
    respx.post(f"{BASE}/api/v1/exec").mock(
        return_value=_stream('data: {"error": "command not found"}\n\n')
    )
    with pytest.raises(BonnieError, match="command not found"):
        await client.exec(ExecRequest(command="nope"))
    respx.post(f"{BASE}/api/v1/exec").mock(
        return_value=_stream('event: done\ndata: {"exit_code": 1, "error": "boom"}\n\n')
    )
    with pytest.raises(BonnieError, match="boom"):
        await client.exec(ExecRequest(command="x"))


@respx.mock
async def test_exec_without_done_event_returns_zero(client: BonnieClient) -> None:
    respx.post(f"{BASE}/api/v1/exec").mock(
        return_value=_stream("data: only output\n\n")
    )
    assert (await client.exec(ExecRequest(command="x"))).exit_code == 0


@respx.mock
async def test_retry_503_then_success(client: BonnieClient) -> None:
    # Go: TestRetry_503ThenSuccess
    route = respx.get(f"{BASE}/health").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={})]
    )
    await client.health()
    assert route.call_count == 2


@respx.mock
async def test_retry_retry_after(
    client: BonnieClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Go: TestRetry_RetryAfter
    sleeps: list[float] = []

    async def record(d: float) -> None:
        sleeps.append(d)

    client._sleep = record
    respx.get(f"{BASE}/health").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={}),
        ]
    )
    await client.health()
    assert sleeps == [2.0]


@respx.mock
async def test_retry_exhausted_raises_last_error(client: BonnieClient) -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(502, text="bad gateway")
    )
    with pytest.raises(BonnieError) as info:
        await client.health()
    assert info.value.status == 502
    assert route.call_count == 3  # retries counts total attempts


@respx.mock
async def test_retry_network_errors_then_unavailable(client: BonnieClient) -> None:
    sleeps: list[float] = []

    async def record(d: float) -> None:
        sleeps.append(d)

    client._sleep = record
    route = respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(BonnieUnavailable, match="refused"):
        await client.health()
    assert route.call_count == 3
    assert len(sleeps) == 2  # FIX: no sleep after the final attempt


@respx.mock
async def test_retry_non_idempotent_not_retried(client: BonnieClient) -> None:
    # Go: TestRetry_NonIdempotentNotRetried
    route = respx.post(f"{BASE}/api/v1/containers").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(BonnieError):
        await client.create_container(CreateContainerRequest(name="n", image="i"))
    assert route.call_count == 1
    route = respx.post(f"{BASE}/api/v1/containers/c1/start").mock(
        side_effect=httpx.ConnectError("x")
    )
    with pytest.raises(BonnieUnavailable):
        await client.start_container("c1")
    assert route.call_count == 1


@respx.mock
async def test_retry_4xx_not_retried(client: BonnieClient) -> None:
    # Go: TestRetry_4xxNotRetried
    route = respx.get(f"{BASE}/health").mock(return_value=httpx.Response(404))
    with pytest.raises(BonnieNotFound):
        await client.health()
    assert route.call_count == 1


def test_backoff_delay() -> None:
    assert backoff_delay(0, "7") == 7.0
    assert backoff_delay(0, "junk") <= 0.125
    for attempt, base in enumerate([0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 5.0, 5.0]):
        d = backoff_delay(attempt)
        assert base * 0.75 <= d <= base * 1.25


@respx.mock
async def test_fetch_model(client: BonnieClient) -> None:
    # Go: TestFetchModel
    route = respx.post(f"{BASE}/api/v1/models/fetch").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "m1",
                "source": "hf",
                "model_id": "org/model",
                "path": "/models/m1",
                "size_bytes": 10,
                "files": ["a.gguf"],
                "fetched_at": "2026-01-01T00:00:00Z",
                "last_used_at": "2026-01-01T00:00:00Z",
            },
        )
    )
    entry = await client.fetch_model(
        FetchModelRequest(source="hf", model_id="org/model")
    )
    assert entry.id == "m1" and entry.files == ["a.gguf"]
    assert route.calls[0].request.extensions["timeout"]["read"] == client.fetch_timeout


@respx.mock
async def test_fetch_model_not_retried_on_timeout(client: BonnieClient) -> None:
    # FIX: Go's 30 s timeout cancelled the download and retried it.
    route = respx.post(f"{BASE}/api/v1/models/fetch").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(BonnieUnavailable, match="timeout"):
        await client.fetch_model(FetchModelRequest(source="hf", model_id="m"))
    assert route.call_count == 1


@respx.mock
async def test_fetch_model_server_error_retries(client: BonnieClient) -> None:
    # Go: TestFetchModel_ServerError (5xx retryable statuses still retry)
    route = respx.post(f"{BASE}/api/v1/models/fetch").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(BonnieError):
        await client.fetch_model(FetchModelRequest(source="hf", model_id="m"))
    assert route.call_count == 3


@respx.mock
async def test_list_and_delete_models(client: BonnieClient) -> None:
    # Go: TestListModels, TestListModels_Empty, TestDeleteModel, TestDeleteModel_NotFound
    respx.get(f"{BASE}/api/v1/models").mock(
        return_value=httpx.Response(200, json=[{"id": "m1"}])
    )
    assert [m.id for m in await client.list_models()] == ["m1"]
    respx.get(f"{BASE}/api/v1/models").mock(return_value=httpx.Response(200, json=[]))
    assert await client.list_models() == []
    respx.delete(f"{BASE}/api/v1/models/m1").mock(return_value=httpx.Response(204))
    await client.delete_model("m1")
    respx.delete(f"{BASE}/api/v1/models/m2").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    with pytest.raises(BonnieNotFound):
        await client.delete_model("m2")


def _spec() -> PairedRunSpec:
    return PairedRunSpec(
        run_id="r1",
        engine=EngineSpec(
            image="e", health_check=HealthCheck(path="/", port=1, timeout_seconds=1)
        ),
        benchmark=BenchmarkSpec(kind="container", image="b"),
    )


@respx.mock
async def test_run_benchmark(client: BonnieClient) -> None:
    # Go: TestRunBenchmark, TestRunBenchmark_NilCallback
    respx.post(f"{BASE}/api/v1/benchmark").mock(
        return_value=_stream(
            'data: {"type": "status", "phase": "engine"}\n\n',
            "data: not json\n\n",
            'data: {"type": "bogus"}\n\n',
            'data: {"type": "result", "phase": "benchmark", "results": {"tps": 12.5}, "duration_ms": 900}\n\n',
        )
    )
    events: list[BenchmarkEvent] = []
    result = await client.run_benchmark(_spec(), events.append)
    assert [e.type for e in events] == ["status", "result"]
    assert result.results == {"tps": 12.5} and result.duration_ms == 900
    respx.post(f"{BASE}/api/v1/benchmark").mock(
        return_value=_stream('data: {"type": "result", "phase": "benchmark"}\n\n')
    )
    assert (await client.run_benchmark(_spec())).phase == "benchmark"


@respx.mock
async def test_run_benchmark_error_and_no_result(client: BonnieClient) -> None:
    # Go: TestRunBenchmark_Error, TestRunBenchmark_NoResult
    respx.post(f"{BASE}/api/v1/benchmark").mock(
        return_value=_stream(
            'data: {"type": "error", "phase": "engine", "error": "OOM"}\n\n'
        )
    )
    with pytest.raises(BonnieError, match="benchmark engine: OOM"):
        await client.run_benchmark(_spec())
    respx.post(f"{BASE}/api/v1/benchmark").mock(
        return_value=_stream('data: {"type": "status"}\n\n')
    )
    with pytest.raises(BonnieError, match="without result"):
        await client.run_benchmark(_spec())
    respx.post(f"{BASE}/api/v1/benchmark").mock(
        return_value=_stream(
            'data: {"type": "result", "results": 1}\n\n',
            'data: {"type": "error", "error": "late"}\n\n',
        )
    )
    assert (
        await client.run_benchmark(_spec())
    ).results == 1  # error after a result is ignored


@respx.mock
async def test_malformed_json_response(client: BonnieClient) -> None:
    respx.get(f"{BASE}/api/v1/system/info").mock(
        return_value=httpx.Response(200, text="<html>")
    )
    with pytest.raises(BonnieError, match="decode"):
        await client.system_info()


async def test_unavailable_error_shape() -> None:
    err = BonnieUnavailable("health", "boom")
    assert err.status is None and str(err) == "bonnie: health: boom"
    assert BonnieError("op", 500, "x" * 5000).body == "x" * 4096
