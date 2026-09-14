"""Port of Go sse_test.go plus the tolerant-framing and stdcopy fixes."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from flag_commons.bonnie import SSEFrame, demux_stdcopy, parse_sse
from flag_commons.bonnie.sse import iter_lines, looks_like_stdcopy

pytestmark = pytest.mark.anyio


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def _frames(*parts: bytes, demux: bool = False) -> list[SSEFrame]:
    return [f async for f in parse_sse(_chunks(*parts), demux=demux)]


def _hdr(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


async def test_basic_frames() -> None:
    # Go: TestParseSSE_BasicFrames
    frames = await _frames(b"data: one\n\ndata: two\n\n")
    assert [f.data for f in frames] == ["one", "two"]
    assert all(f.event == "" for f in frames)


async def test_multiline_data() -> None:
    # Go: TestParseSSE_MultilineData
    frames = await _frames(b"data: line1\ndata: line2\n\n")
    assert frames[0].data == "line1\nline2"
    assert frames[0].lines == ["line1", "line2"]


async def test_comments_ignored() -> None:
    # Go: TestParseSSE_Comments
    frames = await _frames(b": keepalive\n\n: another\ndata: x\n\n")
    assert [f.data for f in frames] == ["x"]


async def test_event_and_data() -> None:
    # Go: TestParseSSE_EventAndData
    frames = await _frames(b'event: done\ndata: {"exit_code": 0}\n\n')
    assert frames[0].event == "done"
    assert frames[0].data == '{"exit_code": 0}'


async def test_no_trailing_blank_line() -> None:
    # Go: TestParseSSE_NoTrailingBlankLine
    frames = await _frames(b"data: last")
    assert [f.data for f in frames] == ["last"]


async def test_chunk_boundaries_and_crlf() -> None:
    frames = await _frames(b"da", b"ta: sp", b"lit\r\n\r\ndata: b\n\n")
    assert [f.data for f in frames] == ["split", "b"]


async def test_data_without_space_and_unknown_fields() -> None:
    frames = await _frames(b"id: 7\nretry: 100\ndata:tight\n\n")
    assert [f.data for f in frames] == ["tight"]
    assert (await _frames(b"junk outside any frame\n\n")) == []


async def test_bonnie_raw_multiline_continuation() -> None:
    # FIX: BONNIE writes raw multi-line output after one "data: " prefix.
    raw = b"data: first line\nsecond line\nthird line\n\n"
    frames = await _frames(raw)
    assert frames[0].lines == ["first line", "second line", "third line"]


async def test_comment_inside_frame_is_continuation() -> None:
    frames = await _frames(b"data: a\n: not a comment here\n\n")
    assert frames[0].lines == ["a", ": not a comment here"]


def test_demux_stdcopy() -> None:
    payload = _hdr(1, b"hello\n") + _hdr(2, b"err") + _hdr(1, b"world")
    assert demux_stdcopy(payload) == b"hello\nerrworld"
    assert demux_stdcopy(b"plain text") == b"plain text"
    assert looks_like_stdcopy(b"\x01\x00\x00\x00\x00\x00\x00\x05")
    assert not looks_like_stdcopy(b"\x09\x00\x00\x00\x00\x00\x00\x05")


def test_demux_keeps_remainder_on_bad_length() -> None:
    broken = bytes([1, 0, 0, 0, 0, 0, 0, 50]) + b"short"
    assert demux_stdcopy(broken) == b"short"
    mixed = _hdr(1, b"ok") + b"trailing junk"
    assert demux_stdcopy(mixed) == b"oktrailing junk"


async def test_stream_logs_strips_headers_when_demux() -> None:
    raw = b"data: " + _hdr(1, b"line one") + b"\n" + _hdr(1, b"line two") + b"\n\n"
    frames = await _frames(raw, demux=True)
    assert frames[0].lines == ["line one", "line two"]
    frames = await _frames(raw, demux=False)
    assert frames[0].lines[0].startswith("\x01\x00\x00\x00")


async def test_demux_header_split_by_newline_byte() -> None:
    # A payload of exactly 10 bytes has length byte 0x0a, which the line
    # splitter treats as a newline inside the header.
    payload = b"0123456789"
    assert len(payload) == 10
    raw = b"data: " + _hdr(1, payload) + b"\n\n"
    frames = await _frames(raw, demux=True)
    assert frames[0].lines == ["0123456789"]


async def test_demux_is_noop_on_clean_input() -> None:
    frames = await _frames(b"data: clean\n\n", demux=True)
    assert frames[0].lines == ["clean"]


async def test_iter_lines() -> None:
    lines = [ln async for ln in iter_lines(_chunks(b"a\r\nb\n", b"c"))]
    assert lines == [b"a", b"b", b"c"]


async def test_callback_style_cancellation_via_break() -> None:
    # Go: TestParseSSE_ContextCancel / ForwardsCallbackError — consumers stop by breaking.
    seen = []
    async for frame in parse_sse(_chunks(b"data: 1\n\ndata: 2\n\ndata: 3\n\n")):
        seen.append(frame.data)
        if frame.data == "2":
            break
    assert seen == ["1", "2"]
