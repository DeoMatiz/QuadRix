#!/usr/bin/env python3
"""Тесты PART 1 состояния Play протокола QuadRix.

Источник: horizon-protocol/src/packets/play.rs.

PART 1 — только каркас: полные таблицы ID направлений, dispatch
decode/encode и три простых пакета в каждую сторону. Остальные payload'ы
проверяются как явные заглушки Unsupported, а не как «молча пустые».

Это чистые кодеки провода: .local-файлов они не читают.
"""

from __future__ import annotations

import pytest

from quadrix.protocol import ids
from quadrix.protocol.buf import ProtocolError, Reader, Writer
from quadrix.protocol.ids import Direction, State, id_of
from quadrix.protocol.packets.play import (
    CLASS_TO_ID,
    Clientbound,
    ClientTickEnd,
    ClientboundPlayPacket,
    Disconnect,
    ID_TO_CLASS,
    KeepAlive,
    PlayerLoaded,
    SERVERBOUND_CLASS_TO_ID,
    SERVERBOUND_ID_TO_CLASS,
    Serverbound,
    ServerboundPlayPacket,
    Unsupported,
    BundleDelimiter,
    decode_clientbound,
    decode_serverbound,
    encode_clientbound,
    encode_serverbound,
)
from quadrix.world.nbt import Tag, TagType


def round_trip(packet_set, packet):
    """Как packets/mod.rs::round_trip: id VarInt + тело, затем обратно."""
    body = packet_set.encode(packet)
    r = Reader(body)
    packet_id = r.varint()
    back = packet_set.decode(packet_id, r.rest())
    assert r.remaining() == 0
    assert back == packet
    return packet_id, body


def string(s: str) -> Tag:
    return Tag(TagType.String, str_val=s)


def compound(**fields: Tag) -> Tag:
    return Tag(TagType.Compound, compound_val=fields)


# ── Clientbound: KeepAlive ───────────────────────────────────────────


def test_clientbound_keep_alive_round_trip_long():
    value = 123456789
    packet = KeepAlive(id=value)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "keep_alive", State.PLAY, Direction.CLIENTBOUND
    )
    assert body[1:] == value.to_bytes(8, "big", signed=True)
    assert len(body) == 9  # VarInt-id (1 байт) + long (8 байт)

    # Module-level диспетчеры видят тот же пакет.
    w = Writer()
    assert encode_clientbound(w, packet) == packet_id
    assert bytes(w.data) == body
    r = Reader(body)
    decoded_id = r.varint()
    assert decode_clientbound(decoded_id, r) == packet


# ── Clientbound: Disconnect ──────────────────────────────────────────


def test_clientbound_disconnect_round_trip_russian_json_nbt():
    # В play.rs Disconnect — это configuration::Disconnect с причиной в
    # сетевом NBT. JSON-строка с русскими символами лежит внутри тега.
    reason = compound(text=string('{"text":"Прощай, мир! ☃","color":"red"}'))
    packet = Disconnect(reason=reason)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "disconnect", State.PLAY, Direction.CLIENTBOUND
    )
    # Первый байт payload — TagType.Compound, а не VarInt-длина строки.
    assert body[1] == int(TagType.Compound)
    assert packet.reason == reason
    assert "Прощай" in reason.compound_val["text"].str_val


# ── Clientbound: BundleDelimiter ─────────────────────────────────────


def test_clientbound_bundle_delimiter_round_trip_empty():
    packet_id, body = round_trip(Clientbound, BundleDelimiter())

    assert packet_id == id_of(
        "bundle_delimiter", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 0
    assert body == b"\x00"  # только id, payload пустой


# ── Serverbound: KeepAlive / ClientTickEnd / PlayerLoaded ────────────


def test_serverbound_keep_alive_round_trip_long():
    packet = KeepAlive(id=-987654321)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "keep_alive", State.PLAY, Direction.SERVERBOUND
    )
    assert body[1:] == (-987654321).to_bytes(8, "big", signed=True)

    w = Writer()
    assert encode_serverbound(w, packet) == packet_id
    assert bytes(w.data) == body
    r = Reader(body)
    decoded_id = r.varint()
    assert decode_serverbound(decoded_id, r) == packet


def test_serverbound_client_tick_end_and_player_loaded_round_trip_empty():
    tick_id, tick_body = round_trip(Serverbound, ClientTickEnd())
    loaded_id, loaded_body = round_trip(Serverbound, PlayerLoaded())

    assert tick_id == id_of(
        "client_tick_end", State.PLAY, Direction.SERVERBOUND
    )
    assert loaded_id == id_of(
        "player_loaded", State.PLAY, Direction.SERVERBOUND
    )
    assert tick_body == bytes([tick_id])
    assert loaded_body == bytes([loaded_id])

    # Разные пустые варианты не должны схлопываться в один класс/ID.
    assert ClientTickEnd is not PlayerLoaded
    assert Serverbound.id(ClientTickEnd()) != Serverbound.id(PlayerLoaded())


# ── Полнота таблиц и заглушки ────────────────────────────────────────


def test_id_tables_cover_every_id_from_ids_py():
    assert len(ID_TO_CLASS) == len(ids.play.clientbound.NAMES)
    assert len(CLASS_TO_ID) == len(ids.play.clientbound.NAMES)
    assert len(SERVERBOUND_ID_TO_CLASS) == len(ids.play.serverbound.NAMES)
    assert len(SERVERBOUND_CLASS_TO_ID) == len(ids.play.serverbound.NAMES)

    # Каждый ID из таблицы NAMES реально присутствует в dispatch.
    for packet_id, name in enumerate(ids.play.clientbound.NAMES):
        assert packet_id in ID_TO_CLASS, name
    for packet_id, name in enumerate(ids.play.serverbound.NAMES):
        assert packet_id in SERVERBOUND_ID_TO_CLASS, name

    assert ClientboundPlayPacket is Clientbound
    assert ServerboundPlayPacket is Serverbound


def test_unimplemented_payload_raises_named_unsupported():
    add_entity_id = id_of(
        "add_entity", State.PLAY, Direction.CLIENTBOUND
    )

    with pytest.raises(Unsupported) as excinfo:
        decode_clientbound(add_entity_id, Reader(b""))

    assert "play.rs PART 2+" in str(excinfo.value)
    assert "add_entity" in str(excinfo.value)

    # encode заглушки тоже не притворяется, что пакет реализован.
    placeholder = ID_TO_CLASS[add_entity_id]()
    with pytest.raises(Unsupported):
        encode_clientbound(Writer(), placeholder)


def test_unknown_and_trailing_bytes():
    unknown = Clientbound.decode(999, b"\xAA\xBB")
    assert unknown.packet_id == 999
    assert unknown.payload == b"\xAA\xBB"
    assert Clientbound.name(unknown) == "Unknown"
    assert Clientbound.id(unknown) == 999

    with pytest.raises(KeyError):
        Clientbound.decode(999, b"", strict=True)
    with pytest.raises(KeyError):
        Serverbound.decode(999, b"", strict=True)

    body = Clientbound.encode(BundleDelimiter())
    with pytest.raises(ProtocolError):
        Clientbound.decode(0, body[1:] + b"\x00")
