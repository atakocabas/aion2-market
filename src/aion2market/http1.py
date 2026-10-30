"""Minimal HTTP/1.1 message parser for decrypted streams (Content-Length, chunked, gzip/deflate)."""
from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass


@dataclass(frozen=True)
class HttpMessage:
    head: str                  # start line + header lines
    headers: dict[str, str]    # lower-cased names
    body: bytes                # de-chunked and decompressed

    @property
    def start_line(self) -> str:
        return self.head.split("\r\n", 1)[0]

    @property
    def status(self) -> int:
        """Status code of a response (0 for a request)."""
        parts = self.start_line.split()
        return int(parts[1]) if len(parts) > 1 and parts[0].startswith("HTTP/") else 0

    @property
    def path(self) -> str:
        """Request path without the query string ("" for a response)."""
        parts = self.start_line.split()
        return parts[1].split("?", 1)[0] if len(parts) > 1 and not parts[0].startswith("HTTP/") else ""


def _dechunk(b: bytes, i: int) -> tuple[bytes, int] | None:
    out = bytearray()
    while True:
        j = b.find(b"\r\n", i)
        if j < 0:
            return None
        size = int(b[i:j].split(b";")[0] or b"0", 16)
        if size == 0:
            end = b.find(b"\r\n\r\n", j)
            return (bytes(out), end + 4) if end >= 0 else None
        if len(b) < j + 2 + size + 2:
            return None
        out += b[j + 2:j + 2 + size]
        i = j + 2 + size + 2


def _decode(body: bytes, encoding: str) -> bytes:
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            return zlib.decompress(body)
    except (OSError, zlib.error):
        pass
    return body


def parse_message(b: bytes, i: int = 0) -> tuple[HttpMessage, int] | None:
    """Parse one message starting at ``i``; None if it isn't complete yet."""
    end = b.find(b"\r\n\r\n", i)
    if end < 0:
        return None
    head = b[i:end].decode("latin-1")
    headers = {ln.split(":", 1)[0].strip().lower(): ln.split(":", 1)[1].strip()
               for ln in head.split("\r\n")[1:] if ":" in ln}
    start = end + 4
    if headers.get("transfer-encoding", "").lower() == "chunked":
        res = _dechunk(b, start)
        if res is None:
            return None
        body, nxt = res
    else:
        n = int(headers.get("content-length", "0"))
        if len(b) < start + n:
            return None
        body, nxt = b[start:start + n], start + n
    return HttpMessage(head, headers, _decode(body, headers.get("content-encoding", "").lower())), nxt


def http_messages(b: bytes):
    i = 0
    while (res := parse_message(b, i)) is not None:
        msg, i = res
        yield msg


class HttpStream:
    """Feed decrypted bytes in any chunk sizes, get complete messages back."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[HttpMessage]:
        self.buf += data
        out, i = [], 0
        buf = bytes(self.buf)
        while (res := parse_message(buf, i)) is not None:
            msg, i = res
            out.append(msg)
        del self.buf[:i]
        return out
