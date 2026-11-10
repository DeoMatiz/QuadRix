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
    # PART 6
    AcceptTeleportation,
    AddTransientBlock,
    AwardStats,
    BlockChangedAck,
    BlockDestruction,
    BlockEntityData,
    BlockEntityInfo,
    BlockUpdate,
    BossAction,
    BossEvent,
    ChangeDifficulty,
    ChangeGameMode,
    ChunkBatchFinished,
    ChunkBatchReceived,
    ChunkData,
    ClearDialog,
    Explode,
    ExplosionParticle,
    ForgetLevelChunk,
    LevelChunkWithLight,
    LevelEvent,
    LightData,
    Particle,
    RecipeBookRemove,
    RecipeBookSettings,
    SectionBlocksUpdate,
    SetBorderSize,
    SetChunkCacheRadius,
    SetSimulationDistance,
    SignUpdate,
    UseItem,
    UpdateRecipes,
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


def test_part6_completes_play_rs():
    # PART 6 закрыл остаток play.rs: статистика — уже не заглушка, а
    # настоящий @dataclass с кодеком провода.
    stats_id = id_of("award_stats", State.PLAY, Direction.CLIENTBOUND)
    assert ID_TO_CLASS[stats_id] is AwardStats

    # Ни один класс dispatch больше не поднимает Unsupported.
    for cls in (
        *ID_TO_CLASS.values(),
        *SERVERBOUND_ID_TO_CLASS.values(),
    ):
        assert not getattr(cls, "_unsupported", False), cls.__name__

    assert issubclass(Unsupported, Exception)


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


# ═════════════════════════════════════════════════════════════════════
# PART 4 — чат и команды (play.rs)
# ═════════════════════════════════════════════════════════════════════


from quadrix.protocol.packets.play import (  # noqa: E402 — PART 4 блок
    Chat,
    ChatAck,
    ChatCommand,
    ChatCommandSigned,
    ChatSessionUpdate,
    ChatTypeBound,
    ClearTitles,
    CommandNode,
    CommandSuggestion,
    CommandSuggestions,
    Commands,
    CustomChatCompletions,
    DeleteChat,
    DisguisedChat,
    LastSeenUpdate,
    NumberFormat,
    PlayerChat,
    ResetScore,
    ServerData,
    SetActionBarText,
    SetPlayerTeam,
    SetScore,
    SetSubtitleText,
    SetTitleText,
    SetTitlesAnimation,
    SystemChat,
    TabList,
    TeamParameters,
)


def test_clientbound_system_chat_round_trip():
    content = compound(text=string("Привет, мир!"))
    packet = SystemChat(content=content, overlay=True)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "system_chat", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 124
    assert body[1] == int(TagType.Compound)  # сырой NBT, не VarInt-строка
    assert body[-1] == 1  # overlay
    assert packet.content == content


