"""Wire types: omitempty, extra=ignore, null handling, run_id validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flag_commons.bonnie import (
    BenchmarkSpec,
    CreateContainerRequest,
    EngineSpec,
    FetchModelRequest,
    GPUSnapshot,
    HealthCheck,
    PairedRunSpec,
    SystemInfoResponse,
)


def test_create_container_omits_empty_lists_but_keeps_gpu() -> None:
    wire = CreateContainerRequest(name="n", image="img").to_wire()
    assert wire == {"name": "n", "image": "img", "gpu": False}
    wire = CreateContainerRequest(
        name="n", image="img", env=["A=1"], gpu=True, command=["sh"]
    ).to_wire()
    assert wire == {
        "name": "n",
        "image": "img",
        "env": ["A=1"],
        "gpu": True,
        "command": ["sh"],
    }


def test_fetch_model_omits_none() -> None:
    assert FetchModelRequest(source="hf", model_id="m").to_wire() == {
        "source": "hf",
        "model_id": "m",
    }
    assert FetchModelRequest(
        source="hf", model_id="m", dest="/x", patterns=["*.gguf"]
    ).to_wire() == {
        "source": "hf",
        "model_id": "m",
        "dest": "/x",
        "patterns": ["*.gguf"],
    }


def test_request_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CreateContainerRequest(name="n", image="i", bogus=1)  # type: ignore[call-arg]


def test_response_models_ignore_unknown_fields() -> None:
    snap = GPUSnapshot.model_validate(
        {
            "vendor": "nvidia",
            "gpus": None,
            "timestamp": "2026-01-01T00:00:00Z",
            "new": 1,
        }
    )
    assert snap.gpus is None  # FIX: null stays None, not []
    info = SystemInfoResponse.model_validate(
        {"system": {"hostname": "h"}, "disk": None}
    )
    assert info.disk is None
    assert info.system.hostname == "h"


def _spec(run_id: str = "run-1") -> PairedRunSpec:
    return PairedRunSpec(
        run_id=run_id,
        timeout_seconds=60,
        engine=EngineSpec(
            image="vllm",
            model_path="/m",
            health_check=HealthCheck(path="/health", port=8000, timeout_seconds=30),
        ),
        benchmark=BenchmarkSpec(kind="yaml", yaml_spec={"a": 1}),
    )


def test_paired_run_spec_wire_shape() -> None:
    wire = _spec().to_wire()
    assert wire["run_id"] == "run-1"
    assert wire["engine"] == {
        "image": "vllm",
        "model_path": "/m",
        "health_check": {"path": "/health", "port": 8000, "timeout_seconds": 30},
    }
    # Go had no omitempty on image, so an empty string is sent.
    assert wire["benchmark"] == {"kind": "yaml", "image": "", "yaml_spec": {"a": 1}}


@pytest.mark.parametrize("bad", ["", "has space", "slash/x", "dot.x"])
def test_run_id_validation(bad: str) -> None:
    with pytest.raises(ValidationError, match="run_id"):
        _spec(bad)


def test_benchmark_kind_is_restricted() -> None:
    with pytest.raises(ValidationError):
        BenchmarkSpec(kind="binary")  # type: ignore[arg-type]
