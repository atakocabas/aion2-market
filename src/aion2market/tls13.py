"""Decrypt TLS 1.3 streams with an NSS key log (SSLKEYLOGFILE).

Only reads files and packets the OS already has; nothing is sent anywhere.

    python -m aion2market.tls13 captures\\<run> captures\\sslkeys.log [--host qos-api]

For every connection whose ClientHello random is in the key log, writes
``c2s.plain`` / ``s2c.plain`` (application data) next to ``c2s.bin`` / ``s2c.bin``,
plus ``http.txt`` with the HTTP/1.1 messages decoded.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from .http1 import http_messages

HANDSHAKE, APPLICATION_DATA, CHANGE_CIPHER_SPEC = 22, 23, 20

# cipher suite -> (aead, key length, hash)
SUITES: dict[int, tuple[type[AESGCM | ChaCha20Poly1305], int, Callable]] = {
    0x1301: (AESGCM, 16, hashlib.sha256),
    0x1302: (AESGCM, 32, hashlib.sha384),
    0x1303: (ChaCha20Poly1305, 32, hashlib.sha256),
}


class KeyLog:
    """NSS key log that is re-read as the client appends to it."""

    def __init__(self, path: Path):
        self.path = path
        self.keys: dict[bytes, dict[str, bytes]] = defaultdict(dict)
        self._pos = 0
        self._partial = b""

    def refresh(self) -> None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size < self._pos:           # file was truncated or replaced
            self._pos, self._partial = 0, b""
        if size == self._pos:
            return
        with self.path.open("rb") as f:
            f.seek(self._pos)
            data = f.read()
        self._pos += len(data)
        lines = (self._partial + data).split(b"\n")
        self._partial = lines.pop()
        for line in lines:
            parts = line.decode("ascii", "ignore").split()
            if len(parts) == 3 and not parts[0].startswith("#"):
                try:
                    self.keys[bytes.fromhex(parts[1])][parts[0]] = bytes.fromhex(parts[2])
                except ValueError:
                    continue

    def get(self, client_random: bytes) -> dict[str, bytes]:
        if "SERVER_TRAFFIC_SECRET_0" not in self.keys.get(client_random, {}):
            self.refresh()
        return self.keys.get(client_random, {})


def hkdf_expand_label(secret: bytes, label: str, length: int, hash_fn) -> bytes:
    full = b"tls13 " + label.encode()
    info = length.to_bytes(2, "big") + bytes([len(full)]) + full + b"\x00"
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(secret, block + info + bytes([i]), hash_fn).digest()
        out += block
        i += 1
    return out[:length]


def client_hello_sni(data: bytes) -> str | None:
    """SNI host name from the first record of a client stream, if it is a ClientHello."""
    if len(data) < 43 or data[0] != HANDSHAKE or data[5] != 0x01:
        return None
    try:
        i = 9 + 2 + 32                                  # record hdr + hs hdr + version + random
        i += 1 + data[i]                                # session id
        i += 2 + int.from_bytes(data[i:i + 2], "big")   # cipher suites
        i += 1 + data[i]                                # compression
        end = i + 2 + int.from_bytes(data[i:i + 2], "big")
        i += 2
        while i + 4 <= min(end, len(data)):
            typ = int.from_bytes(data[i:i + 2], "big")
            ln = int.from_bytes(data[i + 2:i + 4], "big")
            if typ == 0:
                name_len = int.from_bytes(data[i + 7:i + 9], "big")
                return data[i + 9:i + 9 + name_len].decode("ascii", "replace")
            i += 4 + ln
    except IndexError:
        pass
    return None


@dataclass
class Direction:
    """Tries each traffic secret in order; a failed tag means the peer moved to the next one."""
    secrets: list[bytes]
    suite: int
    stage: int = 0
    seq: int = 0
    _cipher: AESGCM | ChaCha20Poly1305 | None = field(default=None, repr=False)
    _iv: bytes = b""

    def _load(self) -> bool:
        if self.stage >= len(self.secrets):
            return False
        aead, key_len, hash_fn = SUITES[self.suite]
        secret = self.secrets[self.stage]
        self._cipher = aead(hkdf_expand_label(secret, "key", key_len, hash_fn))
        self._iv = hkdf_expand_label(secret, "iv", 12, hash_fn)
        self.seq = 0
        return True

    def decrypt(self, header: bytes, body: bytes) -> tuple[int, bytes] | None:
        if self._cipher is None and not self._load():
            return None
        while True:
            assert self._cipher is not None             # _load() returned True
            nonce = bytes(a ^ b for a, b in zip(self._iv, self.seq.to_bytes(12, "big"), strict=True))
            try:
                plain = self._cipher.decrypt(nonce, body, header)
            except InvalidTag:
                self.stage += 1
                if not self._load():
                    return None
                continue
            self.seq += 1
            inner = plain.rstrip(b"\x00")
            return inner[-1], inner[:-1]


def decrypt_stream(stream: bytes, direction: Direction) -> tuple[bytes, int]:
    """Return (application data, number of records that failed to decrypt)."""
    out, failed = bytearray(), 0
    i = 0
    while i + 5 <= len(stream):
        ln = int.from_bytes(stream[i + 3:i + 5], "big")
        if i + 5 + ln > len(stream):
            break
        if stream[i] == APPLICATION_DATA:
            res = direction.decrypt(stream[i:i + 5], stream[i + 5:i + 5 + ln])
            if res is None:
                failed += 1
            elif res[0] == APPLICATION_DATA:
                out += res[1]
        i += 5 + ln
    return bytes(out), failed


class TlsConnection:
    """Incremental decryption of one TCP connection; records wait until their keys are logged."""

    def __init__(self, keylog: KeyLog):
        self.keylog = keylog
        self.buf = {"c2s": bytearray(), "s2c": bytearray()}
        self.pending: dict[str, list[tuple[bytes, bytes]]] = {"c2s": [], "s2c": []}
        self.client_random: bytes | None = None
        self.suite: int | None = None
        self.dirs: dict[str, Direction] | None = None
        self.failed = 0

    def feed(self, direction: str, data: bytes) -> list[tuple[str, bytes]]:
        buf = self.buf[direction]
        buf += data
        i = 0
        while len(buf) - i >= 5:
            ln = int.from_bytes(buf[i + 3:i + 5], "big")
            if len(buf) - i - 5 < ln:
                break
            self._on_record(direction, buf[i], bytes(buf[i:i + 5]), bytes(buf[i + 5:i + 5 + ln]))
            i += 5 + ln
        del buf[:i]
        return self.drain()

    def _on_record(self, direction: str, typ: int, header: bytes, body: bytes) -> None:
        if typ == HANDSHAKE and body[:1] == b"\x01" and self.client_random is None:
            self.client_random = body[6:38]
        elif typ == HANDSHAKE and body[:1] == b"\x02" and self.suite is None:
            i = 4 + 2 + 32
            i += 1 + body[i]
            self.suite = int.from_bytes(body[i:i + 2], "big")
        elif typ == APPLICATION_DATA:
            self.pending[direction].append((header, body))

    def _load_keys(self) -> bool:
        if self.client_random is None or self.suite not in SUITES:
            return False
        k = self.keylog.get(self.client_random)
        if "CLIENT_TRAFFIC_SECRET_0" not in k or "SERVER_TRAFFIC_SECRET_0" not in k:
            return False
        c = [k[n] for n in ("CLIENT_EARLY_TRAFFIC_SECRET", "CLIENT_HANDSHAKE_TRAFFIC_SECRET",
                            "CLIENT_TRAFFIC_SECRET_0") if n in k]
        s = [k[n] for n in ("SERVER_HANDSHAKE_TRAFFIC_SECRET", "SERVER_TRAFFIC_SECRET_0") if n in k]
        self.dirs = {"c2s": Direction(c, self.suite), "s2c": Direction(s, self.suite)}
        return True

    @property
    def waiting(self) -> bool:
        return self.dirs is None and any(self.pending.values())

    def drain(self) -> list[tuple[str, bytes]]:
        """Decrypt whatever is pending; returns (direction, application data) chunks."""
        if self.dirs is None and not self._load_keys():
            return []
        assert self.dirs is not None                    # _load_keys() returned True
        out = []
        for d in ("c2s", "s2c"):
            data = bytearray()
            for header, body in self.pending[d]:
                res = self.dirs[d].decrypt(header, body)
                if res is None:
                    self.failed += 1
                elif res[0] == APPLICATION_DATA:
                    data += res[1]
            self.pending[d].clear()
            if data:
                out.append((d, bytes(data)))
        return out


def decrypt_connection(conn_dir: Path, keylog: KeyLog) -> tuple[bytes, bytes, int] | None:
    conn = TlsConnection(keylog)
    chunks = conn.feed("c2s", (conn_dir / "c2s.bin").read_bytes())
    chunks += conn.feed("s2c", (conn_dir / "s2c.bin").read_bytes())
    if conn.dirs is None:
        return None
    up = b"".join(data for d, data in chunks if d == "c2s")
    down = b"".join(data for d, data in chunks if d == "s2c")
    return up, down, conn.failed


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("keylog", type=Path)
    ap.add_argument("--host", default="", help="only write http.txt for connections whose HTTP text contains this")
    args = ap.parse_args(argv)

    keylog = KeyLog(args.keylog)
    for conn_dir in sorted(p for p in args.run.iterdir() if p.is_dir()):
        res = decrypt_connection(conn_dir, keylog)
        if res is None:
            continue
        up, down, failed = res
        (conn_dir / "c2s.plain").write_bytes(up)
        (conn_dir / "s2c.plain").write_bytes(down)
        lines = []
        for label, data in (("ISTEK", up), ("YANIT", down)):
            for m in http_messages(data):
                lines.append(f"===== {label} =====\n{m.head}\n\n{m.body.decode('utf-8', 'replace')}\n")
        text = "\n".join(lines)
        if args.host and args.host not in text:
            continue
        (conn_dir / "http.txt").write_text(text, encoding="utf-8")
        print(f"{conn_dir.name}: up={len(up):,} down={len(down):,} failed_records={failed}")


if __name__ == "__main__":
    main()