def test_clientbound_disguised_chat_round_trip():
    bound = ChatTypeBound(
        chat_type=1,
        name=compound(text=string("chat.type.text")),
        target=None,
    )
    packet = DisguisedChat(
        message=compound(text=string("hi")), chat_type=bound
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "disguised_chat", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 33
    assert body[1] == int(TagType.Compound)
    # ChatTypeBound: holder id + 1 (1 -> varint 2).
    assert bound.chat_type == 1
    assert packet.chat_type == bound


def test_clientbound_player_chat_round_trip():
    uuid = 0x0123456789ABCDEF0123456789ABCDEF
    bound = ChatTypeBound(
        chat_type=2,
        name=compound(text=string("chat.type.text")),
        target=compound(text=string("Alex")),
    )
    packet = PlayerChat(
        global_index=5,
        sender=uuid,
        index=3,
        signature=None,
        content="hello",
        timestamp=1000,
        salt=42,
        last_seen=[(2, None), (-1, b"\x11" * 256)],
        unsigned_content=compound(text=string("raw")),
        filter=(0, []),
        chat_type=bound,
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "player_chat", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 66
    assert body[1] == 5  # global_index
    assert body[2:18] == uuid.to_bytes(16, "big")
    assert body[18] == 3  # index
    assert body[19] == 0  # signature отсутствует
    assert packet.salt == 42
    assert packet.last_seen == [(2, None), (-1, b"\x11" * 256)]


def test_clientbound_delete_chat_round_trip():
    packet = DeleteChat(signature=(-1, b"\x00" * 256))

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "delete_chat", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 31
    # varint(-1 + 1) = 0, затем 256 байт подписи.
    assert body[1] == 0
    assert len(body) == 2 + 256


def test_clientbound_command_suggestions_round_trip():
    packet = CommandSuggestions(
        id=7,
        start=0,
        length=3,
        matches=[
            ("abc", None),
            ("abd", compound(text=string("tooltip"))),
        ],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "command_suggestions", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 15
    assert body[1] == 7  # id
    assert body[2] == 0  # start
    assert body[3] == 3  # length
    assert body[4] == 2  # число matches
    assert packet.matches[0] == ("abc", None)
    assert packet.matches[1][0] == "abd"


def test_clientbound_commands_round_trip():
    nodes = [
        CommandNode(
            kind=0,
            executable=False,
            restricted=False,
            children=[1, 2],
            redirect=None,
            name="",
            parser=None,
            suggestions=None,
        ),
        CommandNode(
            kind=1,
            executable=True,
            restricted=False,
            children=[],
            redirect=None,
            name="run",
            parser=None,
            suggestions=None,
        ),
        CommandNode(
            kind=2,
            executable=False,
            restricted=False,
            children=[],
            redirect=0,
            name="value",
            parser=(5, b"\x01"),  # brigadier:string, property = VarInt 1
            suggestions="minecraft:ask_server",
        ),
    ]
    packet = Commands(nodes=nodes, root=0)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of("commands", State.PLAY, Direction.CLIENTBOUND)
    assert packet_id == 16
    assert body[1] == 3  # число узлов
    assert packet.nodes[2].redirect == 0
    assert packet.nodes[2].parser == (5, b"\x01")
    assert packet.nodes[2].suggestions == "minecraft:ask_server"


def test_clientbound_commands_rejects_a_cycle():
    cyc = [
        CommandNode(
            kind=0,
            executable=False,
            restricted=False,
            children=[0],
            redirect=None,
            name="",
            parser=None,
            suggestions=None,
        )
    ]
    body = Commands(nodes=cyc, root=0).encode()
    with pytest.raises(ProtocolError):
        Clientbound.decode(16, body)


def test_clientbound_titles_round_trip():
    title = SetTitleText(text=compound(text=string("Title")))
    subtitle = SetSubtitleText(text=compound(text=string("Sub")))
    action = SetActionBarText(text=compound(text=string("Bar")))
    times = SetTitlesAnimation(fade_in=10, stay=70, fade_out=20)
    clear = ClearTitles(value=True)

    assert round_trip(Clientbound, title)[0] == id_of(
        "set_title_text", State.PLAY, Direction.CLIENTBOUND
    )
    assert round_trip(Clientbound, subtitle)[0] == id_of(
        "set_subtitle_text", State.PLAY, Direction.CLIENTBOUND
    )
    assert round_trip(Clientbound, action)[0] == id_of(
        "set_action_bar_text", State.PLAY, Direction.CLIENTBOUND
    )
    times_id, times_body = round_trip(Clientbound, times)
    assert times_id == id_of(
        "set_titles_animation", State.PLAY, Direction.CLIENTBOUND
    )
    assert times_body == bytes([times_id]) + struct.pack(
        ">iii", 10, 70, 20
    )
    clear_id, clear_body = round_trip(Clientbound, clear)
    assert clear_id == id_of(
        "clear_titles", State.PLAY, Direction.CLIENTBOUND
    )
    assert clear_body == bytes([clear_id, 1])


def test_clientbound_set_player_team_round_trip():
    packet = SetPlayerTeam(
        name="team1",
        method=0,
        parameters=TeamParameters(
            display_name=compound(text=string("Team")),
            prefix=compound(text=string("[")),
            suffix=compound(text=string("]")),
            name_tag_visibility=0,
            collision_rule=0,
            color=1,
            options=3,
        ),
        players=["Alex", "Steve"],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "set_player_team", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 111
    assert body[1:7] == b"\x05team1"
    assert body[7] == 0  # method
    assert packet.players == ["Alex", "Steve"]

    # method 1 (remove) не несёт ни параметров, ни игроков.
    removed = SetPlayerTeam("team1", 1, None, [])
    remove_id, remove_body = round_trip(Clientbound, removed)
    assert remove_body == bytes([remove_id, 5]) + b"team1" + bytes([1])


def test_clientbound_set_and_reset_score_round_trip():
    score = SetScore(
        owner="Alex",
        objective="points",
        score=42,
        display=compound(text=string("42")),
        number_format=NumberFormat.fixed(compound(text=string("42"))),
    )
    reset = ResetScore(owner="Alex", objective=None)

    score_id, _ = round_trip(Clientbound, score)
    reset_id, reset_body = round_trip(Clientbound, reset)

    assert score_id == id_of("set_score", State.PLAY, Direction.CLIENTBOUND)
    assert reset_id == id_of("reset_score", State.PLAY, Direction.CLIENTBOUND)
    assert reset_body == bytes([reset_id, 4]) + b"Alex" + bytes([0])
    assert score.number_format == NumberFormat.fixed(
        compound(text=string("42"))
    )


def test_clientbound_server_data_and_completions_round_trip():
    server = ServerData(
        motd=compound(text=string("MOTD")), icon=b"\x01\x02\x03"
    )
    completions = CustomChatCompletions(action=2, entries=["/say", "/time"])
    tab = TabList(
        header=compound(text=string("H")),
        footer=compound(text=string("F")),
    )

    server_id, _ = round_trip(Clientbound, server)
    completions_id, completions_body = round_trip(Clientbound, completions)
    tab_id, _ = round_trip(Clientbound, tab)

    assert server_id == id_of("server_data", State.PLAY, Direction.CLIENTBOUND)
    assert completions_id == id_of(
        "custom_chat_completions", State.PLAY, Direction.CLIENTBOUND
    )
    assert completions_body[1] == 2
    assert completions_body[2] == 2  # две записи
    assert tab_id == id_of("tab_list", State.PLAY, Direction.CLIENTBOUND)


def test_serverbound_chat_round_trip():
    last_seen = LastSeenUpdate(
        offset=3, acknowledged=b"\x00\x00\x00", checksum=1
    )
    packet = Chat(
        message="hello world",
        timestamp=123456789,
        salt=99,
        signature=None,
        last_seen=last_seen,
    )

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of("chat", State.PLAY, Direction.SERVERBOUND)
    assert packet_id == 9
    assert body[1] == 11  # длина строки "hello world"
    assert body[2:13] == b"hello world"
    assert packet.timestamp == 123456789
    assert packet.salt == 99
    assert body[13] == 0  # подпись отсутствует


def test_serverbound_chat_command_and_ack_round_trip():
    command = ChatCommand(command="say hi")
    ack = ChatAck(offset=7)

    command_id, command_body = round_trip(Serverbound, command)
    ack_id, ack_body = round_trip(Serverbound, ack)

    assert command_id == id_of(
        "chat_command", State.PLAY, Direction.SERVERBOUND
    )
    assert command_id == 7
    assert command_body == bytes([command_id, 6]) + b"say hi"
    assert ack_id == id_of("chat_ack", State.PLAY, Direction.SERVERBOUND)
    assert ack_body == bytes([ack_id, 7])


def test_serverbound_chat_command_signed_round_trip():
    packet = ChatCommandSigned(
        command="msg Alex hi",
        timestamp=1000,
        salt=7,
        arguments=[("target", b"\x01" * 256)],
        last_seen=LastSeenUpdate(
            offset=1, acknowledged=b"\x01\x02\x03", checksum=-5
        ),
    )

    packet_id, _ = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "chat_command_signed", State.PLAY, Direction.SERVERBOUND
    )
    assert packet_id == 8
    assert packet.arguments[0][0] == "target"
    assert len(packet.arguments[0][1]) == 256


def test_serverbound_chat_session_update_round_trip():
    packet = ChatSessionUpdate(
        session=0xAAAA,
        expires_at=1700000000000,
        key=b"key-bytes",
        key_signature=b"signature-bytes",
    )

    packet_id, _ = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "chat_session_update", State.PLAY, Direction.SERVERBOUND
    )
    assert packet.session == 0xAAAA
    assert packet.expires_at == 1700000000000


def test_serverbound_command_suggestion_round_trip():
    packet = CommandSuggestion(id=2, text="execute ")

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "command_suggestion", State.PLAY, Direction.SERVERBOUND
    )
    assert packet_id == 15
    assert body == bytes([packet_id, 2, 8]) + b"execute "


def test_part4_replaces_unsupported_stubs():
    expected_clientbound = {
        "system_chat": SystemChat,
        "player_chat": PlayerChat,
        "disguised_chat": DisguisedChat,
        "delete_chat": DeleteChat,
        "command_suggestions": CommandSuggestions,
        "commands": Commands,
        "set_title_text": SetTitleText,
        "set_subtitle_text": SetSubtitleText,
        "set_action_bar_text": SetActionBarText,
        "set_titles_animation": SetTitlesAnimation,
        "clear_titles": ClearTitles,
        "set_player_team": SetPlayerTeam,
        "set_score": SetScore,
        "reset_score": ResetScore,
        "server_data": ServerData,
        "custom_chat_completions": CustomChatCompletions,
        "tab_list": TabList,
    }
    for name, cls in expected_clientbound.items():
        packet_id = id_of(name, State.PLAY, Direction.CLIENTBOUND)
        assert ID_TO_CLASS[packet_id] is cls, name

    expected_serverbound = {
        "chat": Chat,
        "chat_command": ChatCommand,
        "chat_ack": ChatAck,
        "chat_command_signed": ChatCommandSigned,
        "chat_session_update": ChatSessionUpdate,
        "command_suggestion": CommandSuggestion,
    }
    for name, cls in expected_serverbound.items():
        packet_id = id_of(name, State.PLAY, Direction.SERVERBOUND)
        assert SERVERBOUND_ID_TO_CLASS[packet_id] is cls, name


# ═════════════════════════════════════════════════════════════════════
# PART 5 — инвентарь, слоты и контейнеры (play.rs)
# ═════════════════════════════════════════════════════════════════════


from quadrix.protocol.packets.play import (  # noqa: E402 — PART 5 блок
    ContainerButtonClick,
    ContainerClick,
    ContainerClose,
    ContainerSetContent,
    ContainerSetData,
    ContainerSetSlot,
    ContainerSlotStateChanged,
    Cooldown,
    EditBook,
    Hashed,
    MerchantOffers,
    NetCost,
    NetOffer,
    OpenScreen,
    RenameItem,
    SelectTrade,
    SetCreativeModeSlot,
    SetCursorItem,
    SetPlayerInventory,
)


def test_clientbound_container_set_content_round_trip():
    # Сверить с Rust: ContainerSetContent { container, state,
    # items: Vec<Option<Stack>> => List<Slot>, carried: Option<Stack> }.
    packet = ContainerSetContent(
        container=0, state=1, items=[None] * 46, carried=None
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "container_set_content", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet_id == 18
    # container 0, state 1, размер списка 46, 46 пустых слотов, курсор пуст.
    assert body == bytes([packet_id, 0, 1, 46]) + b"\x00" * 47
    assert len(packet.items) == 46
    assert packet.carried is None


def test_clientbound_container_set_slot_and_data_round_trip():
    slot = ContainerSetSlot(container=0, state=1, slot=36, item=None)
    data = ContainerSetData(container=0, id=1, value=100)

    slot_id, slot_body = round_trip(Clientbound, slot)
    data_id, data_body = round_trip(Clientbound, data)

    assert slot_id == id_of(
        "container_set_slot", State.PLAY, Direction.CLIENTBOUND
    )
    assert slot_id == 20
    # container 0, state 1, slot Short 36, пустой предмет.
    assert slot_body == bytes([slot_id, 0, 1]) + struct.pack(">h", 36) + b"\x00"
    assert data_id == id_of(
        "container_set_data", State.PLAY, Direction.CLIENTBOUND
    )
    assert data_id == 19
    # container 0, property Short 1, value Short 100.
    assert data_body == bytes([data_id, 0]) + struct.pack(">hh", 1, 100)
    assert slot.item is None
    assert data.value == 100


def test_serverbound_container_click_round_trip():
    # Rust ContainerClick: container, state, slot Short, button i8,
    # input VarInt, changed (slot, Option<Hashed>), carried Option<Hashed>.
    packet = ContainerClick(
        container=0,
        state=1,
        slot=36,
        button=0,
        input=0,
        changed=[(36, Hashed(item=1, count=1))],
        carried=None,
    )

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of("container_click", State.PLAY, Direction.SERVERBOUND)
    assert packet_id == 18
    assert body[1] == 0  # container
    assert body[2] == 1  # state
    assert body[3:5] == struct.pack(">h", 36)  # slot
    assert body[5] == 0  # button i8
    assert body[6] == 0  # input VarInt
    assert body[7] == 1  # changed: одна запись
    assert body[8:10] == struct.pack(">h", 36)  # slot изменения
    assert body[10] == 1  # Hashed присутствует
    assert packet.changed == [(36, Hashed(item=1, count=1))]
    assert packet.carried is None


def test_serverbound_set_creative_mode_slot_round_trip():
    packet = SetCreativeModeSlot(slot=36, item=None)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "set_creative_mode_slot", State.PLAY, Direction.SERVERBOUND
    )
    assert packet_id == 57
    assert body == bytes([packet_id]) + struct.pack(">h", 36) + b"\x00"
    assert packet.slot == 36 and packet.item is None


def test_serverbound_container_button_click_round_trip():
    packet = ContainerButtonClick(container=0, button=1)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "container_button_click", State.PLAY, Direction.SERVERBOUND
    )
    assert packet_id == 17
    assert body == bytes([packet_id, 0, 1])
    assert packet.button == 1


