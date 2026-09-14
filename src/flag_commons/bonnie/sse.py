"""Tolerant Server-Sent Events parser plus Docker stdcopy demultiplexing.

The parser follows the SSE spec (``data:``, ``event:``, ``:`` comments,
multi-line ``data:`` joined with newlines, blank line ends a frame) and adds
one deliberate leniency for BONNIE as it exists today: **a non-field line
inside a frame is treated as a continuation of ``data``**. BONNIE writes raw
multi-line output after a single ``data: ``; the Go client silently dropped
every line after the first. Once BONNIE frames correctly this path is never
taken.

Container logs from BONNIE are not demultiplexed today, so each Docker
``stdcopy`` frame arrives with its 8-byte header (stream id, three zero
bytes, big-endian payload length). :func:`demux_stdcopy` strips those
headers when it recognises them, and is a no-op on clean input.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

STDCOPY_HEADER_LEN = 8
_STDCOPY_STREAMS = (0, 1, 2)


@dataclass
class SSEFrame:
    """One event-stream frame."""

    event: str = ""
    data: str = ""
    lines: list[str] = field(default_factory=list)


def looks_like_stdcopy(chunk: bytes) -> bool:
    """True when ``chunk`` starts with a Docker stdcopy header."""
    return (
        len(chunk) >= STDCOPY_HEADER_LEN
        and chunk[0] in _STDCOPY_STREAMS
        and chunk[1:4] == b"\x00\x00\x00"
    )


def demux_stdcopy(payload: bytes) -> bytes:
    """Strip every stdcopy frame header from ``payload``.

    Frames are walked using the declared length; if a header is malformed
    or the declared length runs past the end, the remainder is kept
    verbatim so no output is lost.
    """
    if not looks_like_stdcopy(payload):
        return payload
    out = bytearray()
    pos = 0
    while pos < len(payload):
        head = payload[pos : pos + STDCOPY_HEADER_LEN]
        if not looks_like_stdcopy(head):
            out += payload[pos:]
            break
        length = int.from_bytes(head[4:8], "big")
        start = pos + STDCOPY_HEADER_LEN
        out += payload[start : start + length]
        pos = start + length
    return bytes(out)


async def iter_lines(chunks: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Split a byte stream into lines on ``\\n`` (a trailing ``\\r`` is removed)."""
    buffer = b""
    async for chunk in chunks:
        buffer += chunk
        while True:
            idx = buffer.find(b"\n")
            if idx < 0:
                break
            line = buffer[:idx]
            buffer = buffer[idx + 1 :]
            yield line[:-1] if line.endswith(b"\r") else line
    if buffer:
        yield buffer[:-1] if buffer.endswith(b"\r") else buffer


async def parse_sse(
    chunks: AsyncIterator[bytes], *, demux: bool = False
) -> AsyncIterator[SSEFrame]:
    """Yield frames from a byte stream. ``demux`` strips stdcopy headers."""
    frame = SSEFrame()
    open_frame = False
    pending_header = b""  # partial stdcopy header split by a newline byte

    def flush() -> SSEFrame | None:
        nonlocal frame, open_frame
        if not open_frame:
            return None
        done = frame
        done.data = "\n".join(done.lines)
        frame = SSEFrame()
        open_frame = False
        return done

    async for raw in iter_lines(chunks):
        if raw == b"" and not pending_header:
            done = flush()
            if done is not None:
                yield done
            continue
        if raw.startswith(b":") and not open_frame:
            continue  # comment / keepalive
        if raw.startswith(b"event:"):
            frame.event = raw[6:].strip().decode("utf-8", "replace")
            open_frame = True
            continue
        if raw.startswith(b"data:"):
            payload = raw[5:]
            if payload.startswith(b" "):
                payload = payload[1:]
        elif open_frame or pending_header:
            payload = raw  # BONNIE leniency: continuation of the current data
        else:
            continue  # unknown field outside a frame: ignore per spec
        if demux:
            demuxed, pending_header = _demux_line(pending_header + payload)
            if demuxed is None:
                continue
            payload = demuxed
        open_frame = True
        frame.lines.append(payload.decode("utf-8", "replace"))
    done = flush()
    if done is not None:
        yield done


def _demux_line(payload: bytes) -> tuple[bytes | None, bytes]:
    """Demux one line; returns (text or None, header bytes to carry over).

    A stdcopy header whose length field contains 0x0a gets split across two
    lines by the line splitter; the partial header (fewer than 8 bytes,
    valid so far) is carried into the next line.
    """
    if len(payload) < STDCOPY_HEADER_LEN and payload and payload[0] in _STDCOPY_STREAMS:
        zeros = payload[1:4]
        if zeros == b"\x00\x00\x00"[: len(zeros)]:
            return None, payload + b"\n"
    return demux_stdcopy(payload), b""
