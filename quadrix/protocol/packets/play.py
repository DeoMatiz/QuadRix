# Порт horizon-protocol/src/packets/play.rs —
# PART 1 (framework) + PART 2 (движение/позиция/тики).
#
# play.rs — самое большое состояние протокола (мир, сущности, инвентарь,
# чат, чанки). PART 1 дал КАРКАС:
#   * полные таблицы ID clientbound и serverbound (из ids.py, как
#     packet_enum! в Rust);
#   * диспетчеризация decode/encode по ID и по типу пакета;
#   * три простых clientbound-пакета: BundleDelimiter, Disconnect,
#     KeepAlive;
#   * три простых serverbound-пакета: ClientTickEnd, KeepAlive,
#     PlayerLoaded.
#
# PART 2 заменил заглушки реальными @dataclass + encode/decode для
# движения/позиции/тиков (см. раздел «PART 2» ниже): GameEvent,
# PlayerLookAt, PlayerPosition, PlayerRotation, SetChunkCacheCenter,
# SetHealth, SetHeldSlot, SetTime, TeleportEntity, TickingState,
# TickingStep, PlayerAbilities, MovePlayerPos/PosRot/Rot/Status,
# PlayerAbilitiesRequest, PlayerAction, PlayerCommand, PlayerInput,
# SetCarriedItem.
#
# Остальные payload'ы (PART 3-6) сознательно НЕ портируются. Для каждого
# такого ID создаётся отдельный класс-заглушка: его read/write сразу
# бросают именованный Unsupported("play.rs PART 2+: <packet>"). Это не
# pass и не NotImplementedError — PART 3-6 просто заменят заглушку на
# настоящий @dataclass, не меняя dispatch.
#
# Важные детали Rust, сохранённые дословно:
#   * Disconnect в play.rs — это configuration::Disconnect, то есть
#     причина читается как сетевой NBT (Tag), а не как JSON-строка.
#     JSON-строка есть только у login::Disconnect.
#   * KeepAlive — тоже configuration::KeepAlive { id: i64 }.
#   * BundleDelimiter, ClientTickEnd, PlayerLoaded — разные варианты с
#     пустым payload, поэтому у каждого свой подкласс Empty, иначе
#     encode не смог бы отличить их по типу.
#   * Неизвестный ID (которого нет в ids.play) по-прежнему даёт Unknown
#     с сырым payload, как packet_enum! в Rust.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Type

from quadrix.protocol import ids
from quadrix.protocol.buf import (
    Bool,
    Byte,
    Double,
    Float,
    Int,
    List,
    Long,
    Opt,
    Pos,
    ProtocolError,
    Reader,
    Short,
    UByte,
    VarInt,
    VarLong,
    Vec3d,
    Writer,
)
from quadrix.protocol.ids import Direction, State, id_of
from quadrix.protocol.packets.configuration import Disconnect, KeepAlive
from quadrix.protocol.packets.handshake import (
    Empty,
    Unknown,
    _Packet,
    _PacketSet,
)

__all__ = [
    # исключение для незапортированных payload'ов
    "Unsupported",
    # реализованные clientbound
    "BundleDelimiter",
    "Disconnect",
    "KeepAlive",
    # реализованные serverbound
    "ClientTickEnd",
    "PlayerLoaded",
    # PART 2: движение/позиция/тики — clientbound
    "GameEvent",
    "LookAtEntity",
    "PlayerLookAt",
    "PlayerPosition",
    "PlayerRotation",
    "SetChunkCacheCenter",
    "SetHealth",
    "SetHeldSlot",
    "ClockState",
    "SetTime",
    "TeleportEntity",
    "TickingState",
    "TickingStep",
    "PlayerAbilities",
    # PART 2: движение/позиция/тики — serverbound
    "MovePlayerPos",
    "MovePlayerPosRot",
    "MovePlayerRot",
    "MovePlayerStatus",
    "PlayerAbilitiesRequest",
    "PlayerAction",
    "PlayerCommand",
    "PlayerInput",
    "SetCarriedItem",
    # таблицы
    "ID_TO_CLASS",
    "CLASS_TO_ID",
    "SERVERBOUND_ID_TO_CLASS",
    "SERVERBOUND_CLASS_TO_ID",
    "CLIENTBOUND_ID_TO_CLASS",
    "CLIENTBOUND_CLASS_TO_ID",
    # направления (аналоги enum из packet_enum!)
    "Clientbound",
    "Serverbound",
    "ClientboundPlayPacket",
    "ServerboundPlayPacket",
    # module-level диспетчеры
    "decode_clientbound",
    "decode_serverbound",
    "encode_clientbound",
    "encode_serverbound",
]