def test_serverbound_rename_item_round_trip():
    packet = RenameItem(name="Меч-кладенец")

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of("rename_item", State.PLAY, Direction.SERVERBOUND)
    assert packet_id == 49
    # STRING_UTF8: длина — в байтах UTF-8.
    assert body[1] == len(packet.name.encode("utf-8"))
    assert packet.name == "Меч-кладенец"


def test_clientbound_open_screen_round_trip():
    title = compound(text=string("Сундук"))
    packet = OpenScreen(container=2, menu=0, title=title)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of("open_screen", State.PLAY, Direction.CLIENTBOUND)
    assert packet_id == 60
    assert body[1] == 2  # container VarInt
    assert body[2] == 0  # menu VarInt (тип меню)
    assert body[3] == int(TagType.Compound)  # title — сырой NBT
    assert packet.title == title


def test_serverbound_edit_book_round_trip():
    packet = EditBook(
        slot=0,
        pages=["Первая", "Вторая"],
        title="Дневник",
    )

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == id_of("edit_book", State.PLAY, Direction.SERVERBOUND)
    assert packet_id == 24
    assert body[1] == 0  # slot VarInt
    assert body[2] == 2  # число страниц
    assert body[3] == len("Первая".encode("utf-8"))
    assert packet.pages == ["Первая", "Вторая"]
    assert packet.title == "Дневник"

    # Без подписи title отсутствует (Opt).
    untitled = EditBook(slot=40, pages=[], title=None)
    round_trip(Serverbound, untitled)
    assert untitled.title is None


