#!/usr/bin/env python3
"""Тесты состояния Play протокола QuadRix (PART 1 + PART 2).

Источник: horizon-protocol/src/packets/play.rs.

PART 1 — каркас: полные таблицы ID направлений, dispatch decode/encode и
три простых пакета в каждую сторону. Остальные payload'ы проверяются как
явные заглушки Unsupported, а не как «молча пустые».

PART 2 — движение/позиция/тики: MovePlayerPos/PosRot/Rot/Status,
PlayerInput, PlayerAction, PlayerCommand, PlayerAbilitiesRequest,
SetCarriedItem, GameEvent, PlayerLookAt, PlayerPosition, PlayerRotation,
SetChunkCacheCenter, SetHealth, SetHeldSlot, SetTime, TeleportEntity,
TickingState, TickingStep, PlayerAbilities — с round-trip и проверкой
байтов провода.

Это чистые кодеки провода: .local-файлов они не читают.
"""

from __future__ import annotations

import struct

import pytest

from quadrix.protocol import ids
from quadrix.protocol.buf import ProtocolError, Reader, Writer, pack_block_pos
from quadrix.protocol.ids import Direction, State, id_of
from quadrix.protocol.packets.play import (
    CLASS_TO_ID,
    Clientbound,
    ClientTickEnd,
    ClientboundPlayPacket,
    ClockState,
    Disconnect,
    GameEvent,
    ID_TO_CLASS,
    KeepAlive,
    LookAtEntity,
    MovePlayerPos,
    MovePlayerPosRot,
    MovePlayerRot,
    MovePlayerStatus,
    PlayerAbilities,
    PlayerAbilitiesRequest,
    PlayerAction,
    PlayerCommand,
    PlayerInput,
    PlayerLoaded,
    PlayerLookAt,
    PlayerPosition,
    PlayerRotation,
    SERVERBOUND_CLASS_TO_ID,
    SERVERBOUND_ID_TO_CLASS,
    Serverbound,
    ServerboundPlayPacket,
    SetCarriedItem,
    SetChunkCacheCenter,
    SetHealth,
    SetHeldSlot,
    SetTime,
    TeleportEntity,
    TickingState,
    TickingStep,
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


# ═════════════════════════════════════════════════════════════════════
# PART 2 — движение / позиция / тики (play.rs)
# ═════════════════════════════════════════════════════════════════════


# ── Serverbound: движение игрока ─────────────────────────────────────


def test_serverbound_move_player_pos_round_trip():
    # В Rust у ServerboundMovePlayerPacket.Pos последнее поле — flags: u8
    # (1 = на земле), а не bool on_ground.
    packet = MovePlayerPos(x=1.5, y=64.0, z=-2.3, flags=1)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "move_player_pos", State.PLAY, Direction.SERVERBOUND
    )
    assert packet_id == 30
    assert len(body) == 1 + 8 * 3 + 1
    assert body[1:9] == struct.pack(">d", 1.5)
    assert body[9:17] == struct.pack(">d", 64.0)
    assert body[17:25] == struct.pack(">d", -2.3)
    assert body[25] == 1


def test_serverbound_move_player_pos_rot_round_trip():
    packet = MovePlayerPosRot(
        x=10.25, y=70.0, z=-0.5, yaw=90.0, pitch=-30.0, flags=3
    )

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "move_player_pos_rot", State.PLAY, Direction.SERVERBOUND
    )
    assert len(body) == 1 + 8 * 3 + 4 * 2 + 1
    assert body[1:9] == struct.pack(">d", 10.25)
    assert body[25:29] == struct.pack(">f", 90.0)
    assert body[29:33] == struct.pack(">f", -30.0)
    assert body[33] == 3


def test_serverbound_move_player_rot_and_status_round_trip():
    rot = MovePlayerRot(yaw=45.0, pitch=10.0, flags=1)
    status = MovePlayerStatus(flags=3)

    rot_id, rot_body = round_trip(Serverbound, rot)
    status_id, status_body = round_trip(Serverbound, status)

    assert rot_id == id_of(
        "move_player_rot", State.PLAY, Direction.SERVERBOUND
    )
    assert status_id == id_of(
        "move_player_status_only", State.PLAY, Direction.SERVERBOUND
    )
    assert rot_body == (
        bytes([rot_id])
        + struct.pack(">f", 45.0)
        + struct.pack(">f", 10.0)
        + b"\x01"
    )
    assert status_body == bytes([status_id, 3])


