import gzip

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aion2market.http1 import HttpStream, http_messages
from aion2market.tls13 import SUITES, Direction, decrypt_stream, hkdf_expand_label


def test_hkdf_expand_label_rfc8448():
    # RFC 8448 section 3, server handshake traffic key/iv
    secret = bytes.fromhex("b67b7d690cc16c4e75e54213cb2d37b4e9c912bcded9105d42befd59d391ad38")
    hash_fn = SUITES[0x1301][2]
    assert hkdf_expand_label(secret, "key", 16, hash_fn).hex() == "3fce516009c21727d0f2e4e86ee403bc"
    assert hkdf_expand_label(secret, "iv", 12, hash_fn).hex() == "5d313eb2671276ee13000b30"


def _record(secret: bytes, seq: int, inner_type: int, data: bytes) -> bytes:
    hash_fn = SUITES[0x1301][2]
    key = hkdf_expand_label(secret, "key", 16, hash_fn)
    iv = hkdf_expand_label(secret, "iv", 12, hash_fn)
    nonce = bytes(a ^ b for a, b in zip(iv, seq.to_bytes(12, "big"), strict=True))
    plain = data + bytes([inner_type])
    header = b"\x17\x03\x03" + (len(plain) + 16).to_bytes(2, "big")
    return header + AESGCM(key).encrypt(nonce, plain, header)


def test_switches_from_handshake_to_application_secret():
    hs, app = b"\x01" * 32, b"\x02" * 32
    stream = (b"\x14\x03\x03\x00\x01\x01"              # change_cipher_spec, ignored
              + _record(hs, 0, 22, b"finished")
              + _record(app, 0, 23, b"GET / ")
              + _record(app, 1, 23, b"HTTP/1.1"))
    out, failed = decrypt_stream(stream, Direction([hs, app], 0x1301))
    assert (out, failed) == (b"GET / HTTP/1.1", 0)


def test_http_messages_chunked_and_gzip():
    body = gzip.compress(b'{"a":1}')
    raw = (b"HTTP/1.1 200 OK\r\ncontent-encoding: gzip\r\ntransfer-encoding: chunked\r\n\r\n"
           + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
           + b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}")
    msgs = list(http_messages(raw))
    assert [m.body for m in msgs] == [b'{"a":1}', b"{}"]
    assert msgs[0].status == 200


def test_http_stream_waits_for_complete_message():
    s = HttpStream()
    raw = b"POST /trade/v1.0/x?q=1 HTTP/1.1\r\ncontent-length: 4\r\n\r\nbody"
    assert s.feed(raw[:20]) == [] and s.feed(raw[20:-1]) == []
    (m,) = s.feed(raw[-1:])
    assert (m.path, m.body, m.status) == ("/trade/v1.0/x", b"body", 0)
