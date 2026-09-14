"""Port of Go logging_test.go and context_test.go."""

from __future__ import annotations

import io
import json
import logging

import pytest

from flag_commons import logging as flag_logging


def _setup(
    fmt: str = "text", level: str = "info"
) -> tuple[io.StringIO, logging.Logger]:
    buf = io.StringIO()
    logger = flag_logging.setup_logging("test-svc", level=level, fmt=fmt, stream=buf)
    return buf, logger


def test_new_text_format() -> None:
    # Go: TestNew_TextFormat
    buf, logger = _setup("text")
    logger.info("hello")
    out = buf.getvalue()
    assert "component=test-svc" in out
    assert "msg=hello" in out
    assert out.startswith("time=")
    assert "level=INFO" in out


def test_new_json_format() -> None:
    # Go: TestNew_JSONFormat
    buf, logger = _setup("json")
    logger.info("hello")
    out = buf.getvalue()
    assert '"component":"test-svc"' in out
    assert '"msg":"hello"' in out
    record = json.loads(out)
    assert set(record) >= {"time", "level", "msg", "component", "version"}
    assert record["level"] == "INFO"


def test_new_level_filtering() -> None:
    # Go: TestNew_LevelFiltering
    buf, logger = _setup("text", level="warn")
    logger.info("should not appear")
    assert buf.getvalue() == ""
    logger.warning("should appear")
    assert "should appear" in buf.getvalue()
    assert "level=WARN" in buf.getvalue()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("debug", logging.DEBUG),
        ("DEBUG", logging.DEBUG),
        ("info", logging.INFO),
        ("warn", logging.WARNING),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
        ("unknown", logging.INFO),
        ("", logging.INFO),
        ("  Error  ", logging.ERROR),
    ],
)
def test_parse_level(value: str, expected: int) -> None:
    # Go: TestParseLevel
    assert flag_logging.parse_level(value) == expected


def test_unknown_format_falls_back_to_text() -> None:
    buf, logger = _setup("yaml")
    logger.info("hello")
    assert "msg=hello" in buf.getvalue()


def test_bind_injects_fields_and_restores() -> None:
    # Replaces Go: TestWithContext_FromContext
    buf, logger = _setup("json")
    with flag_logging.bind(request_id="r1"):
        logger.info("inside")
        with flag_logging.bind(user="u1"):
            logger.info("nested")
    logger.info("outside")
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert lines[0]["request_id"] == "r1" and "user" not in lines[0]
    assert lines[1]["request_id"] == "r1" and lines[1]["user"] == "u1"
    assert "request_id" not in lines[2]
    assert flag_logging.bound_fields() == {}


def test_extra_fields_are_rendered() -> None:
    buf, logger = _setup("json")
    logger.info("with extras", extra={"agent": "gpu-01", "count": 3})
    record = json.loads(buf.getvalue())
    assert record["agent"] == "gpu-01"
    assert record["count"] == 3


def test_text_quotes_values_with_spaces() -> None:
    buf, logger = _setup("text")
    logger.info("two words", extra={"path": "/a b"})
    out = buf.getvalue()
    assert 'msg="two words"' in out
    assert 'path="/a b"' in out


def test_exception_is_included() -> None:
    buf, logger = _setup("json")
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
    record = json.loads(buf.getvalue())
    assert record["level"] == "ERROR"
    assert "ValueError: boom" in record["exception"]


def test_setup_twice_replaces_handler() -> None:
    first, _ = _setup("text")
    second, logger = _setup("json")
    logger.info("hello")
    assert first.getvalue() == ""
    assert '"msg":"hello"' in second.getvalue()
    tagged = [
        h
        for h in logging.getLogger().handlers
        if getattr(h, "_flag_commons_handler", False)
    ]
    assert len(tagged) == 1


def test_other_loggers_share_the_handler() -> None:
    buf, _ = _setup("json")
    logging.getLogger("kitt.engines").info("from another module")
    record = json.loads(buf.getvalue())
    assert record["component"] == "test-svc"
    assert record["logger"] == "kitt.engines"


@pytest.mark.parametrize(
    ("levelno", "expected"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.WARNING, "WARN"),
        (logging.CRITICAL, "ERROR"),
        (5, "DEBUG"),
        (25, "INFO"),
        (35, "WARN"),
        (45, "ERROR"),
    ],
)
def test_level_name(levelno: int, expected: str) -> None:
    assert flag_logging.level_name(levelno) == expected


def test_uvicorn_log_config_propagates() -> None:
    cfg = flag_logging.uvicorn_log_config("svc", level="debug")
    assert cfg["disable_existing_loggers"] is False
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert cfg["loggers"][name]["propagate"] is True
        assert cfg["loggers"][name]["level"] == logging.DEBUG