def test_clientbound_container_close_and_cursor_and_inventory_round_trip():
    close = ContainerClose(container=3)
    cursor = SetCursorItem(item=None)
    inventory = SetPlayerInventory(
        slot=36, item=ItemStack(item=1, count=1)
    )

    close_id, close_body = round_trip(Clientbound, close)
    cursor_id, cursor_body = round_trip(Clientbound, cursor)
    inventory_id, inventory_body = round_trip(Clientbound, inventory)

    assert close_id == id_of(
        "container_close", State.PLAY, Direction.CLIENTBOUND
    )
    assert close_body == bytes([close_id, 3])
    assert cursor_id == id_of(
        "set_cursor_item", State.PLAY, Direction.CLIENTBOUND
    )
    assert cursor_body == bytes([cursor_id, 0])
    assert inventory_id == id_of(
        "set_player_inventory", State.PLAY, Direction.CLIENTBOUND
    )
    assert inventory_body == bytes([inventory_id, 36, 1, 1, 0, 0])
    assert inventory.item == ItemStack(item=1, count=1)


def test_clientbound_cooldown_and_merchant_offers_round_trip():
    cooldown = Cooldown(group="minecraft:use_cooldown", duration=40)
    offer = NetOffer(
        cost_a=NetCost(item=1, count=2),
        result=ItemStack(item=5, count=1),
        cost_b=None,
        out_of_stock=False,
        uses=0,
        max_uses=7,
        xp=1,
        special_price=0,
        price_multiplier=1.0,
        demand=0,
    )
    offers = MerchantOffers(
        container=1,
        offers=[offer],
        level=1,
        xp=3,
        show_progress=True,
        can_restock=False,
    )

    cooldown_id, cooldown_body = round_trip(Clientbound, cooldown)
    offers_id, offers_body = round_trip(Clientbound, offers)

    assert cooldown_id == id_of("cooldown", State.PLAY, Direction.CLIENTBOUND)
    assert cooldown_id == 22
    assert cooldown_body[1] == len("minecraft:use_cooldown")
    assert cooldown_body[-1] == 40
    assert offers_id == id_of(
        "merchant_offers", State.PLAY, Direction.CLIENTBOUND
    )
    assert offers_id == 53
    assert offers_body[1] == 1  # container
    assert offers_body[2] == 1  # число предложений
    assert offers.offers[0].max_uses == 7
    assert offers.can_restock is False


