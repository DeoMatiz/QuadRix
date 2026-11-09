#!/usr/bin/env python3
"""Тесты quadrix/protocol/connection.py.

Порт horizon-protocol/src/connection.rs и сжатой части frame.rs.
Соединение проверяется поверх socket.socketpair() — это ближайший
аналог Rust Pipe::pair() для in-memory канала между двумя концами.

.local-файлов эти тесты не читают: сетевой провод самодостаточен,
данные берутся из буферов. Точные форматы (VarInt(длина) + zlib,
префикс 0 у несжатого тела) сверены с frame.rs::contents.
"""

from __future__ import annotations

import zlib

import pytest

from quadrix.protocol import ids
from quadrix.protocol.buf import (
    MAX_FRAME,
    ProtocolError,
    Reader,
    frame_header,
    write_varint,
)
from quadrix.protocol.connection import (
    MAX_UNCOMPRESSED,
    PROTOCOL_VERSION,
    ClientConnection,
    Connection,
    ConnectionState,
    Inflater,
    connection_pair,
    contents,
    frame_body,
    prefixed,
)
from quadrix.protocol.packets.handshake import LOGIN, STATUS, TRANSFER, Intention
from quadrix.protocol.packets.login import (
    Clientbound as LoginClientbound,
    GameProfile,
    LoginFinished,
)


def wire_frame(sock) -> bytes:
    """Прочитать один целый кадр прямо с сокета (без Connection)."""
    buf = bytearray()
    while True:
        header = frame_header(bytes(buf))
        if header is not None:
            prefix, length = header
            if len(buf) >= prefix + length:
                return bytes(buf[:prefix + length])
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("peer closed before a whole frame arrived")
        buf += chunk


# ── Ритуал handshake ──────────────────────────────────────────────────


def test_send_handshake_round_trip():
    a, b = connection_pair()
    a.send_handshake("localhost", 25565, LOGIN)

    packet_id, payload = b.read_packet()
    assert packet_id == ids.handshake.serverbound.INTENTION == 0

    intention = Intention.decode(payload)
    assert intention.protocol == PROTOCOL_VERSION
    assert intention.host == "localhost"
    assert intention.port == 25565
    assert intention.intent == LOGIN

    # Отправитель перешёл в Login (next_state(LOGIN)).
    assert a.state is ConnectionState.LOGIN


def test_handshake_is_an_alias_of_send_handshake():
    a, b = connection_pair()
    a.handshake("example.org", 25565, STATUS)
    assert a.state is ConnectionState.STATUS
    assert b.read_packet()[0] == ids.handshake.serverbound.INTENTION


def test_unknown_intent_is_rejected():
    a, _ = connection_pair()
    with pytest.raises(ProtocolError):
        a.next_state(99)


# ── Сжатие выключено ─────────────────────────────────────────────────


def test_compression_off_round_trip():
    a, b = connection_pair()
    assert a.threshold is None

    a.write_packet(0x00, b"\x01\x02\x03")
    assert b.read_packet() == (0x00, b"\x01\x02\x03")


def test_compression_off_wire_is_plain_frame():
    a, b = connection_pair()
    a.write_packet(0x00, b"\x01\x02\x03")

    raw = wire_frame(b.sock)
    # Ровно: длина, id, payload — без ведущего поля длины сжатия.
    assert raw == prefixed(b"\x00\x01\x02\x03")
    assert raw == bytes([4, 0x00, 0x01, 0x02, 0x03])


# ── Сжатие включено (threshold = 0 → всё сжимается) ───────────────────


def test_compression_on_round_trip():
    a, b = connection_pair()
    a.set_compression(0)
    b.set_compression(0)

    payload = bytes(range(256)) * 8
    a.write_packet(0x05, payload)
    assert b.read_packet() == (0x05, payload)


def test_compression_on_wire_is_varint_length_plus_zlib():
    a, b = connection_pair()
    a.set_compression(0)
    a.write_packet(0x05, b"payload")

    raw = wire_frame(b.sock)
    outer = Reader(raw)
    frame_len = outer.varint()
    assert frame_len == len(raw) - outer.position()

    frame = raw[outer.position():outer.position() + frame_len]
    inner = Reader(frame)
    body_len = inner.varint()
    # Тело: VarInt id (0x05) + 7 байт.
    assert body_len == 8
    assert zlib.decompress(frame[inner.position():]) == b"\x05payload"


# ── Порог сжатия ──────────────────────────────────────────────────────


def test_contents_below_threshold_prefixes_zero():
    small = bytes(range(11))
    inner = contents(small, 256)
    assert inner[0] == 0
    assert inner[1:] == small


def test_contents_at_or_above_threshold_compresses():
    big = bytes((i * 7) % 13 for i in range(5000))
    inner = contents(big, 256)
    r = Reader(inner)
    assert r.varint() == len(big)
    assert zlib.decompress(inner[r.position():]) == big
    assert len(inner) < len(big)


def test_connection_threshold_mixes_both_paths():
    a, b = connection_pair()
    a.set_compression(64)
    b.set_compression(64)

    small = b"tiny"
    big = b"\x07" * 1000
    a.write_packet(1, small)
    a.write_packet(2, big)

    assert b.read_packet() == (1, small)
    assert b.read_packet() == (2, big)


def test_negative_threshold_disables_compression():
    a, b = connection_pair()
    a.set_compression(64)
    a.set_compression(-1)
    assert a.threshold is None
    a.write_packet(0, b"hi")
    assert wire_frame(b.sock) == prefixed(b"\x00hi")


