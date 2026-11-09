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
    # PART 3
    AddEntity,
    Animate,
    AttributeModifier,
    AttributeSnapshot,
    ClientCommand,
    DamageEvent,
    EntityEvent,
    EntityPositionSync,
    HurtAnimation,
    Interact,
    ItemStack,
    MoveEntityPos,
    MoveEntityPosRot,
    MoveEntityRot,
    MoveVehicle,
    MoveVehicleRequest,
    PaddleBoat,
    PickItemFromEntity,
    PlayerInfo,
    PlayerInfoRemove,
    PlayerInfoUpdate,
    PositionPath,
    ProjectilePower,
    Property,
    RemoveEntities,
    RotateHead,
    SetCamera,
    SetEntityData,
    SetEntityLink,
    SetEntityMotion,
    SetEquipment,
    SetPassengers,
    SwingAnimation,
    TakeItemEntity,
    UpdateAttributes,
    VecDelta,
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
    # PART 3 закрыл add_entity, поэтому берём пакет из ещё не портированной
    # группы (статистика — не entity/player sync).
    stats_id = id_of(
        "award_stats", State.PLAY, Direction.CLIENTBOUND
    )

    with pytest.raises(Unsupported) as excinfo:
        decode_clientbound(stats_id, Reader(b""))

    assert "play.rs PART 2+" in str(excinfo.value)
    assert "award_stats" in str(excinfo.value)

    # encode заглушки тоже не притворяется, что пакет реализован.
    placeholder = ID_TO_CLASS[stats_id]()
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


# ═════════════════════════════════════════════════════════════════════
# PART 3 — сущности и синхронизация игроков (play.rs)
# ═════════════════════════════════════════════════════════════════════


def test_clientbound_add_entity_round_trip():
    uuid = 0x0123456789ABCDEF0123456789ABCDEF
    packet = AddEntity(
        id=42,
        uuid=uuid,
        kind=5,
        position=(1.5, 64.0, -2.5),
        velocity=(0.0, 0.0, 0.0),
        pitch=0,
        yaw=90,
        head_yaw=90,
        data=0,
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of("add_entity", State.PLAY, Direction.CLIENTBOUND)
    assert packet_id == 1
    assert body[1] == 42  # id сущности (VarInt)
    assert body[2:18] == uuid.to_bytes(16, "big")
    assert body[18] == 5  # kind VarInt
    assert body[19:27] == struct.pack(">d", 1.5)
    assert body[43] == 0  # LpVec3 (0, 0, 0) — один нулевой байт
    assert body[44:47] == bytes([0, 90, 90])  # pitch, yaw, head_yaw (i8)
    assert body[47] == 0  # data VarInt
    assert packet.uuid == uuid and packet.kind == 5


def test_clientbound_remove_entities_round_trip():
    packet = RemoveEntities(ids=[1, 2, 3])

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "remove_entities", State.PLAY, Direction.CLIENTBOUND
    )
    # id 78, счётчик 3, затем id сущностей как VarInt.
    assert body == bytes([packet_id, 3, 1, 2, 3])
    assert packet.ids == [1, 2, 3]


def test_clientbound_set_entity_data_round_trip():
    # index=5, type=0 (BYTE), value=1; список закрыт 0xFF.
    packet = SetEntityData(id=1, values=[(5, 0, 1)])

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "set_entity_data", State.PLAY, Direction.CLIENTBOUND
    )
    assert body == bytes([packet_id, 1, 5, 0, 1, 0xFF])

    # Несколько типов сериализаторов: INT, BLOCK_POS и VECTOR3.
    many = SetEntityData(
        id=3,
        values=[(1, 1, 300), (7, 10, (1, 2, 3)), (8, 39, (1.0, 2.0, 3.0))],
    )
    round_trip(Clientbound, many)