def test_serverbound_container_slot_state_and_select_trade_round_trip():
    toggle = ContainerSlotStateChanged(slot=3, container=1, enabled=True)
    trade = SelectTrade(item=2)

    toggle_id, toggle_body = round_trip(Serverbound, toggle)
    trade_id, trade_body = round_trip(Serverbound, trade)

    assert toggle_id == id_of(
        "container_slot_state_changed", State.PLAY, Direction.SERVERBOUND
    )
    assert toggle_body == bytes([toggle_id, 3, 1, 1])
    assert trade_id == id_of("select_trade", State.PLAY, Direction.SERVERBOUND)
    assert trade_id == 52
    assert trade_body == bytes([trade_id, 2])


def test_invalid_component_payload_is_rejected():
    # Непустые патчи компонент теперь реально кодируются. Но значение
    # компоненты обязано быть вариантом ``Component`` из item_data; чужая
    # полезная нагрузка (object()) по-прежнему отвергается при записи.
    packet = ContainerSetSlot(
        container=0,
        state=1,
        slot=0,
        item=ItemStack(item=1, count=1, added=[(5, object())]),
    )
    with pytest.raises(ProtocolError):
        Clientbound.encode(packet)


def test_part5_replaces_unsupported_stubs():
    expected_clientbound = {
        "container_close": ContainerClose,
        "container_set_content": ContainerSetContent,
        "container_set_data": ContainerSetData,
        "container_set_slot": ContainerSetSlot,
        "merchant_offers": MerchantOffers,
        "open_screen": OpenScreen,
        "set_cursor_item": SetCursorItem,
        "set_player_inventory": SetPlayerInventory,
        "cooldown": Cooldown,
    }
    for name, cls in expected_clientbound.items():
        packet_id = id_of(name, State.PLAY, Direction.CLIENTBOUND)
        assert ID_TO_CLASS[packet_id] is cls, name

    expected_serverbound = {
        "container_button_click": ContainerButtonClick,
        "container_click": ContainerClick,
        "container_close": ContainerClose,
        "container_slot_state_changed": ContainerSlotStateChanged,
        "edit_book": EditBook,
        "rename_item": RenameItem,
        "set_creative_mode_slot": SetCreativeModeSlot,
        "select_trade": SelectTrade,
    }
    for name, cls in expected_serverbound.items():
        packet_id = id_of(name, State.PLAY, Direction.SERVERBOUND)
        assert SERVERBOUND_ID_TO_CLASS[packet_id] is cls, name


# ═════════════════════════════════════════════════════════════════════
# PART 6 — мир, чанки, свет, границы, погода, рецепты и остаток
# ═════════════════════════════════════════════════════════════════════