class Unsupported(Exception):
    """Payload, который ещё не портирован в PART 1.

    Наследует Exception, а не NotImplementedError: PART 2-6 заменят
    заглушку настоящей реализацией, а до тех пор ошибка должна быть
    явной и именованной.
    """


# ── Пустые варианты play.rs ──────────────────────────────────────────
#
# packet_enum! различает варианты по имени, хотя payload у всех Empty.
# В Python таблица направлений различает пакеты по классу, поэтому
# каждому пустому варианту нужен собственный подкласс Empty.


class BundleDelimiter(Empty):
    """ClientboundBundleDelimiterPacket (пустой payload)."""


class ClientTickEnd(Empty):
    """ServerboundClientTickEndPacket (пустой payload)."""


class PlayerLoaded(Empty):
    """ServerboundPlayerLoadedPacket (пустой payload)."""


# ── Заглушки для будущих PART 2-6 ────────────────────────────────────


def _variant_name(ids_name: str) -> str:
    """``chunk_batch_start`` → ``ChunkBatchStart`` (как вариант в Rust)."""
    parts = ids_name.replace("/", "_").split("_")
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _unsupported_packet(packet_name: str) -> Type[_Packet]:
    """Создать отдельный класс-заглушку для одного ещё не портированного ID.

    Отдельный класс (а не один общий Empty) нужен, чтобы CLASS_TO_ID не
    схлопывал разные варианты в один ID и чтобы encode выбирал ровно тот
    ID, который был у пакета в Rust.
    """
    message = f"play.rs PART 2+: {packet_name}"

    def read(cls, r: Reader):  # noqa: ANN001, ANN202 — сигнатура Codec.read
        raise Unsupported(message)

    def write(self, w: Writer) -> None:  # noqa: ANN001 — сигнатура Codec.write
        raise Unsupported(message)

    return type(
        _variant_name(packet_name),
        (_Packet,),
        {
            "__doc__": (
                f"Заглушка PART 1 для {packet_name}: настоящий payload "
                f"появится в PART 2+."
            ),
            "read": classmethod(read),
            "write": write,
        },
    )


# ── PART 2: движение, позиция и тики (play.rs) ───────────────────────
#
# Источник — play.rs. Имена полей и вариантов сохранены дословно.
# Где задание ожидало «более удобные» имена, победил Rust:
#   * MovePlayerPos / MovePlayerPosRot / MovePlayerRot / MovePlayerStatus
#     несут `flags: u8` (ServerboundMovePlayerPacket: 1 — на земле,
#     2 — горизонтальная коллизия), а не `on_ground: bool`;
#   * PlayerInput несёт `flags: u8` (forward 1, backward 2, left 4,
#     right 8, jump 16, shift 32, sprint 64), а не семь отдельных bool;
#   * у SetTime не world_age/time_of_day, а `game_time` + `clocks`
#     (ClockState по каждому мировому такту);
#   * PlayerPosition — это ClientboundPlayerPositionPacket с
#     `teleport`/`position`/`delta`/`yaw`/`pitch`/`relatives`;
#   * PlayerLookAt.from в Rust — ключевое слово Python, поэтому поле
#     названо `from_` (единственное переименование, поведение то же).
#
# Энтити-синк (PART 3), чат (PART 4), инвентарь (PART 5) и чанки
# (PART 6) не трогаются: их ID по-прежнему остаются заглушками
# Unsupported. Исключение — SetHeldSlot/SetCarriedItem (выбор слота в
# хотбаре), они из списка PART 2.

