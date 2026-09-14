"""Wire types for the BONNIE HTTP API.

Every model uses ``extra="ignore"`` so a newer BONNIE can add fields without
breaking older clients. Field names mirror BONNIE's Go structs; do not rename
without a coordinated server change.

Difference from Go, on purpose: ``disk: null`` and ``gpus: null`` stay
``None``. Go turned them into zero values, so "missing" looked like "0 GB".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

GPUVendor = Literal["nvidia", "amd", "intel", "none"]
BenchmarkKind = Literal["yaml", "container"]
EventType = Literal["status", "progress", "result", "error"]


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_wire(self) -> dict[str, Any]:
        """JSON-ready dict with Go ``omitempty`` semantics for optional fields."""
        data = self.model_dump(mode="json")
        return {
            k: v
            for k, v in data.items()
            if not (
                v is None or v == [] or v == {} or (v == "" and k in self.omit_empty())
            )
        }

    @classmethod
    def omit_empty(cls) -> frozenset[str]:
        return frozenset()


# --- health -------------------------------------------------------------------


class HealthStatus(_Wire):
    name: str
    healthy: bool
    error: str | None = None
    latency_ms: int = 0


class HealthReport(_Wire):
    healthy: bool = True
    version: str = ""
    checks: list[HealthStatus] = Field(default_factory=list)


# --- system & GPU -------------------------------------------------------------


class GPUInfo(_Wire):
    index: int
    name: str
    vendor: str
    memory_total_mib: int = 0
    memory_free_mib: int = 0
    utilization_percent: int = 0


class GPUSnapshot(_Wire):
    vendor: str
    gpus: list[GPUInfo] | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class GPUMetrics:
    """Raw Prometheus text exposition from ``/api/v1/gpu/metrics``."""

    content_type: str
    body: str


class SystemInfo(_Wire):
    hostname: str = ""
    os: str = ""
    arch: str = ""
    kernel: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    memory_mb: int = 0


class DiskUsage(_Wire):
    total_gb: float = 0
    used_gb: float = 0
    available_gb: float = 0
    used_percent: str = ""


class SystemInfoResponse(_Wire):
    system: SystemInfo
    disk: DiskUsage | None = None


# --- containers ---------------------------------------------------------------


class ContainerInfo(_Wire):
    id: str
    name: str = ""
    image: str = ""
    state: str = ""
    status: str = ""
    created: int = 0


class CreateContainerRequest(_Request):
    name: str
    image: str
    env: list[str] = Field(default_factory=list)
    mounts: list[str] = Field(default_factory=list)
    gpu: bool = False
    command: list[str] = Field(default_factory=list)


class ExecRequest(_Request):
    command: str
    args: list[str] = Field(default_factory=list)


class ExecResult(_Wire):
    exit_code: int = 0


# --- models -------------------------------------------------------------------


class FetchModelRequest(_Request):
    source: str
    model_id: str
    dest: str | None = None
    patterns: list[str] = Field(default_factory=list)
    mount_source: str | None = None
    subpath: str | None = None


class ModelEntry(_Wire):
    id: str
    source: str = ""
    model_id: str = ""
    path: str = ""
    size_bytes: int = 0
    files: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None
    last_used_at: datetime | None = None


# --- paired benchmark runs ----------------------------------------------------


class HealthCheck(_Request):
    path: str
    port: int
    timeout_seconds: int


class EngineSpec(_Request):
    image: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    ports: list[int] = Field(default_factory=list)
    model_path: str = ""
    health_check: HealthCheck

    @classmethod
    def omit_empty(cls) -> frozenset[str]:
        return frozenset()


class BenchmarkSpec(_Request):
    kind: BenchmarkKind
    image: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    config: Any | None = None
    yaml_spec: Any | None = None


class PairedRunSpec(_Request):
    run_id: str
    timeout_seconds: int = 0
    engine: EngineSpec
    benchmark: BenchmarkSpec

    @field_validator("run_id")
    @classmethod
    def _check_run_id(cls, value: str) -> str:
        if not RUN_ID_PATTERN.match(value):
            raise ValueError("run_id must match [a-zA-Z0-9_-]+")
        return value

    def to_wire(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["engine"] = self.engine.to_wire()
        data["benchmark"] = self.benchmark.to_wire()
        return data


class BenchmarkEvent(_Wire):
    type: EventType
    phase: str = ""
    source: str = ""
    line: str = ""
    timestamp: datetime | None = None
    results: Any | None = None
    duration_ms: int = 0
    error: str = ""


class BenchmarkResult(_Wire):
    phase: str = ""
    results: Any | None = None
    duration_ms: int = 0