def test_level_chunk_with_light_round_trip_raw_buffer():
    # Буфер секций остаётся сырым: тут его не разбираем в полноценный Chunk.
    layer = bytes([0xAB]) * 2048
    entity = BlockEntityInfo(
        packed_xz=3, y=64, kind=1, tag=compound(x=Tag(TagType.Int, int_val=7))
    )
    chunk = ChunkData(
        heightmaps=[(1, [0, 0])],
        buffer=b"\xDE\xAD\xBE\xEF",
        block_entities=[entity],
    )
    light = LightData(
        sky_mask=bytearray(b"\x01"),
        block_mask=bytearray(b"\x02"),
        empty_sky_mask=bytearray(),
        empty_block_mask=bytearray(),
        sky=[layer],
        block=[layer, layer],
    )
    packet = LevelChunkWithLight(x=12, z=-7, chunk=chunk, light=light)

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "level_chunk_with_light", State.PLAY, Direction.CLIENTBOUND
    )
    # Сразу за id — два Int (x, z), затем сырой буфер чанка.
    assert body[1:5] == (12).to_bytes(4, "big", signed=True)
    assert body[5:9] == (-7).to_bytes(4, "big", signed=True)
    assert b"\xDE\xAD\xBE\xEF" in body
    assert packet.chunk.buffer == b"\xDE\xAD\xBE\xEF"
    assert len(packet.light.sky[0]) == 2048


def test_forget_level_chunk_and_block_update_round_trip():
    forget = ForgetLevelChunk(pos=(5, -7))
    update = BlockUpdate(pos=(1, 64, -3), state=42)

    forget_id, _ = round_trip(Clientbound, forget)
    update_id, update_body = round_trip(Clientbound, update)

    assert forget_id == id_of(
        "forget_level_chunk", State.PLAY, Direction.CLIENTBOUND
    )
    assert forget_id != update_id
    assert update_id == id_of("block_update", State.PLAY, Direction.CLIENTBOUND)
    assert int.from_bytes(update_body[1:9], "big", signed=True) == (
        pack_block_pos((1, 64, -3))
    )
    assert update_body[9] == 42
    assert len(update_body) == 10


def test_section_blocks_update_and_block_entity_data_round_trip():
    section = SectionBlocksUpdate(
        section=(2, -1, 3), changes=[1, 2, 300, 123456]
    )
    be_data = BlockEntityData(
        pos=(10, 20, 30),
        kind=7,
        tag=compound(text=string('{"text":"Сундук"}')),
    )

    section_id, _ = round_trip(Clientbound, section)
    be_id, _ = round_trip(Clientbound, be_data)

    assert section_id == id_of(
        "section_blocks_update", State.PLAY, Direction.CLIENTBOUND
    )
    assert section.changes == [1, 2, 300, 123456]
    assert be_id == id_of(
        "block_entity_data", State.PLAY, Direction.CLIENTBOUND
    )
    assert be_data.tag.compound_val["text"].str_val == '{"text":"Сундук"}'


def test_level_event_and_block_destruction_round_trip():
    event = LevelEvent(kind=2001, pos=(1, 2, 3), data=0, global_=True)
    destruction = BlockDestruction(id=3, pos=(4, 5, 6), progress=7)

    event_id, event_body = round_trip(Clientbound, event)
    destruction_id, destruction_body = round_trip(Clientbound, destruction)

    assert event_id == id_of("level_event", State.PLAY, Direction.CLIENTBOUND)
    assert event_body[1:5] == (2001).to_bytes(4, "big", signed=True)
    assert event_body[-1] == 1  # global_
    assert destruction_id == id_of(
        "block_destruction", State.PLAY, Direction.CLIENTBOUND
    )
    assert destruction_body[1] == 3  # VarInt id
    assert destruction_body[-1] == 7  # u8 progress


