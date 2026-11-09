#!/usr/bin/env python3
"""Тесты трёх маленьких состояний протокола QuadRix.

Источники:
  * horizon-protocol/src/packets/handshake.rs
  * horizon-protocol/src/packets/status.rs
  * horizon-protocol/src/packets/login.rs
  * горизонт-protocol/src/packets/mod.rs (Empty, packet_enum!)

Это чистые кодеки провода: .local-файлов они не читают, поэтому
тестов с реальными данными .local здесь нет. Точные байты взяты из
теста intention_bytes в handshake.rs.
"""

from __future__ import annotations

import pytest

from quadrix.protocol.buf import ProtocolError, Reader
from quadrix.protocol.packets.handshake import (
    LOGIN,
    STATUS,
    TRANSFER,
    HandshakePacket,
    Intention,
    Serverbound as HandshakeServerbound,
)
from quadrix.protocol.packets.login import (
    Clientbound as LoginClientbound,
    Compression,
    CookieRequest,
    CookieResponse,
    CustomQuery,
    CustomQueryAnswer,
    Disconnect,
    EncryptionRequest,
    EncryptionResponse,
    GameProfile,
    Hello,
    Key,
    LoginAcknowledged,
    LoginDisconnect,
    LoginFinished,
    LoginStart,
    LoginSuccess,
    Property,
    ServerHello,
    Serverbound as LoginServerbound,
)
from quadrix.protocol.packets.status import (
    Clientbound as StatusClientbound,
    Ping,
    PingRequest,
    PingResponse,
    Serverbound as StatusServerbound,
    StatusRequest,
    StatusResponse,
)


def round_trip(packet_set, packet):
    """Как packets/mod.rs::round_trip: id VarInt + тело, затем обратно."""
    body = packet_set.encode(packet)
    r = Reader(body)
    packet_id = r.varint()
    back = packet_set.decode(packet_id, r.rest())
    assert r.remaining() == 0
    assert back == packet
    return packet_id, body


# ── Handshake ─────────────────────────────────────────────────────────


def test_handshake_exact_bytes_and_round_trip():
    # Тест intention_bytes из handshake.rs: protocol 777, LOGIN.
    p = Intention(protocol=777, host="localhost", port=25565, intent=LOGIN)
    packet_id, body = round_trip(HandshakeServerbound, p)

    assert packet_id == 0
    assert body[0] == 0
    assert body[1:3] == bytes([0x89, 0x06])          # VarInt 777
    assert body[-3:] == bytes([0x63, 0xDD, 0x02])    # порт 25565 + intent 2
    assert body[3] == len("localhost")

    # Значение из задания: протокол 763 и intent=2 (login).
    # Поля называются как в Rust: protocol/host/port/intent.
    p2 = HandshakePacket(protocol=763, host="localhost", port=25565, intent=2)
    _, body2 = round_trip(HandshakeServerbound, p2)
    assert body2[1:3] == bytes([0xFB, 0x05])          # VarInt 763
    assert p2.intent == LOGIN


def test_handshake_intent_constants():
    assert (STATUS, LOGIN, TRANSFER) == (1, 2, 3)
    assert HandshakeServerbound.name(Intention(1, "h", 1, STATUS)) == "Intention"


# ── Status ────────────────────────────────────────────────────────────


def test_status_request_and_response_round_trip():
    request = StatusRequest()
    packet_id, body = round_trip(StatusServerbound, request)
    assert packet_id == 0
    assert body == b"\x00"  # только id, у Empty нет полей

    response = StatusResponse(json='{"version":{"name":"26.3"}}')
    packet_id, _ = round_trip(StatusClientbound, response)
    assert packet_id == 0
    assert StatusClientbound.name(response) == "StatusResponse"


def test_status_ping_round_trip_long_payload():
    for value in (123, -5, 2**63 - 1, -(2**63)):
        packet = PingRequest(time=value)
        packet_id, _ = round_trip(StatusServerbound, packet)
        assert packet_id == 1
        assert packet == Ping(time=value)
        assert PingResponse is Ping and PingRequest is Ping

    pong = PingResponse(time=0x0102030405060708)
    packet_id, body = round_trip(StatusClientbound, pong)
    assert packet_id == 1
    assert body[1:] == bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])
    assert StatusClientbound.name(pong) == "PongResponse"


# ── Login ─────────────────────────────────────────────────────────────


