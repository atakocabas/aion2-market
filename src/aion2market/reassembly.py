"""One-direction TCP stream reassembly from sniffed segments.

Handles out-of-order delivery, retransmissions, overlapping segments and
sequence number wraparound. When a hole can't be filled (packet lost by the
sniffer), it is reported as a Gap so downstream parsers know framing may be
broken at that offset.
"""

from __future__ import annotations

from dataclasses import dataclass

MOD = 1 << 32


def seq_diff(a: int, b: int) -> int:
    """Signed distance a - b in 32-bit sequence space."""
    d = (a - b) % MOD
    return d - MOD if d >= MOD // 2 else d


@dataclass(frozen=True)
class Data:
    offset: int
    payload: bytes


@dataclass(frozen=True)
class Gap:
    offset: int
    size: int


Event = Data | Gap


class StreamReassembler:
    def __init__(self, max_pending_bytes: int = 4 * 1024 * 1024):
        self.next_seq: int | None = None
        self.offset = 0  # bytes (including gaps) delivered so far
        self.max_pending_bytes = max_pending_bytes
        self._pending: dict[int, bytes] = {}
        self._pending_bytes = 0

    def feed(self, seq: int, payload: bytes, syn: bool = False) -> list[Event]:
        out: list[Event] = []
        if syn:
            # SYN consumes one sequence number; data follows at seq + 1.
            seq = (seq + 1) % MOD
            if self.next_seq is None:
                self.next_seq = seq
        if not payload:
            return out
        if self.next_seq is None:
            # Joined mid-stream: start from the first segment we see.
            self.next_seq = seq

        d = seq_diff(seq, self.next_seq)
        if d < 0:
            if len(payload) <= -d:
                return out  # pure retransmission
            payload = payload[-d:]
            seq = self.next_seq
            d = 0

        if d == 0:
            self._emit(payload, out)
            self._drain(out)
        else:
            old = self._pending.get(seq)
            if old is None or len(payload) > len(old):
                self._pending_bytes += len(payload) - (len(old) if old else 0)
                self._pending[seq] = payload
            while self._pending_bytes > self.max_pending_bytes:
                self._skip_gap(out)
        return out

    def flush(self) -> list[Event]:
        """Give up on remaining holes and deliver everything buffered."""
        out: list[Event] = []
        while self._pending:
            self._skip_gap(out)
        return out

    def _emit(self, payload: bytes, out: list[Event]) -> None:
        out.append(Data(self.offset, payload))
        self.offset += len(payload)
        self.next_seq = (self.next_seq + len(payload)) % MOD

    def _drain(self, out: list[Event]) -> None:
        while self._pending:
            k = min(self._pending, key=lambda s: seq_diff(s, self.next_seq))
            d = seq_diff(k, self.next_seq)
            if d > 0:
                return
            data = self._pending.pop(k)
            self._pending_bytes -= len(data)
            if len(data) > -d:
                self._emit(data[-d:], out)

    def _skip_gap(self, out: list[Event]) -> None:
        k = min(self._pending, key=lambda s: seq_diff(s, self.next_seq))
        gap = seq_diff(k, self.next_seq)
        if gap > 0:
            out.append(Gap(self.offset, gap))
            self.offset += gap
            self.next_seq = k
        self._drain(out)