def test_serverbound_player_input_round_trip():
    # Rust PlayerInput: flags: u8 (forward 1, backward 2, left 4, right 8,
    # jump 16, shift 32, sprint 64), а не семь отдельных bool.
    flags = 0b0101_0001  # forward + jump + sprint
    packet = PlayerInput(flags=flags)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "player_input", State.PLAY, Direction.SERVERBOUND
    )
    assert body == bytes([packet_id, flags])
    assert packet.flags == 81


def test_serverbound_player_action_round_trip():
    packet = PlayerAction(action=0, pos=(1, 64, -3), direction=1, sequence=7)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "player_action", State.PLAY, Direction.SERVERBOUND
    )
    assert body[0] == packet_id
    assert body[1] == 0  # action VarInt
    assert body[2:10] == struct.pack(">q", pack_block_pos((1, 64, -3)))
    assert body[10] == 1  # direction (3D data value)
    assert body[11] == 7  # sequence VarInt
    assert packet.pos == (1, 64, -3)


def test_serverbound_player_command_and_abilities_round_trip():
    command = PlayerCommand(id=12, action=5, data=0)
    abilities = PlayerAbilitiesRequest(flags=2)

    command_id, command_body = round_trip(Serverbound, command)
    abilities_id, abilities_body = round_trip(Serverbound, abilities)

    assert command_id == id_of(
        "player_command", State.PLAY, Direction.SERVERBOUND
    )
    assert command_body == bytes([command_id, 12, 5, 0])
    assert abilities_id == id_of(
        "player_abilities", State.PLAY, Direction.SERVERBOUND
    )
    # flags: i8 — только бит полёта (2).
    assert abilities_body == bytes([abilities_id, 2])


def test_serverbound_set_carried_item_round_trip():
    packet = SetCarriedItem(slot=4)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "set_carried_item", State.PLAY, Direction.SERVERBOUND
    )
    assert body == bytes([packet_id]) + struct.pack(">h", 4)


# ── Clientbound: позиция / поворот игрока ────────────────────────────


def test_clientbound_player_position_round_trip():
    # Rust ClientboundPlayerPositionPacket: teleport, position, delta,
    # yaw, pitch, relatives. (В задании он звался SyncPlayerPosition.)
    packet = PlayerPosition(
        teleport=1,
        position=(0.5, 70.0, 0.5),
        delta=(0.0, 0.0, 0.0),
        yaw=90.0,
        pitch=0.0,
        relatives=33,  # X (1) | DELTA_X (32)
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "player_position", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 73
    assert body[1] == 1  # teleport VarInt
    assert body[2:10] == struct.pack(">d", 0.5)
    assert body[50:54] == struct.pack(">f", 90.0)  # yaw после delta
    assert body[58:62] == struct.pack(">i", 33)  # relatives как Int


def test_clientbound_player_look_at_round_trip():
    at_point = PlayerLookAt(from_=1, target=(1.5, 64.0, -2.25), entity=None)
    at_entity = PlayerLookAt(
        from_=0,
        target=(0.0, 70.0, 0.0),
        entity=LookAtEntity(id=42, anchor=1),
    )

    point_id, point_body = round_trip(Clientbound, at_point)
    entity_id, entity_body = round_trip(Clientbound, at_entity)

    assert point_id == id_of(
        "player_look_at", State.PLAY, Direction.CLIENTBOUND
    )
    assert entity_id == point_id
    # 1 id, 1 from VarInt, 3 double target, 1 флаг Opt; сущность +2 VarInt.
    assert len(point_body) == 1 + 1 + 24 + 1
    assert len(entity_body) == 1 + 1 + 24 + 1 + 2
    assert at_point.entity is None
    assert at_entity.entity == LookAtEntity(id=42, anchor=1)


def test_clientbound_player_rotation_round_trip():
    packet = PlayerRotation(
        yaw=90.0, relative_yaw=True, pitch=-15.0, relative_pitch=False
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "player_rotation", State.PLAY, Direction.CLIENTBOUND
    )
    assert len(body) == 1 + 4 + 1 + 4 + 1
    assert body[1:5] == struct.pack(">f", 90.0)
    assert body[5] == 1  # relative_yaw
    assert body[10] == 0  # relative_pitch


def test_clientbound_teleport_entity_round_trip():
    packet = TeleportEntity(
        id=1,
        position=(1.0, 2.0, 3.0),
        delta=(0.0, 0.0, 0.0),
        yaw=45.0,
        pitch=10.0,
        relatives=1,
        on_ground=True,
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "teleport_entity", State.PLAY, Direction.CLIENTBOUND
    )
    # id пакета 128 — двубайтовый VarInt (80 01), затем id сущности 1.
    assert body[:2] == b"\x80\x01"
    assert body[2] == 1
    assert body[-1] == 1  # on_ground
    assert len(body) == 2 + 1 + 24 + 24 + 4 + 4 + 4 + 1


# ── Clientbound: здоровье, время, события, тики ──────────────────────


def test_clientbound_set_health_round_trip():
    packet = SetHealth(health=17.5, food=18, saturation=3.0)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "set_health", State.PLAY, Direction.CLIENTBOUND
    )
    assert body[1:5] == struct.pack(">f", 17.5)
    assert body[5] == 18
    assert body[6:10] == struct.pack(">f", 3.0)