def test_login_start_round_trip_with_and_without_real_uuid():
    # Rust LoginStart = ServerHello { name, uuid: u128 }; uuid = 0 — offline.
    offline = LoginStart(name="Player", uuid=0)
    packet_id, body = round_trip(LoginServerbound, offline)
    assert packet_id == 0
    assert body[1] == len("Player")
    assert body[-16:] == b"\x00" * 16

    online = LoginStart(name="Player", uuid=0x1234567890ABCDEF)
    packet_id, _ = round_trip(LoginServerbound, online)
    assert packet_id == 0
    assert online == ServerHello(name="Player", uuid=0x1234567890ABCDEF)


def test_login_success_round_trip_empty_properties():
    profile = GameProfile(
        uuid=0xDEADBEEFCAFEBABE,
        name="Player",
        properties=[],
    )
    packet = LoginSuccess(profile=profile, session=7)

    packet_id, _ = round_trip(LoginClientbound, packet)
    assert packet_id == 2
    assert packet.profile.properties == []
    assert LoginFinished is LoginSuccess


def test_login_success_round_trip_with_property_and_signature():
    signature = "подпись"
    profile = GameProfile(
        uuid=1,
        name="Horizon",
        properties=[
            Property(name="textures", value="e30=", signature=None),
            Property(name="signed", value="abc", signature=signature),
        ],
    )
    packet = LoginFinished(profile=profile, session=0)
    _, _ = round_trip(LoginClientbound, packet)

    back = LoginClientbound.decode(2, LoginFinished(profile, 0).encode())
    assert back.profile.properties[0].signature is None
    assert back.profile.properties[1].signature == signature


def test_login_disconnect_round_trip_russian_json():
    reason = '{"text":"Прощай, мир! ☃","color":"red"}'
    packet = LoginDisconnect(reason_json=reason)

    packet_id, body = round_trip(LoginClientbound, packet)
    assert packet_id == 0
    assert packet.reason_json == reason
    assert "Прощай" in body.decode("utf-8")
    assert Disconnect is LoginDisconnect


def test_login_encryption_and_cookie_round_trip():
    request = EncryptionRequest(
        server_id="",
        public_key=b"\x01\x02",
        challenge=b"\x03" * 4,
        should_authenticate=True,
    )
    packet_id, _ = round_trip(LoginClientbound, request)
    assert packet_id == 1
    assert Hello is EncryptionRequest

    response = EncryptionResponse(key=b"\x09" * 128, challenge=b"\x08" * 128)
    packet_id, _ = round_trip(LoginServerbound, response)
    assert packet_id == 1
    assert Key is EncryptionResponse

    # CookieResponse: payload есть и отсутствует.
    for payload in (None, b"\x01"):
        _, _ = round_trip(
            LoginServerbound,
            CookieResponse(key="quadrix:test", payload=payload),
        )
    # CustomQueryAnswer: payload есть и отсутствует.
    for payload in (None, b"\x02\x03"):
        _, _ = round_trip(
            LoginServerbound,
            CustomQueryAnswer(transaction=3, payload=payload),
        )


def test_login_custom_query_and_misc_clientbound():
    query = CustomQuery(
        transaction=3,
        channel="velocity:player_info",
        data=b"\x01",
    )
    packet_id, _ = round_trip(LoginClientbound, query)
    assert packet_id == 4

    packet_id, _ = round_trip(LoginClientbound, CookieRequest(key="a:b"))
    assert packet_id == 5

    packet_id, _ = round_trip(LoginClientbound, Compression(threshold=256))
    assert packet_id == 3

    packet_id, _ = round_trip(LoginServerbound, LoginAcknowledged())
    assert packet_id == 3


# ── Ошибки ────────────────────────────────────────────────────────────


def test_unknown_id_is_unknown_by_default_and_strict_raises():
    # Как в Rust, неизвестный id не роняет декодирование: Unknown(id,payload).
    unknown = StatusClientbound.decode(99, b"\xAA\xBB")
    assert unknown.packet_id == 99
    assert unknown.payload == b"\xAA\xBB"
    assert StatusClientbound.name(unknown) == "Unknown"
    assert StatusClientbound.id(unknown) == 99
    assert StatusClientbound.encode(unknown) == b"\x63\xAA\xBB"  # VarInt 99

    with pytest.raises(KeyError):
        StatusClientbound.decode(99, b"", strict=True)
    with pytest.raises(KeyError):
        HandshakeServerbound.decode(5, b"", strict=True)


def test_trailing_bytes_are_rejected():
    # packet_enum! отвергает пакет длиннее ожидаемого.
    body = HandshakeServerbound.encode(Intention(763, "localhost", 25565, LOGIN))
    r = Reader(body)
    packet_id = r.varint()
    with pytest.raises(ProtocolError):
        HandshakeServerbound.decode(packet_id, r.rest() + b"\x00")

    with pytest.raises(ProtocolError):
        LoginAcknowledged.decode(b"\x00")
