from aion2market.reassembly import MOD, Data, Gap, StreamReassembler


def collect(events):
    return b"".join(e.payload for e in events if isinstance(e, Data))


def test_in_order():
    r = StreamReassembler()
    assert collect(r.feed(100, b"abc") + r.feed(103, b"def")) == b"abcdef"


def test_syn_sets_start():
    r = StreamReassembler()
    r.feed(999, b"", syn=True)
    assert r.feed(1000, b"xy") == [Data(0, b"xy")]


def test_out_of_order_is_buffered():
    r = StreamReassembler()
    r.feed(0, b"", syn=True)
    assert r.feed(4, b"def") == []
    assert collect(r.feed(1, b"abc")) == b"abcdef"


def test_retransmission_and_overlap():
    r = StreamReassembler()
    out = r.feed(10, b"abcd")
    out += r.feed(10, b"abcd")      # duplicate
    out += r.feed(12, b"cdef")      # overlaps two bytes
    assert collect(out) == b"abcdef"


def test_longer_retransmit_of_pending_wins():
    r = StreamReassembler()
    r.feed(0, b"a")
    r.feed(3, b"d")
    r.feed(3, b"def")
    assert collect(r.feed(1, b"bc")) == b"bcdef"


def test_wraparound():
    r = StreamReassembler()
    start = MOD - 2
    out = r.feed(start, b"ab") + r.feed(0, b"cd")
    assert collect(out) == b"abcd"


def test_gap_skipped_when_buffer_full():
    r = StreamReassembler(max_pending_bytes=4)
    r.feed(0, b"aa")
    out = r.feed(5, b"bbbbb")  # 3-byte hole, pending exceeds limit
    assert out == [Gap(2, 3), Data(5, b"bbbbb")]
    assert collect(r.feed(10, b"c")) == b"c"


def test_flush_reports_gap():
    r = StreamReassembler()
    r.feed(0, b"aa")
    r.feed(4, b"cc")
    assert r.flush() == [Gap(2, 2), Data(4, b"cc")]