def test_explosion_round_trip_with_sound_holder():
    particle = Particle(id=0)
    block_particle = ExplosionParticle(
        particle=Particle(id=0), scaling=1.5, speed=0.5, weight=3
    )
    packet = Explode(
        center=(1.0, 2.0, 3.0),
        radius=4.0,
        block_count=5,
        knockback=(0.1, 0.2, 0.3),
        particle=particle,
        sound=(-1, ("minecraft:entity.generic.explode", None)),
        block_particles=[block_particle],
        play_sound=True,
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == id_of("explode", State.PLAY, Direction.CLIENTBOUND)
    assert packet.sound == (-1, ("minecraft:entity.generic.explode", None))
    assert packet.block_particles[0].weight == 3
    assert packet.play_sound is True


def test_border_size_and_chunk_distances_round_trip():
    border = SetBorderSize(size=29999984.0)
    radius = SetChunkCacheRadius(distance=10)
    simulation = SetSimulationDistance(distance=8)

    border_id, border_body = round_trip(Clientbound, border)
    radius_id, radius_body = round_trip(Clientbound, radius)
    simulation_id, simulation_body = round_trip(Clientbound, simulation)

    assert border_id == id_of(
        "set_border_size", State.PLAY, Direction.CLIENTBOUND
    )
    assert border_body[1:] == struct.pack(">d", 29999984.0)
    assert radius_id == id_of(
        "set_chunk_cache_radius", State.PLAY, Direction.CLIENTBOUND
    )
    assert simulation_id == id_of(
        "set_simulation_distance", State.PLAY, Direction.CLIENTBOUND
    )
    # Один Rust-структ Distance обслуживает два разных ID.
    assert radius_id != simulation_id
    assert radius_body == bytes([radius_id, 10])
    assert simulation_body == bytes([simulation_id, 8])


def test_recipe_book_packets_round_trip():
    remove = RecipeBookRemove(ids=[1, 2, 300])
    settings = RecipeBookSettings(
        books=[(True, False), (False, True), (True, True), (False, False)]
    )

    remove_id, remove_body = round_trip(Clientbound, remove)
    settings_id, settings_body = round_trip(Clientbound, settings)

    assert remove_id == id_of(
        "recipe_book_remove", State.PLAY, Direction.CLIENTBOUND
    )
    assert remove_body[1] == 3  # число id
    assert settings_id == id_of(
        "recipe_book_settings", State.PLAY, Direction.CLIENTBOUND
    )
    assert settings_body[1:] == bytes([1, 0, 0, 1, 1, 1, 0, 0])


def test_serverbound_part6_round_trip():
    teleport = AcceptTeleportation(
        id=9, x=1.0, y=2.0, z=3.0, yaw=90.0, pitch=-45.0
    )
    mode = ChangeGameMode(mode=1)
    batch = ChunkBatchReceived(chunks_per_tick=8.5)
    sign = SignUpdate(pos=(1, 2, 3), lines=["a", "b", "c", "d"], front=True)
    use = UseItem(hand=0, sequence=7, yaw=0.0, pitch=0.0)

    teleport_id, _ = round_trip(Serverbound, teleport)
    mode_id, mode_body = round_trip(Serverbound, mode)
    batch_id, _ = round_trip(Serverbound, batch)
    sign_id, _ = round_trip(Serverbound, sign)
    use_id, _ = round_trip(Serverbound, use)

    assert teleport_id == id_of(
        "accept_teleportation", State.PLAY, Direction.SERVERBOUND
    )
    assert teleport.yaw == 90.0
    assert mode_id == id_of("change_game_mode", State.PLAY, Direction.SERVERBOUND)
    assert mode_body == bytes([mode_id, 1])
    assert batch_id == id_of(
        "chunk_batch_received", State.PLAY, Direction.SERVERBOUND
    )
    assert sign.lines == ["a", "b", "c", "d"]
    assert use.sequence == 7


def test_unmodeled_ids_pass_through_raw():
    # update_recipes Rust не моделирует: payload идёт как есть (как Unknown).
    recipe_id = id_of("update_recipes", State.PLAY, Direction.CLIENTBOUND)

    packet = Clientbound.decode(recipe_id, b"\x01\x02\x03")
    assert isinstance(packet, UpdateRecipes)
    assert packet.payload == b"\x01\x02\x03"

    _, body = round_trip(Clientbound, packet)
    expected = Writer()
    expected.varint(recipe_id)
    expected.bytes(b"\x01\x02\x03")
    assert body == bytes(expected.data)


def test_play_rs_fully_implemented():
    # Ни один смоделированный Rust ID не остался заглушкой Unsupported.
    for packet_id, cls in ID_TO_CLASS.items():
        assert not getattr(cls, "_unsupported", False), (
            packet_id,
            cls.__name__,
        )
    for packet_id, cls in SERVERBOUND_ID_TO_CLASS.items():
        assert not getattr(cls, "_unsupported", False), (
            packet_id,
            cls.__name__,
        )

    # Плюс таблицы dispatch покрывают все ID из ids.py.
    assert len(ID_TO_CLASS) == len(ids.play.clientbound.NAMES)
    assert len(SERVERBOUND_ID_TO_CLASS) == len(ids.play.serverbound.NAMES)


# ═════════════════════════════════════════════════════════════════════
# PART 3/5 — компоненты ItemStack на проводе (item.rs)
#
# _Slot / _Template / DelimitedSlot больше не отвергают непустые патчи
# компонент: значения читаются и пишутся через item_data. Здесь проверяем
# реальные компоненты (damage, custom_name) в пакетах PART 3 и PART 5.
# ═════════════════════════════════════════════════════════════════════


from quadrix.items.item_data import (  # noqa: E402 — блок компонент
    ComponentInt,
    ComponentText,
    component_id,
)
from quadrix.items.items import ITEM_REGISTRY  # noqa: E402


def protocol_item(name: str) -> int:
    """Сетевой id предмета = индекс в реестре сетевого порядка."""
    return ITEM_REGISTRY.registry_order.index(name)


DAMAGE_COMPONENT = component_id("minecraft:damage")
CUSTOM_NAME_COMPONENT = component_id("minecraft:custom_name")


def test_play_set_equipment_round_trip_with_components():
    # SetEquipment несёт пары (slot, Option<Stack>); Stack с damage.
    packet = SetEquipment(
        id=7,
        slots=[
            (0, None),
            (1, ItemStack(item=protocol_item("minecraft:diamond_sword"), count=1,
                          added=[(DAMAGE_COMPONENT, ComponentInt(50))])),
        ],
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == id_of("set_equipment", State.PLAY, Direction.CLIENTBOUND)
    assert packet.slots[0] == (0, None)
    stack = packet.slots[1][1]
    assert stack.item == protocol_item("minecraft:diamond_sword")
    assert stack.damage() == 50


def test_play_container_set_content_round_trip_with_components():
    packet = ContainerSetContent(
        container=0,
        state=1,
        items=[
            None,
            ItemStack(item=protocol_item("minecraft:stone"), count=32),
            ItemStack(item=protocol_item("minecraft:diamond_sword"), count=1,
                      added=[(DAMAGE_COMPONENT, ComponentInt(50))]),
        ],
        carried=None,
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "container_set_content", State.PLAY, Direction.CLIENTBOUND
    )
    assert packet.items[1].count == 32
    assert packet.items[1].added == []
    assert packet.items[2].damage() == 50


def test_play_container_set_slot_round_trip_with_custom_name():
    name = string("test")
    packet = ContainerSetSlot(
        container=0,
        state=1,
        slot=36,
        item=ItemStack(
            item=protocol_item("minecraft:stone"),
            count=1,
            added=[(CUSTOM_NAME_COMPONENT, ComponentText(name))],
        ),
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == id_of(
        "container_set_slot", State.PLAY, Direction.CLIENTBOUND
    )
    comp = packet.item.component(CUSTOM_NAME_COMPONENT)
    assert isinstance(comp, ComponentText)
    assert comp.tag == name


def test_play_set_creative_mode_slot_round_trip_with_components():
    # Rust: item => DelimitedSlot (каждая компонента за своей длиной).
    packet = SetCreativeModeSlot(
        slot=36,
        item=ItemStack(item=protocol_item("minecraft:diamond_sword"), count=1,
                       added=[(DAMAGE_COMPONENT, ComponentInt(50))]),
    )

    packet_id, _ = round_trip(Serverbound, packet)

    assert packet_id == id_of(
        "set_creative_mode_slot", State.PLAY, Direction.SERVERBOUND
    )
    assert packet.item.damage() == 50


def test_play_set_cursor_item_and_inventory_round_trip_with_components():
    cursor = SetCursorItem(
        item=ItemStack(item=protocol_item("minecraft:stone"), count=5)
    )
    inventory = SetPlayerInventory(
        slot=36,
        item=ItemStack(item=protocol_item("minecraft:stone"), count=5),
    )

    cursor_id, _ = round_trip(Clientbound, cursor)
    inventory_id, _ = round_trip(Clientbound, inventory)

    assert cursor_id == id_of(
        "set_cursor_item", State.PLAY, Direction.CLIENTBOUND
    )
    assert inventory_id == id_of(
        "set_player_inventory", State.PLAY, Direction.CLIENTBOUND
    )
    assert cursor.item.count == 5
    assert inventory.item.count == 5


def test_play_merchant_offers_round_trip_with_item_cost_components():
    # ItemCost.STREAM_CODEC: item, count, список (kind, Component) без
    # patch-removal count.
    offer = NetOffer(
        cost_a=NetCost(
            item=protocol_item("minecraft:stone"),
            count=32,
            components=((DAMAGE_COMPONENT, ComponentInt(3)),),
        ),
        result=ItemStack(item=protocol_item("minecraft:diamond_sword"), count=1,
                         added=[(DAMAGE_COMPONENT, ComponentInt(50))]),
        cost_b=None,
        out_of_stock=False,
        uses=0,
        max_uses=7,
        xp=1,
        special_price=0,
        price_multiplier=1.0,
        demand=0,
    )
    offers = MerchantOffers(
        container=1,
        offers=[offer],
        level=1,
        xp=3,
        show_progress=True,
        can_restock=False,
    )

    packet_id, _ = round_trip(Clientbound, offers)

    assert packet_id == id_of(
        "merchant_offers", State.PLAY, Direction.CLIENTBOUND
    )
    assert offers.offers[0].cost_a.components == ((DAMAGE_COMPONENT, ComponentInt(3)),)
    assert offers.offers[0].result.damage() == 50


def test_play_item_stack_trailing_bytes_are_rejected():
    # Лишний байт после реального Stack — ProtocolError (тело не дочитано).
    packet = SetCursorItem(
        item=ItemStack(item=protocol_item("minecraft:stone"), count=1)
    )
    _, body = round_trip(Clientbound, packet)
    packet_id = body[0]
    with pytest.raises(ProtocolError):
        Clientbound.decode(packet_id, body[1:] + b"\x00")