def test_clientbound_move_entity_pos_round_trip():
    packet = MoveEntityPos(
        id=1,
        delta=VecDelta.linear(100, 200, -50),
        on_ground=True,
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "move_entity_pos", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 54
    # id сущности, properties (on_ground=1, steps=0), затем три i16.
    assert body == bytes([packet_id, 1, 1]) + struct.pack(">hhh", 100, 200, -50)
    assert packet.delta == VecDelta.linear(100, 200, -50)


def test_clientbound_move_entity_pos_rot_and_rot_round_trip():
    pos_rot = MoveEntityPosRot(
        id=2,
        delta=VecDelta.linear(10, -20, 30),
        rotation=(90, -45),
        on_ground=True,
    )
    rot = MoveEntityRot(id=3, rotation=(-90, 45), on_ground=False)

    pos_id, pos_body = round_trip(Clientbound, pos_rot)
    rot_id, rot_body = round_trip(Clientbound, rot)

    assert pos_id == id_of(
        "move_entity_pos_rot", State.PLAY, Direction.CLIENTBOUND
    )
    assert pos_body[1:3] == bytes([2, 1])
    assert pos_body[3:] == struct.pack(">hhh", 10, -20, 30) + bytes([90, 211])
    assert rot_id == id_of(
        "move_entity_rot", State.PLAY, Direction.CLIENTBOUND
    )
    # В Rust порядок: id, on_ground (bool), yaw i8, pitch i8.
    assert rot_body == bytes([rot_id, 3, 0, 166, 45])


def test_clientbound_entity_position_sync_round_trip():
    packet = EntityPositionSync(
        id=1,
        path=PositionPath.linear_path(1.0, 2.0, 3.0),
        yaw=90.0,
        pitch=-10.0,
        on_ground=True,
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "entity_position_sync", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 35
    assert body[1] == 1  # id сущности
    assert body[2] == 0  # PositionPath::Linear
    assert body[3:11] == struct.pack(">d", 1.0)
    assert body[-1] == 1  # on_ground

    stepped = EntityPositionSync(
        id=1,
        path=PositionPath.stepped([((1.0, 2.0, 3.0), 0), ((1.5, 2.0, 3.0), 2)]),
        yaw=0.0,
        pitch=0.0,
        on_ground=False,
    )
    round_trip(Clientbound, stepped)


def test_clientbound_update_attributes_round_trip():
    packet = UpdateAttributes(
        id=1,
        values=[
            AttributeSnapshot(
                attribute=2,
                base=20.0,
                modifiers=(
                    AttributeModifier("minecraft:generic.max_health", -2.0, 1),
                ),
            )
        ],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "update_attributes", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 134
    assert body[:2] == b"\x86\x01"  # VarInt 134
    assert body[2] == 1  # id сущности
    assert body[3] == 1  # число снапшотов
    assert body[4] == 2  # attribute VarInt
    assert body[5:13] == struct.pack(">d", 20.0)
    assert packet.values[0].modifiers[0].operation == 1


def test_clientbound_set_equipment_round_trip():
    packet = SetEquipment(
        id=1,
        slots=[(0, None), (1, ItemStack(item=5, count=2))],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "set_equipment", State.PLAY, Direction.CLIENTBOUND
    )
    # slot 0 с continuation-битом 128, пустой Slot (0), затем slot 1:
    # count=2, item=5, positive=0, negative=0.
    assert body == bytes([packet_id, 1, 128, 0, 1, 2, 5, 0, 0])
    assert packet.slots[0] == (0, None)
    assert packet.slots[1] == (1, ItemStack(item=5, count=2))


def test_clientbound_player_info_update_round_trip():
    uuid = 0xFEDCBA98765432100123456789ABCDEF
    packet = PlayerInfoUpdate(
        actions=5,  # ADD_PLAYER (1) | UPDATE_GAME_MODE (4)
        entries=[
            PlayerInfo(
                uuid=uuid,
                name="Alex",
                properties=[Property("textures", "abc", None)],
                game_mode=1,
            )
        ],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "player_info_update", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 71
    assert body[1] == 5  # actions bitset (u8)
    assert body[2] == 1  # число записей
    assert body[3:19] == uuid.to_bytes(16, "big")
    assert body[19:24] == b"\x04Alex"  # имя (StrN<16>)
    assert body[24] == 1  # число properties
    assert body[25:34] == b"\x08textures"
    assert body[34:38] == b"\x03abc"
    assert body[38] == 0  # signature отсутствует
    assert body[39] == 1  # game_mode VarInt

    # UPDATE_LATENCY (16) отдельно.
    latency = PlayerInfoUpdate(
        actions=16, entries=[PlayerInfo(uuid=uuid, latency=42)]
    )
    latency_id, latency_body = round_trip(Clientbound, latency)
    assert latency_id == packet_id
    assert latency_body == bytes([packet_id, 16, 1]) + uuid.to_bytes(
        16, "big"
    ) + bytes([42])


def test_clientbound_player_info_remove_and_set_passengers_round_trip():
    remove = PlayerInfoRemove(uuids=[1, 2])
    passengers = SetPassengers(vehicle=1, passengers=[2, 3])

    remove_id, remove_body = round_trip(Clientbound, remove)
    passengers_id, passengers_body = round_trip(Clientbound, passengers)

    assert remove_id == id_of(
        "player_info_remove", State.PLAY, Direction.CLIENTBOUND
    )
    assert remove_body == bytes([remove_id, 2]) + (1).to_bytes(
        16, "big"
    ) + (2).to_bytes(16, "big")
    assert passengers_id == id_of(
        "set_passengers", State.PLAY, Direction.CLIENTBOUND
    )
    assert passengers_body == bytes([passengers_id, 1, 2, 2, 3])


def test_clientbound_entity_event_and_animation_round_trip():
    event = EntityEvent(id=42, event=2)
    animate = Animate(id=7, action=3)
    hurt = HurtAnimation(id=7, yaw=90.0)
    head = RotateHead(id=7, head_yaw=-32)
    swing = SwingAnimation(id=7, hand=0, kind=1, duration=5)

    event_id, event_body = round_trip(Clientbound, event)
    animate_id, animate_body = round_trip(Clientbound, animate)
    hurt_id, hurt_body = round_trip(Clientbound, hurt)
    head_id, head_body = round_trip(Clientbound, head)
    swing_id, swing_body = round_trip(Clientbound, swing)

    assert event_id == id_of("entity_event", State.PLAY, Direction.CLIENTBOUND)
    assert event_body == bytes([event_id]) + struct.pack(">i", 42) + b"\x02"
    assert animate_id == id_of("animate", State.PLAY, Direction.CLIENTBOUND)
    assert animate_body == bytes([animate_id, 7, 3])
    assert hurt_id == id_of(
        "hurt_animation", State.PLAY, Direction.CLIENTBOUND
    )
    assert hurt_body == bytes([hurt_id, 7]) + struct.pack(">f", 90.0)
    assert head_id == id_of("rotate_head", State.PLAY, Direction.CLIENTBOUND)
    assert head_body == bytes([head_id, 7, 224])
    assert swing_id == id_of(
        "swing_animation", State.PLAY, Direction.CLIENTBOUND
    )
    assert swing_body == bytes([swing_id, 7, 0, 1, 5])


def test_clientbound_set_entity_motion_link_camera_round_trip():
    motion = SetEntityMotion(id=7, velocity=(0.0, 0.0, 0.0))
    link = SetEntityLink(source=5, dest=9)
    camera = SetCamera(camera_id=7)
    take = TakeItemEntity(item=3, player=4, amount=2)
    power = ProjectilePower(id=7, power=0.1)

    motion_id, motion_body = round_trip(Clientbound, motion)
    link_id, link_body = round_trip(Clientbound, link)
    camera_id, camera_body = round_trip(Clientbound, camera)
    take_id, take_body = round_trip(Clientbound, take)
    power_id, power_body = round_trip(Clientbound, power)

    assert motion_id == id_of(
        "set_entity_motion", State.PLAY, Direction.CLIENTBOUND
    )
    assert motion_body == bytes([motion_id, 7, 0])
    assert link_id == id_of(
        "set_entity_link", State.PLAY, Direction.CLIENTBOUND
    )
    assert link_body == bytes([link_id]) + struct.pack(">ii", 5, 9)
    assert camera_id == id_of("set_camera", State.PLAY, Direction.CLIENTBOUND)
    assert camera_body == bytes([camera_id, 7])
    assert take_id == id_of(
        "take_item_entity", State.PLAY, Direction.CLIENTBOUND
    )
    assert take_body == bytes([take_id, 3, 4, 2])
    assert power_id == id_of(
        "projectile_power", State.PLAY, Direction.CLIENTBOUND
    )
    assert power_body[:2] == b"\x8a\x01"
    assert power_body[2] == 7
    assert power_body[3:11] == struct.pack(">d", 0.1)


def test_clientbound_damage_event_round_trip():
    packet = DamageEvent(
        id=1,
        source_type=2,
        cause=3,
        direct=None,
        position=(1.0, 2.0, 3.0),
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "damage_event", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 25
    assert body[1] == 1  # id сущности
    assert body[2] == 2  # source_type
    assert body[3] == 4  # OptVarInt cause=3 -> 3 + 1
    assert body[4] == 0  # OptVarInt direct=None
    assert body[5] == 1  # Opt<Vec3d> присутствует
    assert body[6:14] == struct.pack(">d", 1.0)


def test_serverbound_interact_and_paddle_boat_round_trip():
    interact = Interact(
        id=5, hand=0, location=(0.0, 0.0, 0.0), secondary=True
    )
    boat = PaddleBoat(left=True, right=False)

    interact_id, interact_body = round_trip(Serverbound, interact)
    boat_id, boat_body = round_trip(Serverbound, boat)

    assert interact_id == id_of(
        "interact", State.PLAY, Direction.SERVERBOUND
    )
    assert interact_id == 26
    assert interact_body == bytes([interact_id, 5, 0, 0, 1])
    assert boat_id == id_of(
        "paddle_boat", State.PLAY, Direction.SERVERBOUND
    )
    assert boat_body == bytes([boat_id, 1, 0])


def test_serverbound_client_command_and_pick_item_round_trip():
    command = ClientCommand(action=0)
    pick = PickItemFromEntity(id=9, include_data=True)
    vehicle = MoveVehicleRequest(
        position=(1.5, 64.0, -2.5),
        yaw=90.0,
        pitch=0.0,
        on_ground=True,
    )

    command_id, command_body = round_trip(Serverbound, command)
    pick_id, pick_body = round_trip(Serverbound, pick)
    vehicle_id, vehicle_body = round_trip(Serverbound, vehicle)

    assert command_id == id_of(
        "client_command", State.PLAY, Direction.SERVERBOUND
    )
    assert command_body == bytes([command_id, 0])
    assert pick_id == id_of(
        "pick_item_from_entity", State.PLAY, Direction.SERVERBOUND
    )
    assert pick_body == bytes([pick_id, 9, 1])
    assert vehicle_id == id_of(
        "move_vehicle", State.PLAY, Direction.SERVERBOUND
    )
    assert vehicle_body[1:9] == struct.pack(">d", 1.5)
    assert vehicle_body[-1] == 1


def test_part3_replaces_unsupported_stubs():
    expected_clientbound = {
        "add_entity": AddEntity,
        "animate": Animate,
        "damage_event": DamageEvent,
        "entity_event": EntityEvent,
        "entity_position_sync": EntityPositionSync,
        "hurt_animation": HurtAnimation,
        "move_entity_pos": MoveEntityPos,
        "move_entity_pos_rot": MoveEntityPosRot,
        "move_entity_rot": MoveEntityRot,
        "move_vehicle": MoveVehicle,
        "player_info_remove": PlayerInfoRemove,
        "player_info_update": PlayerInfoUpdate,
        "projectile_power": ProjectilePower,
        "remove_entities": RemoveEntities,
        "rotate_head": RotateHead,
        "set_camera": SetCamera,
        "set_entity_data": SetEntityData,
        "set_entity_link": SetEntityLink,
        "set_entity_motion": SetEntityMotion,
        "set_equipment": SetEquipment,
        "set_passengers": SetPassengers,
        "swing_animation": SwingAnimation,
        "take_item_entity": TakeItemEntity,
        "update_attributes": UpdateAttributes,
    }
    for name, cls in expected_clientbound.items():
        packet_id = id_of(name, State.PLAY, Direction.CLIENTBOUND)
        assert ID_TO_CLASS[packet_id] is cls, name

    expected_serverbound = {
        "interact": Interact,
        "paddle_boat": PaddleBoat,
        "client_command": ClientCommand,
        "pick_item_from_entity": PickItemFromEntity,
        "move_vehicle": MoveVehicleRequest,
    }
    for name, cls in expected_serverbound.items():
        packet_id = id_of(name, State.PLAY, Direction.SERVERBOUND)
        assert SERVERBOUND_ID_TO_CLASS[packet_id] is cls, name