def test_clientbound_set_time_round_trip():
    packet = SetTime(
        game_time=100,
        clocks=[
            ClockState(
                clock=0, total_ticks=6000, partial_tick=0.0, rate=1.0
            )
        ],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "set_time", State.PLAY, Direction.CLIENTBOUND
    )
    assert body[0] == packet_id
    assert body[1:9] == struct.pack(">q", 100)
    assert body[9] == 1  # VarInt-счётчик списка часов
    assert body[10] == 0  # clock: plain registry id, без off-by-one
    assert body[11:13] == b"\xf0\x2e"  # VarLong 6000
    assert packet.clocks[0].total_ticks == 6000


def test_clientbound_game_event_and_tick_packets_round_trip():
    event = GameEvent(event=13, param=0.0)
    state = TickingState(rate=40.0, frozen=True)
    step = TickingStep(steps=7)
    center = SetChunkCacheCenter(x=-3, z=12)
    held = SetHeldSlot(slot=4)

    event_id, event_body = round_trip(Clientbound, event)
    state_id, _ = round_trip(Clientbound, state)
    step_id, _ = round_trip(Clientbound, step)
    center_id, center_body = round_trip(Clientbound, center)
    held_id, held_body = round_trip(Clientbound, held)

    assert event_id == id_of(
        "game_event", State.PLAY, Direction.CLIENTBOUND
    )
    assert event_body == bytes([event_id, 13]) + struct.pack(">f", 0.0)
    assert state_id == id_of(
        "ticking_state", State.PLAY, Direction.CLIENTBOUND
    )
    assert step_id == id_of(
        "ticking_step", State.PLAY, Direction.CLIENTBOUND
    )
    assert center_id == id_of(
        "set_chunk_cache_center", State.PLAY, Direction.CLIENTBOUND
    )
    # VarInt -3 = fd ff ff ff 0f, затем VarInt 12 = 0c.
    assert center_body == bytes([center_id]) + b"\xfd\xff\xff\xff\x0f\x0c"
    assert held_id == id_of(
        "set_held_slot", State.PLAY, Direction.CLIENTBOUND
    )
    assert held_body == bytes([held_id, 4])


def test_clientbound_player_abilities_round_trip():
    packet = PlayerAbilities(flags=2, flying_speed=0.5, walking_speed=0.25)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "player_abilities", State.PLAY, Direction.CLIENTBOUND
    )
    assert body[1] == 2  # flags i8
    assert len(body) == 1 + 1 + 4 + 4


# ── Dispatch: PART 2 заменил заглушки ────────────────────────────────


def test_part2_replaces_unsupported_stubs():
    position_id = id_of("player_position", State.PLAY, Direction.CLIENTBOUND)
    move_id = id_of("move_player_pos", State.PLAY, Direction.SERVERBOUND)

    assert ID_TO_CLASS[position_id] is PlayerPosition
    assert SERVERBOUND_ID_TO_CLASS[move_id] is MovePlayerPos

    # Module-level диспетчеры видят те же классы, что и таблицы.
    health = SetHealth(health=20.0, food=20, saturation=5.0)
    writer = Writer()
    assert encode_clientbound(writer, health) == id_of(
        "set_health", State.PLAY, Direction.CLIENTBOUND
    )
    reader = Reader(bytes(writer.data))
    decoded_id = reader.varint()
    assert decode_clientbound(decoded_id, reader) == health

    action = PlayerAction(action=0, pos=(1, 64, -3), direction=1, sequence=7)
    server_writer = Writer()
    assert encode_serverbound(server_writer, action) == id_of(
        "player_action", State.PLAY, Direction.SERVERBOUND
    )
    server_reader = Reader(bytes(server_writer.data))
    server_id = server_reader.varint()
    assert decode_serverbound(server_id, server_reader) == action