# ---- clientbound -------------------------------------------------------


@dataclass
class GameEvent(_Packet):
    """ClientboundGameEventPacket: тип события (u8) и его параметр (f32)."""

    event: int
    param: float

    @classmethod
    def read(cls, r: Reader) -> "GameEvent":
        return cls(UByte.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        UByte.write(self.event, w)
        Float.write(self.param, w)


@dataclass
class LookAtEntity(_Packet):
    """Цель PlayerLookAt по сущности: её id и anchor (0 ноги, 1 глаза)."""

    id: int
    anchor: int

    @classmethod
    def read(cls, r: Reader) -> "LookAtEntity":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.anchor, w)


@dataclass
class PlayerLookAt(_Packet):
    """ClientboundPlayerLookAtPacket: повернуть игрока из anchor `from`
    к точке `target` (или, если known, к сущности `entity`)."""

    from_: int
    target: Tuple[float, float, float]
    entity: Optional[LookAtEntity]

    @classmethod
    def read(cls, r: Reader) -> "PlayerLookAt":
        return cls(
            VarInt.read(r),
            Vec3d.read(r),
            Opt(LookAtEntity).read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.from_, w)
        Vec3d.write(self.target, w)
        Opt(LookAtEntity).write(self.entity, w)


@dataclass
class PlayerPosition(_Packet):
    """ClientboundPlayerPositionPacket: абсолютная позиция/углы игрока.

    Упаковка Relative: какие из полей относительные (см. relatives).
    """

    teleport: int
    position: Tuple[float, float, float]
    delta: Tuple[float, float, float]
    yaw: float
    pitch: float
    relatives: int

    @classmethod
    def read(cls, r: Reader) -> "PlayerPosition":
        return cls(
            VarInt.read(r),
            Vec3d.read(r),
            Vec3d.read(r),
            Float.read(r),
            Float.read(r),
            Int.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.teleport, w)
        Vec3d.write(self.position, w)
        Vec3d.write(self.delta, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        Int.write(self.relatives, w)


@dataclass
class PlayerRotation(_Packet):
    """ClientboundPlayerRotationPacket: yaw/pitch и флаги относительности."""

    yaw: float
    relative_yaw: bool
    pitch: float
    relative_pitch: bool

    @classmethod
    def read(cls, r: Reader) -> "PlayerRotation":
        return cls(
            Float.read(r),
            Bool.read(r),
            Float.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        Float.write(self.yaw, w)
        Bool.write(self.relative_yaw, w)
        Float.write(self.pitch, w)
        Bool.write(self.relative_pitch, w)


@dataclass
class SetChunkCacheCenter(_Packet):
    """ClientboundSetChunkCacheCenterPacket: центр кеша чанков (x, z)."""

    x: int
    z: int

    @classmethod
    def read(cls, r: Reader) -> "SetChunkCacheCenter":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.x, w)
        VarInt.write(self.z, w)


@dataclass
class SetHealth(_Packet):
    """ClientboundSetHealthPacket: здоровье, еда и насыщение (синк)."""

    health: float
    food: int
    saturation: float

    @classmethod
    def read(cls, r: Reader) -> "SetHealth":
        return cls(Float.read(r), VarInt.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        Float.write(self.health, w)
        VarInt.write(self.food, w)
        Float.write(self.saturation, w)


@dataclass
class SetHeldSlot(_Packet):
    """ClientboundSetHeldSlotPacket: выбранный слот хотбара (VarInt)."""

    slot: int

    @classmethod
    def read(cls, r: Reader) -> "SetHeldSlot":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)


@dataclass
class ClockState(_Packet):
    """ClockNetworkState одного мирового такта (registry id).

    WorldClock.STREAM_CODEC — plain registry id, без off-by-one.
    """

    clock: int
    total_ticks: int
    partial_tick: float
    rate: float

    @classmethod
    def read(cls, r: Reader) -> "ClockState":
        return cls(
            VarInt.read(r),
            VarLong.read(r),
            Float.read(r),
            Float.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.clock, w)
        VarLong.write(self.total_ticks, w)
        Float.write(self.partial_tick, w)
        Float.write(self.rate, w)


@dataclass
class SetTime(_Packet):
    """ClientboundSetTimePacket: игровое время и состояния мировых часов."""

    game_time: int
    clocks: list[ClockState]

    @classmethod
    def read(cls, r: Reader) -> "SetTime":
        return cls(Long.read(r), List(ClockState).read(r))

    def write(self, w: Writer) -> None:
        Long.write(self.game_time, w)
        List(ClockState).write(self.clocks, w)


@dataclass
class TeleportEntity(_Packet):
    """ClientboundTeleportEntityPacket: позиция/углы сущности.

    `relatives` — упаковка Relative, `on_ground` — признак опоры.
    """

    id: int
    position: Tuple[float, float, float]
    delta: Tuple[float, float, float]
    yaw: float
    pitch: float
    relatives: int
    on_ground: bool

    @classmethod
    def read(cls, r: Reader) -> "TeleportEntity":
        return cls(
            VarInt.read(r),
            Vec3d.read(r),
            Vec3d.read(r),
            Float.read(r),
            Float.read(r),
            Int.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Vec3d.write(self.position, w)
        Vec3d.write(self.delta, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        Int.write(self.relatives, w)
        Bool.write(self.on_ground, w)


@dataclass
class TickingState(_Packet):
    """ClientboundTickingStatePacket: частота тиков и заморозка уровня."""

    rate: float
    frozen: bool

    @classmethod
    def read(cls, r: Reader) -> "TickingState":
        return cls(Float.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Float.write(self.rate, w)
        Bool.write(self.frozen, w)


@dataclass
class TickingStep(_Packet):
    """ClientboundTickingStepPacket: сколько тиков отшагнуть (`/tick step`)."""

    steps: int

    @classmethod
    def read(cls, r: Reader) -> "TickingStep":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.steps, w)


@dataclass
class PlayerAbilities(_Packet):
    """ClientboundPlayerAbilitiesPacket: флаги (i8), скорости полёта/ходьбы."""

    flags: int
    flying_speed: float
    walking_speed: float

    @classmethod
    def read(cls, r: Reader) -> "PlayerAbilities":
        return cls(Byte.read(r), Float.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        Byte.write(self.flags, w)
        Float.write(self.flying_speed, w)
        Float.write(self.walking_speed, w)


# ---- serverbound -------------------------------------------------------


@dataclass
class MovePlayerPos(_Packet):
    """ServerboundMovePlayerPacket.Pos: x/y/z + flags (1 на земле)."""

    x: float
    y: float
    z: float
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "MovePlayerPos":
        return cls(
            Double.read(r),
            Double.read(r),
            Double.read(r),
            UByte.read(r),
        )

    def write(self, w: Writer) -> None:
        Double.write(self.x, w)
        Double.write(self.y, w)
        Double.write(self.z, w)
        UByte.write(self.flags, w)


@dataclass
class MovePlayerPosRot(_Packet):
    """ServerboundMovePlayerPacket.PosRot: x/y/z, yaw/pitch и flags."""

    x: float
    y: float
    z: float
    yaw: float
    pitch: float
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "MovePlayerPosRot":
        return cls(
            Double.read(r),
            Double.read(r),
            Double.read(r),
            Float.read(r),
            Float.read(r),
            UByte.read(r),
        )

    def write(self, w: Writer) -> None:
        Double.write(self.x, w)
        Double.write(self.y, w)
        Double.write(self.z, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        UByte.write(self.flags, w)


@dataclass
class MovePlayerRot(_Packet):
    """ServerboundMovePlayerPacket.Rot: только yaw/pitch и flags."""

    yaw: float
    pitch: float
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "MovePlayerRot":
        return cls(Float.read(r), Float.read(r), UByte.read(r))

    def write(self, w: Writer) -> None:
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        UByte.write(self.flags, w)


@dataclass
class MovePlayerStatus(_Packet):
    """ServerboundMovePlayerPacket.StatusOnly: только flags."""

    flags: int

    @classmethod
    def read(cls, r: Reader) -> "MovePlayerStatus":
        return cls(UByte.read(r))

    def write(self, w: Writer) -> None:
        UByte.write(self.flags, w)


@dataclass
class PlayerAbilitiesRequest(_Packet):
    """ServerboundPlayerAbilitiesPacket: только флаг полёта (2), i8."""

    flags: int

    @classmethod
    def read(cls, r: Reader) -> "PlayerAbilitiesRequest":
        return cls(Byte.read(r))

    def write(self, w: Writer) -> None:
        Byte.write(self.flags, w)


@dataclass
class PlayerAction(_Packet):
    """ServerboundPlayerActionPacket: action, позиция, сторона, sequence.

    `direction` — 3D data value (0..5), `pos` — упакованный BlockPos.
    """

    action: int
    pos: Tuple[int, int, int]
    direction: int
    sequence: int

    @classmethod
    def read(cls, r: Reader) -> "PlayerAction":
        return cls(
            VarInt.read(r),
            Pos.read(r),
            UByte.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.action, w)
        Pos.write(self.pos, w)
        UByte.write(self.direction, w)
        VarInt.write(self.sequence, w)


@dataclass
class PlayerCommand(_Packet):
    """ServerboundPlayerCommandPacket: id, action и data (все VarInt)."""

    id: int
    action: int
    data: int

    @classmethod
    def read(cls, r: Reader) -> "PlayerCommand":
        return cls(VarInt.read(r), VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.action, w)
        VarInt.write(self.data, w)


@dataclass
class PlayerInput(_Packet):
    """ServerboundPlayerInputPacket: flags (forward 1 ... sprint 64)."""

    flags: int

    @classmethod
    def read(cls, r: Reader) -> "PlayerInput":
        return cls(UByte.read(r))

    def write(self, w: Writer) -> None:
        UByte.write(self.flags, w)


@dataclass
class SetCarriedItem(_Packet):
    """ServerboundSetCarriedItemPacket: выбранный слот хотбара (Short)."""

    slot: int

    @classmethod
    def read(cls, r: Reader) -> "SetCarriedItem":
        return cls(Short.read(r))

    def write(self, w: Writer) -> None:
        Short.write(self.slot, w)


# ── Реализованные ID (3 clientbound + 3 serverbound в PART 1) ────────

_CLIENTBOUND_IMPLEMENTED: Dict[str, Type[_Packet]] = {
    "bundle_delimiter": BundleDelimiter,
    "disconnect": Disconnect,
    "keep_alive": KeepAlive,
    # PART 2
    "game_event": GameEvent,
    "player_look_at": PlayerLookAt,
    "player_position": PlayerPosition,
    "player_rotation": PlayerRotation,
    "set_chunk_cache_center": SetChunkCacheCenter,
    "set_health": SetHealth,
    "set_held_slot": SetHeldSlot,
    "set_time": SetTime,
    "teleport_entity": TeleportEntity,
    "ticking_state": TickingState,
    "ticking_step": TickingStep,
    "player_abilities": PlayerAbilities,
}

_SERVERBOUND_IMPLEMENTED: Dict[str, Type[_Packet]] = {
    "keep_alive": KeepAlive,
    "client_tick_end": ClientTickEnd,
    "player_loaded": PlayerLoaded,
    # PART 2
    "move_player_pos": MovePlayerPos,
    "move_player_pos_rot": MovePlayerPosRot,
    "move_player_rot": MovePlayerRot,
    "move_player_status_only": MovePlayerStatus,
    "player_abilities": PlayerAbilitiesRequest,
    "player_action": PlayerAction,
    "player_command": PlayerCommand,
    "player_input": PlayerInput,
    "set_carried_item": SetCarriedItem,
}


def _entries(
    names: Tuple[str, ...],
    implemented: Dict[str, Type[_Packet]],
) -> Tuple[Tuple[str, str, Type[_Packet]], ...]:
    """Построить _ENTRIES ровно по таблице ID из ids.py.

    ID не хардкодятся: _PacketSet.__init_subclass__ возьмёт их через
    id_of(...). Заглушки кешируются по имени внутри одного направления,
    чтобы повторяющиеся имена давали один класс; направления получают
    независимые заглушки, как независимы их таблицы ID.
    """
    cache: Dict[str, Type[_Packet]] = {}
    entries: list[Tuple[str, str, Type[_Packet]]] = []
    for packet_name in names:
        packet_cls = implemented.get(packet_name)
        if packet_cls is None:
            packet_cls = cache.get(packet_name)
            if packet_cls is None:
                packet_cls = _unsupported_packet(packet_name)
                cache[packet_name] = packet_cls
        entries.append((_variant_name(packet_name), packet_name, packet_cls))
    return tuple(entries)


_CLIENTBOUND_ENTRIES = _entries(
    ids.play.clientbound.NAMES, _CLIENTBOUND_IMPLEMENTED
)
_SERVERBOUND_ENTRIES = _entries(
    ids.play.serverbound.NAMES, _SERVERBOUND_IMPLEMENTED
)


# ── Направления (packet_enum! из play.rs) ────────────────────────────


class Clientbound(_PacketSet):
    """play::Clientbound: все ID из ids.play.clientbound."""

    _STATE = State.PLAY
    _DIRECTION = Direction.CLIENTBOUND
    _ENTRIES = _CLIENTBOUND_ENTRIES


class Serverbound(_PacketSet):
    """play::Serverbound: все ID из ids.play.serverbound."""

    _STATE = State.PLAY
    _DIRECTION = Direction.SERVERBOUND
    _ENTRIES = _SERVERBOUND_ENTRIES


#: Имена из задания: в Python enum заменён набором пакетов с decode/encode.
ClientboundPlayPacket = Clientbound
ServerboundPlayPacket = Serverbound


# ── Публичные таблицы dispatch ───────────────────────────────────────
#
# ID_TO_CLASS / CLASS_TO_ID относятся к clientbound (как в задании).
# Для serverbound — отдельные словари, потому что один и тот же класс
# KeepAlive имеет разные ID в разных направлениях.

ID_TO_CLASS: Dict[int, Type[_Packet]] = Clientbound._BY_ID
CLASS_TO_ID: Dict[Type[_Packet], int] = Clientbound._ID_BY_TYPE

SERVERBOUND_ID_TO_CLASS: Dict[int, Type[_Packet]] = Serverbound._BY_ID
SERVERBOUND_CLASS_TO_ID: Dict[Type[_Packet], int] = Serverbound._ID_BY_TYPE

CLIENTBOUND_ID_TO_CLASS = ID_TO_CLASS
CLIENTBOUND_CLASS_TO_ID = CLASS_TO_ID


# ── Module-level диспетчеры (как decode/encode в Rust) ───────────────


def decode_clientbound(packet_id: int, reader: Reader) -> _Packet:
    """Разобрать clientbound-пакет; reader стоит на начале payload.

    Лишние байты после полей — ProtocolError (как в configuration.py).
    Неизвестный ID (нет в ids.play.clientbound) — Unknown с сырым
    оставшимся payload. Известный, но не портированный ID — Unsupported.
    """
    return Clientbound.decode(packet_id, reader.rest())


def decode_serverbound(packet_id: int, reader: Reader) -> _Packet:
    """Разобрать serverbound-пакет; reader стоит на начале payload."""
    return Serverbound.decode(packet_id, reader.rest())


def encode_clientbound(writer: Writer, packet: _Packet) -> int:
    """Записать VarInt-id и payload clientbound-пакета, вернуть ID."""
    packet_id = Clientbound.id(packet)
    writer.varint(packet_id)
    if isinstance(packet, Unknown):
        writer.bytes(packet.payload)
    else:
        packet.write(writer)
    return packet_id


def encode_serverbound(writer: Writer, packet: _Packet) -> int:
    """Записать VarInt-id и payload serverbound-пакета, вернуть ID."""
    packet_id = Serverbound.id(packet)
    writer.varint(packet_id)
    if isinstance(packet, Unknown):
        writer.bytes(packet.payload)
    else:
        packet.write(writer)
    return packet_id