def test_bad_declared_size_is_a_protocol_error():
    # Объявленная длина ниже порога — ошибка (frame.rs::body).
    body = zlib.compress(b"\x01" * 10)
    frame = b"\x0a" + body  # заявлено 10 < 256
    with pytest.raises(ProtocolError):
        frame_body(frame, 256, Inflater())

    # Объявленная длина не совпадает с потоком.
    frame = b"\xac\x02" + zlib.compress(b"\x01" * 299)  # заявлено 300
    with pytest.raises(ProtocolError):
        frame_body(frame, 256, Inflater())


def test_declared_size_over_protocol_maximum_is_rejected():
    # Заголовок с длиной больше MAX_UNCOMPRESSED, тело неважно.
    header = bytearray()
    write_varint(header, MAX_UNCOMPRESSED + 1)
    with pytest.raises(ProtocolError):
        frame_body(bytes(header) + b"\x00", 64, Inflater())


def test_empty_compressed_frame_is_skipped():
    a, b = connection_pair()
    a.set_compression(64)
    b.set_compression(64)

    # Пустой сжатый кадр: length=1, contents=b"\x00" (длина сжатия 0).
    assert prefixed(b"\x00") == b"\x01\x00"
    a.write_raw(prefixed(b"\x00"))
    a.write_packet(3, b"after")

    assert b.read_packet() == (3, b"after")


# ── Шифрование ────────────────────────────────────────────────────────


def test_encryption_round_trip():
    a, b = connection_pair()
    secret = bytes(range(16))
    a.enable_encryption(secret)
    b.enable_encryption(secret)

    a.write_packet(0x05, b"secret message")
    assert b.read_packet() == (0x05, b"secret message")


def test_encryption_changes_the_wire_bytes():
    a, b = connection_pair()
    secret = bytes([0xAB]) * 16
    a.enable_encryption(secret)

    a.write_packet(0x00, b"plain")
    # Кадр зашифрован целиком, поэтому длину с провода не разобрать:
    # читаем один дамп и сверяем с открытым кадром.
    raw = b.sock.recv(4096)
    assert raw != prefixed(b"\x00plain")
    assert len(raw) == len(prefixed(b"\x00plain"))


def test_encryption_and_compression_together():
    a, b = connection_pair()
    secret = bytes([3]) * 16
    for conn in (a, b):
        conn.enable_encryption(secret)
        conn.set_compression(64)

    for i in range(20):
        payload = bytes([i]) * (50 + i * 10)
        a.write_packet(i, payload)
    for i in range(20):
        packet_id, payload = b.read_packet()
        assert packet_id == i
        assert payload == bytes([i]) * (50 + i * 10)


# ── State machine ─────────────────────────────────────────────────────


def test_state_machine_login_to_play():
    a, b = connection_pair()
    assert a.state is ConnectionState.HANDSHAKING

    a.send_handshake("h", 25565, LOGIN)
    assert a.state is ConnectionState.LOGIN
    b.read_packet()  # Intention

    a.send_login_acknowledged()
    assert a.state is ConnectionState.CONFIGURATION
    assert b.read_packet()[0] == ids.login.serverbound.LOGIN_ACKNOWLEDGED

    a.send_finish_configuration()
    assert a.state is ConnectionState.PLAY
    assert b.read_packet()[0] == ids.configuration.serverbound.FINISH_CONFIGURATION


def test_next_state_transfer_is_login():
    a, _ = connection_pair()
    assert a.next_state(TRANSFER) is ConnectionState.LOGIN


def test_status_intent_stays_in_status():
    a, b = connection_pair()
    a.send_handshake("h", 25565, STATUS)
    a.send_status_request()
    assert a.state is ConnectionState.STATUS
    b.read_packet()
    packet_id, payload = b.read_packet()
    assert packet_id == ids.status.serverbound.STATUS_REQUEST
    assert payload == b""


# ── await_packet ──────────────────────────────────────────────────────


def test_await_packet_returns_expected_class():
    a, b = connection_pair()
    a.set_state(ConnectionState.LOGIN)

    packet = LoginFinished(GameProfile(0, "Deo", []), 0)
    b.write_packet(LoginClientbound.id(packet), packet.encode())

    got = a.await_packet(LoginFinished, timeout=2.0)
    assert isinstance(got, LoginFinished)
    assert got.profile.name == "Deo"


def test_await_packet_times_out():
    a, _ = connection_pair()
    with pytest.raises(ProtocolError, match="Timed out"):
        a.await_packet(LoginFinished, timeout=0.1)


# ── close и защита размера ────────────────────────────────────────────


def test_close_is_graceful_and_idempotent():
    a, b = connection_pair()
    a.write_packet(0, b"bye")
    assert b.read_packet() == (0, b"bye")

    a.close()
    a.close()  # повторно — без исключения
    with pytest.raises(ProtocolError):
        b.read_packet()


def test_oversized_packet_is_rejected():
    a, _ = connection_pair()
    with pytest.raises(ProtocolError):
        a.write_packet(0, bytes(MAX_FRAME + 1))


def test_client_connection_alias_and_context_manager():
    assert ClientConnection is Connection
    a, _b = connection_pair()
    with Connection(a.sock) as wrapped:
        assert wrapped.state is ConnectionState.HANDSHAKING


def test_recv_alias_matches_read_packet():
    a, b = connection_pair()
    a.write_packet(7, b"data")
    assert b.recv() == (7, b"data")
