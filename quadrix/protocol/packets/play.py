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

from dataclasses import dataclass, field
from typing import Dict, List as TypingList, Optional, Tuple, Type

from quadrix.protocol import ids
from quadrix.protocol.buf import (
    BitSet,
    Bool,
    Byte,
    Bytes,
    BytesN,
    ChunkPos,
    Double,
    Float,
    Ident,
    Int,
    List,
    Long,
    Longs,
    LpVec3,
    Nbt,
    Opt,
    OptVarInt,
    Pos,
    ProtocolError,
    Reader,
    SectionPos,
    Short,
    Str,
    StrN,
    UByte,
    Uuid,
    VarInt,
    VarLong,
    Vec3d,
    Writer,
)
from quadrix.protocol.ids import Direction, State, id_of
from quadrix.protocol.packets.configuration import (
    ClearDialog,
    ClientInformation,
    CookieRequest,
    CookieResponse,
    CustomClickAction,
    CustomPayload,
    Disconnect,
    KeepAlive,
    Ping as ConfigurationPing,
    ResourcePackPop,
    ResourcePackPush,
    ResourcePackResponse,
    ServerLinks,
    StoreCookie,
    Transfer,
    UpdateTags,
)
from quadrix.protocol.packets.handshake import (
    Empty,
    Unknown,
    _Packet,
    _PacketSet,
)
from quadrix.protocol.packets.status import Ping as StatusPing
from quadrix.world.nbt import Tag, TagType

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
    # PART 3: сущности и синхронизация игроков — clientbound
    "AddEntity",
    "SpawnPlayer",
    "Animate",
    "DamageEvent",
    "EntityEvent",
    "EntityPositionSync",
    "PositionPath",
    "HurtAnimation",
    "MoveEntityPos",
    "MoveEntityPosRot",
    "MoveEntityRot",
    "VecDelta",
    "PlayerInfoRemove",
    "PlayerInfoUpdate",
    "PlayerInfo",
    "Property",
    "RemoveEntities",
    "RotateHead",
    "SetCamera",
    "SetEntityData",
    "SetEntityLink",
    "SetEntityMotion",
    "SetEquipment",
    "SetPassengers",
    "SwingAnimation",
    "TakeItemEntity",
    "UpdateAttributes",
    "AttributeModifier",
    "AttributeSnapshot",
    "ProjectilePower",
    "MoveVehicle",
    "Particle",
    "Profile",
    "ItemStack",
    # PART 3: сущности и синхронизация игроков — serverbound
    "Interact",
    "PaddleBoat",
    "ClientCommand",
    "PickItemFromEntity",
    "MoveVehicleRequest",
    # PART 4: чат и команды — общие кодеки
    "Signature",
    "PackedSignature",
    "FilterMask",
    "HolderId",
    "ChatTypeBound",
    "Text",
    "TitlesAnimation",
    "LastSeenUpdate",
    "ArgumentSignatures",
    # PART 4: чат и команды — clientbound
    "SystemChat",
    "PlayerChat",
    "DisguisedChat",
    "DeleteChat",
    "CommandSuggestions",
    "Commands",
    "CommandNode",
    "ARGUMENT_TYPES",
    "SetTitleText",
    "SetSubtitleText",
    "SetActionBarText",
    "SetTitlesAnimation",
    "ClearTitles",
    "SetPlayerTeam",
    "TeamParameters",
    "SetScore",
    "ResetScore",
    "NumberFormat",
    "ServerData",
    "CustomChatCompletions",
    "TabList",
    # PART 4: чат и команды — serverbound
    "Chat",
    "ChatCommand",
    "ChatAck",
    "ChatCommandSigned",
    "ChatSessionUpdate",
    "CommandSuggestion",
    # PART 5: инвентарь, слоты и контейнеры — clientbound
    "ContainerClose",
    "ContainerSetContent",
    "ContainerSetData",
    "ContainerSetSlot",
    "MerchantOffers",
    "NetOffer",
    "NetCost",
    "OpenScreen",
    "SetCursorItem",
    "SetPlayerInventory",
    "Cooldown",
    # PART 5: инвентарь, слоты и контейнеры — serverbound
    "ContainerClick",
    "ContainerButtonClick",
    "ContainerSlotStateChanged",
    "RenameItem",
    "EditBook",
    "SetCreativeModeSlot",
    "SelectTrade",
    "Hashed",
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
            "_unsupported": True,
            "read": classmethod(read),
            "write": write,
        },
    )


@dataclass
class _RawPassthrough(_Packet):
    """ID, который Rust не моделирует: payload пишется/читается как есть.

    packet_enum! в play.rs превращает такие id в ``Unknown`` с сырым
    payload. Здесь для каждого имени создаётся отдельный подкласс
    (ID не должны схлопываться), а ``read`` забирает весь остаток.
    """

    payload: bytes

    @classmethod
    def read(cls, r: Reader) -> "_RawPassthrough":
        return cls(bytes(r.rest()))

    def write(self, w: Writer) -> None:
        w.bytes(self.payload)


def _raw_packet(packet_name: str) -> Type[_Packet]:
    """Отдельный raw-passthrough подкласс для одного id (как Unknown)."""
    return type(
        _variant_name(packet_name),
        (_RawPassthrough,),
        {
            "__doc__": (
                f"ID {packet_name}: Rust не моделирует payload, байты "
                f"проходят как есть (аналог Unknown)."
            ),
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


# ── PART 3: сущности и синхронизация игроков (play.rs) ───────────────
#
# Источник — play.rs и entity_data.rs. Портированы только пакеты
# entity/player sync; чат (PART 4), инвентарь (PART 5) и чанки (PART 6)
# остаются заглушками.
#
# Все поля названы дословно как в Rust: AddEntity несёт pitch/yaw/head_yaw
# (i8), а не градусы; MoveEntity* — `VecDelta` (три i16 в 1/4096 блока);
# PlayerInfoUpdate — байтовый bitset действий; SetEquipment — пары
# (slot, Optional<Stack>). ItemStack пока без компонентов: items.rs ещё
# не портирован, поэтому patch с положительными компонентами честно
# отвергается ProtocolError, а пустой patch (обычный стек) кодируется
# ровно как Slot в Rust (count, item, positive, negative, removed).

# ---- общие структуры ---------------------------------------------------

_STR_64 = StrN(64)
_STR_1024 = StrN(1024)
_OPT_STR_1024 = Opt(_STR_1024)


@dataclass(frozen=True)
class Property:
    """com.mojang.authlib.properties.Property (login.rs:11)."""

    name: str
    value: str
    signature: Optional[str] = None

    @classmethod
    def read(cls, r: Reader) -> "Property":
        return cls(
            _STR_64.read(r),
            r.string(32767),
            _OPT_STR_1024.read(r),
        )

    def write(self, w: Writer) -> None:
        _STR_64.write(self.name, w)
        w.string(self.value)
        _OPT_STR_1024.write(self.signature, w)


@dataclass(frozen=True)
class ItemStack:
    """Stack из item.rs. Компоненты (added) пока не портированы.

    Поля совпадают с Rust: item, count, added, removed. Пустой patch
    (added == () и removed == ()) — это обычный стек и кодируется
    дословно как Slot / Template.
    """

    item: int
    count: int
    added: Tuple[Tuple[int, object], ...] = ()
    removed: Tuple[int, ...] = ()


class _Slot:
    """ItemStack.OPTIONAL_STREAM_CODEC: count, item, затем patch."""

    @classmethod
    def read(cls, r: Reader) -> Optional[ItemStack]:
        count = r.varint()
        if count <= 0:
            return None
        item = r.varint()
        positive = r.count(65536)
        negative = r.count(65536)
        if positive:
            # Значения компонентов живут в items.rs; до его портирования
            # нельзя узнать границы каждого компонента на проводе.
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        removed = tuple(r.varint() for _ in range(negative))
        return ItemStack(item=item, count=count, removed=removed)

    @classmethod
    def write(cls, v: Optional[ItemStack], w: Writer) -> None:
        if v is None or v.count <= 0:
            w.varint(0)
            return
        if v.added:
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        w.varint(v.count)
        w.varint(v.item)
        w.varint(len(v.added))
        w.varint(len(v.removed))
        for kind in v.removed:
            w.varint(kind)


class _Template:
    """ItemStackTemplate.STREAM_CODEC: item, count, затем patch."""

    @classmethod
    def read(cls, r: Reader) -> ItemStack:
        item = r.varint()
        count = r.varint()
        positive = r.count(65536)
        negative = r.count(65536)
        if positive:
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        removed = tuple(r.varint() for _ in range(negative))
        return ItemStack(item=item, count=count, removed=removed)

    @classmethod
    def write(cls, v: ItemStack, w: Writer) -> None:
        if v.added:
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        w.varint(v.item)
        w.varint(v.count)
        w.varint(len(v.added))
        w.varint(len(v.removed))
        for kind in v.removed:
            w.varint(kind)


@dataclass(frozen=True)
class Profile:
    """ResolvableProfile (entity_data.rs:46)."""

    name: Optional[str] = None
    uuid: Optional[int] = None
    properties: Tuple[Property, ...] = ()
    body: Optional[str] = None
    cape: Optional[str] = None
    elytra: Optional[str] = None
    slim: Optional[bool] = None

    @classmethod
    def read(cls, r: Reader) -> "Profile":
        name = None
        uuid = None
        if r.bool():
            uuid = r.uuid()
            name = r.string(16)
        else:
            if r.bool():
                name = r.string(16)
            if r.bool():
                uuid = r.uuid()
        count = r.count(16)
        properties = tuple(Property.read(r) for _ in range(count))
        body = r.string(32767) if r.bool() else None
        cape = r.string(32767) if r.bool() else None
        elytra = r.string(32767) if r.bool() else None
        slim = r.bool() if r.bool() else None
        return cls(name, uuid, properties, body, cape, elytra, slim)

    def write(self, w: Writer) -> None:
        full = self.uuid is not None and self.name is not None
        w.bool(full)
        if full:
            w.uuid(self.uuid or 0)
            w.string(self.name or "")
        else:
            w.bool(self.name is not None)
            if self.name is not None:
                w.string(self.name)
            w.bool(self.uuid is not None)
            if self.uuid is not None:
                w.uuid(self.uuid)
        w.varint(len(self.properties))
        for prop in self.properties:
            prop.write(w)
        for texture in (self.body, self.cape, self.elytra):
            w.bool(texture is not None)
            if texture is not None:
                w.string(texture)
        w.bool(self.slim is not None)
        if self.slim is not None:
            w.bool(self.slim)


@dataclass(frozen=True)
class Particle:
    """ParticleTypes.STREAM_CODEC (entity_data.rs:134).

    data — кортеж, первый элемент которого называет вариант:
    ("state", id), ("color", c), ("color_scale", c, f),
    ("color_scale2", a, b, f), ("color_power", c, f), ("scalar", f),
    ("delay", ticks), ("trail", pos, color, duration), ("item", stack),
    ("geyser", id), ("geyser_base", id, f), ("vibration", source, ticks),
    ("mod", name). None — частица без данных.
    """

    id: int
    data: Optional[tuple] = None

    @classmethod
    def read(cls, r: Reader) -> "Particle":
        pid = r.varint()
        if pid == -1:
            return cls(pid, ("mod", r.string(32767)))
        data: Optional[tuple] = None
        if pid in (1, 2, 36, 121, 125):
            data = ("state", r.varint())
        elif pid in (28, 46, 52):
            data = ("color", r.i32())
        elif pid == 21:
            data = ("color_scale", r.i32(), r.f32())
        elif pid == 22:
            data = ("color_scale2", r.i32(), r.i32(), r.f32())
        elif pid in (23, 56):
            data = ("color_power", r.i32(), r.f32())
        elif pid in (15, 48):
            data = ("scalar", r.f32())
        elif pid == 115:
            data = ("delay", r.varint())
        elif pid == 59:
            data = ("trail", Vec3d.read(r), r.i32(), r.varint())
        elif pid == 57:
            data = ("item", _Template.read(r))
        elif pid == 58:
            kind = r.varint()
            if kind == 0:
                source = ("block", Pos.read(r))
            elif kind == 1:
                source = ("entity", r.varint(), r.f32())
            else:
                raise ProtocolError(f"[QuadRix] position source type {kind}")
            data = ("vibration", source, r.varint())
        elif pid in (7, 10):
            data = ("geyser", r.i32())
        elif pid in (8, 9):
            data = ("geyser_base", r.i32(), r.f32())
        return cls(pid, data)

    def write(self, w: Writer) -> None:
        w.varint(self.id)
        if self.data is None:
            return
        kind = self.data[0]
        if kind in ("state", "delay"):
            w.varint(self.data[1])
        elif kind in ("color", "geyser"):
            w.i32(self.data[1])
        elif kind in ("color_scale", "color_power", "geyser_base"):
            w.i32(self.data[1])
            w.f32(self.data[2])
        elif kind == "color_scale2":
            w.i32(self.data[1])
            w.i32(self.data[2])
            w.f32(self.data[3])
        elif kind == "scalar":
            w.f32(self.data[1])
        elif kind == "trail":
            Vec3d.write(self.data[1], w)
            w.i32(self.data[2])
            w.varint(self.data[3])
        elif kind == "item":
            _Template.write(self.data[1], w)
        elif kind == "mod":
            w.string(self.data[1])
        elif kind == "vibration":
            source, ticks = self.data[1], self.data[2]
            if source[0] == "block":
                w.varint(0)
                Pos.write(source[1], w)
            else:
                w.varint(1)
                w.varint(source[1])
                w.f32(source[2])
            w.varint(ticks)
        else:
            raise ProtocolError(f"[QuadRix] unknown particle data {kind}")


# ---- EntityData (entity_data.rs) --------------------------------------

_SER_BYTE = 0
_SER_INT = 1
_SER_LONG = 2
_SER_FLOAT = 3
_SER_STRING = 4
_SER_COMPONENT = 5
_SER_OPTIONAL_COMPONENT = 6
_SER_ITEM_STACK = 7
_SER_BOOLEAN = 8
_SER_ROTATIONS = 9
_SER_BLOCK_POS = 10
_SER_OPTIONAL_BLOCK_POS = 11
_SER_DIRECTION = 12
_SER_OPTIONAL_LIVING_ENTITY_REFERENCE = 13
_SER_BLOCK_STATE = 14
_SER_OPTIONAL_BLOCK_STATE = 15
_SER_PARTICLE = 16
_SER_PARTICLES = 17
_SER_VILLAGER_DATA = 18
_SER_OPTIONAL_UNSIGNED_INT = 19
_SER_POSE = 20
_SER_CAT_VARIANT = 21
_SER_ZOMBIE_NAUTILUS_VARIANT = 32
_SER_OPTIONAL_GLOBAL_POS = 33
_SER_PAINTING_VARIANT = 34
_SER_WEATHERING_COPPER_STATE = 38
_SER_VECTOR3 = 39
_SER_QUATERNION = 40
_SER_RESOLVABLE_PROFILE = 41
_SER_HUMANOID_ARM = 42
_SER_DYE_COLOR = 43

_UNKNOWN_ENTITY_VALUE = object()


def _read_entity_value(kind: int, r: Reader):
    """Прочитать значение EntityData; unknown — маркер остановки списка."""
    if kind == _SER_BYTE:
        return r.i8()
    if kind == _SER_INT:
        return r.varint()
    if kind == _SER_LONG:
        return r.varlong()
    if kind == _SER_FLOAT:
        return r.f32()
    if kind == _SER_STRING:
        return r.string(32767)
    if kind == _SER_COMPONENT:
        return r.nbt()
    if kind == _SER_OPTIONAL_COMPONENT:
        return r.nbt() if r.bool() else None
    if kind == _SER_ITEM_STACK:
        return _Slot.read(r)
    if kind == _SER_BOOLEAN:
        return r.bool()
    if kind in (_SER_ROTATIONS, _SER_VECTOR3):
        return (r.f32(), r.f32(), r.f32())
    if kind == _SER_QUATERNION:
        return (r.f32(), r.f32(), r.f32(), r.f32())
    if kind == _SER_BLOCK_POS:
        return Pos.read(r)
    if kind == _SER_OPTIONAL_BLOCK_POS:
        return Pos.read(r) if r.bool() else None
    if kind == _SER_OPTIONAL_LIVING_ENTITY_REFERENCE:
        return r.uuid() if r.bool() else None
    if kind == _SER_VILLAGER_DATA:
        return (r.varint(), r.varint(), r.varint())
    if kind in (_SER_BLOCK_STATE, _SER_OPTIONAL_BLOCK_STATE):
        return r.varint()
    if (
        kind == _SER_DIRECTION
        or kind == _SER_OPTIONAL_UNSIGNED_INT
        or kind == _SER_POSE
        or _SER_CAT_VARIANT <= kind <= _SER_ZOMBIE_NAUTILUS_VARIANT
        or _SER_PAINTING_VARIANT <= kind <= _SER_WEATHERING_COPPER_STATE
        or kind in (_SER_HUMANOID_ARM, _SER_DYE_COLOR)
    ):
        return r.varint()
    if kind == _SER_PARTICLE:
        return Particle.read(r)
    if kind == _SER_PARTICLES:
        n = r.count(65536)
        return [Particle.read(r) for _ in range(n)]
    if kind == _SER_RESOLVABLE_PROFILE:
        return Profile.read(r)
    return _UNKNOWN_ENTITY_VALUE


def _write_entity_value(kind: int, value, w: Writer) -> None:
    if kind == _SER_BYTE:
        w.i8(value)
    elif kind in (_SER_INT,):
        w.varint(value)
    elif kind == _SER_LONG:
        w.varlong(value)
    elif kind == _SER_FLOAT:
        w.f32(value)
    elif kind == _SER_STRING:
        w.string(value)
    elif kind == _SER_COMPONENT:
        w.nbt(value)
    elif kind == _SER_OPTIONAL_COMPONENT:
        w.bool(value is not None)
        if value is not None:
            w.nbt(value)
    elif kind == _SER_ITEM_STACK:
        _Slot.write(value, w)
    elif kind == _SER_BOOLEAN:
        w.bool(bool(value))
    elif kind in (_SER_ROTATIONS, _SER_VECTOR3, _SER_QUATERNION):
        for component in value:
            w.f32(component)
    elif kind == _SER_BLOCK_POS:
        Pos.write(value, w)
    elif kind == _SER_OPTIONAL_BLOCK_POS:
        w.bool(value is not None)
        if value is not None:
            Pos.write(value, w)
    elif kind == _SER_OPTIONAL_LIVING_ENTITY_REFERENCE:
        w.bool(value is not None)
        if value is not None:
            w.uuid(value)
    elif kind == _SER_VILLAGER_DATA:
        for component in value:
            w.varint(component)
    elif kind in (
        _SER_DIRECTION,
        _SER_BLOCK_STATE,
        _SER_OPTIONAL_BLOCK_STATE,
        _SER_OPTIONAL_UNSIGNED_INT,
        _SER_POSE,
        _SER_HUMANOID_ARM,
        _SER_DYE_COLOR,
    ) or _SER_CAT_VARIANT <= kind <= _SER_ZOMBIE_NAUTILUS_VARIANT or (
        _SER_PAINTING_VARIANT <= kind <= _SER_WEATHERING_COPPER_STATE
    ):
        w.varint(value)
    elif kind == _SER_PARTICLE:
        value.write(w)
    elif kind == _SER_PARTICLES:
        w.varint(len(value))
        for particle in value:
            particle.write(w)
    elif kind == _SER_RESOLVABLE_PROFILE:
        value.write(w)
    else:
        raise ProtocolError(f"[QuadRix] unknown entity data serializer {kind}")


def _read_entity_data(r: Reader) -> list[Tuple[int, int, object]]:
    out: list[Tuple[int, int, object]] = []
    while True:
        index = r.u8()
        if index == 0xFF:
            return out
        kind = r.varint()
        value = _read_entity_value(kind, r)
        if value is _UNKNOWN_ENTITY_VALUE:
            # Как Rust: неизвестный сериализатор останавливает список,
            # ранее прочитанные записи сохраняются, остаток съедается.
            r.rest()
            return out
        out.append((index, kind, value))


def _write_entity_data(values, w: Writer) -> None:
    for index, kind, value in values:
        w.u8(index)
        w.varint(kind)
        _write_entity_value(kind, value, w)
    w.u8(0xFF)


# ---- VecDelta / PositionPath -----------------------------------------


@dataclass(frozen=True)
class VecDelta:
    """Per-axis deltas in 1/4096 blocks: Linear или Stepped."""

    delta: Optional[Tuple[int, int, int]] = None
    steps: Tuple[Tuple[Tuple[int, int, int], int], ...] = ()

    @classmethod
    def linear(cls, x: int, y: int, z: int) -> "VecDelta":
        return cls((x, y, z), ())

    @classmethod
    def stepped(
        cls, steps: TypingList[Tuple[Tuple[int, int, int], int]]
    ) -> "VecDelta":
        return cls(None, tuple(steps))

    def step_count(self) -> int:
        return len(self.steps)


def _read_vec_delta(r: Reader, steps: int) -> VecDelta:
    if steps == 0:
        return VecDelta((r.i16(), r.i16(), r.i16()), ())
    if steps > r.remaining() // 7:
        raise ProtocolError("[QuadRix] VecDelta with too many steps")
    out: list[Tuple[Tuple[int, int, int], int]] = []
    for _ in range(steps):
        ticks = r.varint()
        out.append(((r.i16(), r.i16(), r.i16()), ticks))
    return VecDelta(None, tuple(out))


def _write_vec_delta(delta: Optional[VecDelta], w: Writer) -> None:
    value = delta if delta is not None else VecDelta.linear(0, 0, 0)
    if value.delta is not None:
        w.i16(value.delta[0])
        w.i16(value.delta[1])
        w.i16(value.delta[2])
    else:
        for (dx, dy, dz), ticks in value.steps:
            w.varint(ticks)
            w.i16(dx)
            w.i16(dy)
            w.i16(dz)


@dataclass(frozen=True)
class PositionPath:
    """PositionPath: Linear(end) или Stepped([(pos, ticks), ...])."""

    linear: Optional[Tuple[float, float, float]] = None
    steps: Tuple[Tuple[Tuple[float, float, float], int], ...] = ()

    @classmethod
    def linear_path(cls, x: float, y: float, z: float) -> "PositionPath":
        return cls((x, y, z), ())

    @classmethod
    def stepped(
        cls, steps: TypingList[Tuple[Tuple[float, float, float], int]]
    ) -> "PositionPath":
        return cls(None, tuple(steps))

    @classmethod
    def read(cls, r: Reader) -> "PositionPath":
        if r.varint() == 1:
            n = r.count(r.remaining() // 25)
            return cls(None, tuple((Vec3d.read(r), r.varint()) for _ in range(n)))
        return cls(Vec3d.read(r), ())

    def write(self, w: Writer) -> None:
        if self.linear is not None:
            w.varint(0)
            Vec3d.write(self.linear, w)
        else:
            w.varint(1)
            w.varint(len(self.steps))
            for position, ticks in self.steps:
                Vec3d.write(position, w)
                w.varint(ticks)


# ---- clientbound: сущности -------------------------------------------


@dataclass
class AddEntity(_Packet):
    """ClientboundAddEntityPacket: id, uuid, type, позиция и углы."""

    id: int
    uuid: int
    kind: int
    position: Tuple[float, float, float]
    velocity: Tuple[float, float, float]
    pitch: int
    yaw: int
    head_yaw: int
    data: int

    @classmethod
    def read(cls, r: Reader) -> "AddEntity":
        return cls(
            VarInt.read(r),
            Uuid.read(r),
            VarInt.read(r),
            Vec3d.read(r),
            LpVec3.read(r),
            Byte.read(r),
            Byte.read(r),
            Byte.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Uuid.write(self.uuid, w)
        VarInt.write(self.kind, w)
        Vec3d.write(self.position, w)
        LpVec3.write(self.velocity, w)
        Byte.write(self.pitch, w)
        Byte.write(self.yaw, w)
        Byte.write(self.head_yaw, w)
        VarInt.write(self.data, w)


#: В этой версии Rust отдельного SpawnPlayer/AddPlayer нет — его заменяет
#: AddEntity (игрок тоже сущность). Оставляем имя из задания как псевдоним.
SpawnPlayer = AddEntity


@dataclass
class Animate(_Packet):
    """ClientboundAnimatePacket: id сущности и действие (u8)."""

    id: int
    action: int

    @classmethod
    def read(cls, r: Reader) -> "Animate":
        return cls(VarInt.read(r), UByte.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        UByte.write(self.action, w)


@dataclass
class DamageEvent(_Packet):
    """ClientboundDamageEventPacket: тип урона, причинитель и позиция."""

    id: int
    source_type: int
    cause: Optional[int]
    direct: Optional[int]
    position: Optional[Tuple[float, float, float]]

    @classmethod
    def read(cls, r: Reader) -> "DamageEvent":
        return cls(
            VarInt.read(r),
            VarInt.read(r),
            OptVarInt.read(r),
            OptVarInt.read(r),
            Opt(Vec3d).read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.source_type, w)
        OptVarInt.write(self.cause, w)
        OptVarInt.write(self.direct, w)
        Opt(Vec3d).write(self.position, w)


@dataclass
class EntityEvent(_Packet):
    """ClientboundEntityEventPacket: id сущности (Int) и событие (i8)."""

    id: int
    event: int

    @classmethod
    def read(cls, r: Reader) -> "EntityEvent":
        return cls(Int.read(r), Byte.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.id, w)
        Byte.write(self.event, w)


@dataclass
class EntityPositionSync(_Packet):
    """ClientboundEntityPositionSyncPacket: путь позиции и углы."""

    id: int
    path: PositionPath
    yaw: float
    pitch: float
    on_ground: bool

    @classmethod
    def read(cls, r: Reader) -> "EntityPositionSync":
        return cls(
            VarInt.read(r),
            PositionPath.read(r),
            Float.read(r),
            Float.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        self.path.write(w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        Bool.write(self.on_ground, w)


@dataclass
class HurtAnimation(_Packet):
    """ClientboundHurtAnimationPacket: id сущности и yaw (f32)."""

    id: int
    yaw: float

    @classmethod
    def read(cls, r: Reader) -> "HurtAnimation":
        return cls(VarInt.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Float.write(self.yaw, w)


@dataclass
class MoveEntityPos(_Packet):
    """ClientboundMoveEntityPacket.Pos: delta (VecDelta) и on_ground."""

    id: int
    delta: Optional[VecDelta]
    rotation: Optional[Tuple[int, int]] = None
    on_ground: bool = False

    @classmethod
    def read(cls, r: Reader) -> "MoveEntityPos":
        id_ = VarInt.read(r)
        properties = VarInt.read(r)
        steps = (properties & 0xFFFFFFFF) >> 1
        delta = _read_vec_delta(r, steps)
        return cls(id_, delta, None, properties & 1 != 0)

    def write(self, w: Writer) -> None:
        delta = self.delta if self.delta is not None else VecDelta.linear(0, 0, 0)
        VarInt.write(self.id, w)
        VarInt.write((1 if self.on_ground else 0) | (delta.step_count() << 1), w)
        _write_vec_delta(delta, w)


@dataclass
class MoveEntityPosRot(_Packet):
    """ClientboundMoveEntityPacket.PosRot: delta, yaw/pitch (i8), on_ground."""

    id: int
    delta: Optional[VecDelta]
    rotation: Optional[Tuple[int, int]] = None
    on_ground: bool = False

    @classmethod
    def read(cls, r: Reader) -> "MoveEntityPosRot":
        id_ = VarInt.read(r)
        properties = VarInt.read(r)
        steps = (properties & 0xFFFFFFFF) >> 1
        delta = _read_vec_delta(r, steps)
        rotation = (Byte.read(r), Byte.read(r))
        return cls(id_, delta, rotation, properties & 1 != 0)

    def write(self, w: Writer) -> None:
        delta = self.delta if self.delta is not None else VecDelta.linear(0, 0, 0)
        VarInt.write(self.id, w)
        VarInt.write((1 if self.on_ground else 0) | (delta.step_count() << 1), w)
        _write_vec_delta(delta, w)
        yaw, pitch = self.rotation if self.rotation is not None else (0, 0)
        Byte.write(yaw, w)
        Byte.write(pitch, w)


@dataclass
class MoveEntityRot(_Packet):
    """ClientboundMoveEntityPacket.Rot: on_ground и yaw/pitch (i8)."""

    id: int
    rotation: Optional[Tuple[int, int]] = None
    on_ground: bool = False

    @classmethod
    def read(cls, r: Reader) -> "MoveEntityRot":
        id_ = VarInt.read(r)
        on_ground = Bool.read(r)
        rotation = (Byte.read(r), Byte.read(r))
        return cls(id_, rotation, on_ground)

    def write(self, w: Writer) -> None:
        yaw, pitch = self.rotation if self.rotation is not None else (0, 0)
        VarInt.write(self.id, w)
        Bool.write(self.on_ground, w)
        Byte.write(yaw, w)
        Byte.write(pitch, w)


@dataclass
class MoveVehicle(_Packet):
    """ClientboundMoveVehiclePacket: позиция, yaw и pitch."""

    position: Tuple[float, float, float]
    yaw: float
    pitch: float

    @classmethod
    def read(cls, r: Reader) -> "MoveVehicle":
        return cls(Vec3d.read(r), Float.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        Vec3d.write(self.position, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)


@dataclass
class ProjectilePower(_Packet):
    """ClientboundProjectilePowerPacket: id и ускорение (f64)."""

    id: int
    power: float

    @classmethod
    def read(cls, r: Reader) -> "ProjectilePower":
        return cls(VarInt.read(r), Double.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Double.write(self.power, w)


@dataclass
class RemoveEntities(_Packet):
    """ClientboundRemoveEntitiesPacket: список id сущностей (VarInt)."""

    ids: list[int]

    @classmethod
    def read(cls, r: Reader) -> "RemoveEntities":
        return cls(List(VarInt).read(r))

    def write(self, w: Writer) -> None:
        List(VarInt).write(self.ids, w)


@dataclass
class RotateHead(_Packet):
    """ClientboundRotateHeadPacket: id сущности и head_yaw (i8)."""

    id: int
    head_yaw: int

    @classmethod
    def read(cls, r: Reader) -> "RotateHead":
        return cls(VarInt.read(r), Byte.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Byte.write(self.head_yaw, w)


@dataclass
class SetCamera(_Packet):
    """ClientboundSetCameraPacket: id сущности, к которой привязан вид."""

    camera_id: int

    @classmethod
    def read(cls, r: Reader) -> "SetCamera":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.camera_id, w)


@dataclass
class SetEntityData(_Packet):
    """ClientboundSetEntityDataPacket: id и список (index, type, value)."""

    id: int
    values: list[Tuple[int, int, object]]

    @classmethod
    def read(cls, r: Reader) -> "SetEntityData":
        return cls(VarInt.read(r), _read_entity_data(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        _write_entity_data(self.values, w)


@dataclass
class SetEntityLink(_Packet):
    """ClientboundSetEntityLinkPacket: источник и цель поводка (Int)."""

    source: int
    dest: int

    @classmethod
    def read(cls, r: Reader) -> "SetEntityLink":
        return cls(Int.read(r), Int.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.source, w)
        Int.write(self.dest, w)


@dataclass
class SetEntityMotion(_Packet):
    """ClientboundSetEntityMotionPacket: id и скорость (LpVec3)."""

    id: int
    velocity: Tuple[float, float, float]

    @classmethod
    def read(cls, r: Reader) -> "SetEntityMotion":
        return cls(VarInt.read(r), LpVec3.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        LpVec3.write(self.velocity, w)


@dataclass
class SetEquipment(_Packet):
    """ClientboundSetEquipmentPacket: пары (slot, Optional<Stack>)."""

    id: int
    slots: list[Tuple[int, Optional[ItemStack]]]

    @classmethod
    def read(cls, r: Reader) -> "SetEquipment":
        id_ = VarInt.read(r)
        out: list[Tuple[int, Optional[ItemStack]]] = []
        while True:
            slot = UByte.read(r)
            out.append((slot & 127, _Slot.read(r)))
            if slot & 128 == 0:
                return cls(id_, out)

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        for i, (slot, stack) in enumerate(self.slots):
            UByte.write(slot | 128 if i + 1 < len(self.slots) else slot, w)
            _Slot.write(stack, w)


@dataclass
class SetPassengers(_Packet):
    """ClientboundSetPassengersPacket: транспорт и список пассажиров."""

    vehicle: int
    passengers: list[int]

    @classmethod
    def read(cls, r: Reader) -> "SetPassengers":
        return cls(VarInt.read(r), List(VarInt).read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.vehicle, w)
        List(VarInt).write(self.passengers, w)


@dataclass
class SwingAnimation(_Packet):
    """ClientboundSwingAnimationPacket: рука, тип и длительность."""

    id: int
    hand: int
    kind: int
    duration: int

    @classmethod
    def read(cls, r: Reader) -> "SwingAnimation":
        return cls(VarInt.read(r), VarInt.read(r), VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.hand, w)
        VarInt.write(self.kind, w)
        VarInt.write(self.duration, w)


@dataclass
class TakeItemEntity(_Packet):
    """ClientboundTakeItemEntityPacket: предмет, игрок и количество."""

    item: int
    player: int
    amount: int

    @classmethod
    def read(cls, r: Reader) -> "TakeItemEntity":
        return cls(VarInt.read(r), VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.item, w)
        VarInt.write(self.player, w)
        VarInt.write(self.amount, w)


@dataclass(frozen=True)
class AttributeModifier:
    """AttributeModifier: id (Ident), amount (f64), operation (VarInt)."""

    id: str
    amount: float
    operation: int

    @classmethod
    def read(cls, r: Reader) -> "AttributeModifier":
        return cls(Ident.read(r), Double.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.id, w)
        Double.write(self.amount, w)
        VarInt.write(self.operation, w)


@dataclass(frozen=True)
class AttributeSnapshot:
    """AttributeSnapshot: id атрибута, база и модификаторы."""

    attribute: int
    base: float
    modifiers: Tuple[AttributeModifier, ...] = ()

    @classmethod
    def read(cls, r: Reader) -> "AttributeSnapshot":
        return cls(VarInt.read(r), Double.read(r), tuple(List(AttributeModifier).read(r)))

    def write(self, w: Writer) -> None:
        VarInt.write(self.attribute, w)
        Double.write(self.base, w)
        List(AttributeModifier).write(list(self.modifiers), w)


@dataclass
class UpdateAttributes(_Packet):
    """ClientboundUpdateAttributesPacket: id и снапшоты атрибутов."""

    id: int
    values: list[AttributeSnapshot]

    @classmethod
    def read(cls, r: Reader) -> "UpdateAttributes":
        return cls(VarInt.read(r), List(AttributeSnapshot).read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        List(AttributeSnapshot).write(self.values, w)


# ---- clientbound: синхронизация игроков ------------------------------


@dataclass
class PlayerInfo:
    """Одна запись PlayerInfoUpdate; поля заполнены по actions."""

    uuid: int
    name: Optional[str] = None
    properties: list[Property] = field(default_factory=list)
    chat_session: Optional[Tuple[int, int, bytes, bytes]] = None
    game_mode: Optional[int] = None
    listed: Optional[bool] = None
    latency: Optional[int] = None
    display_name: Optional[object] = None
    list_order: Optional[int] = None
    show_hat: Optional[bool] = None


@dataclass
class PlayerInfoUpdate(_Packet):
    """ClientboundPlayerInfoUpdatePacket: bitset действий и записи."""

    actions: int
    entries: list[PlayerInfo]

    @classmethod
    def read(cls, r: Reader) -> "PlayerInfoUpdate":
        actions = UByte.read(r)
        n = r.count(r.remaining())
        entries: list[PlayerInfo] = []
        for _ in range(n):
            entry = PlayerInfo(Uuid.read(r))
            if actions & 1:
                entry.name = _STR_16.read(r)
                count = r.count(16)
                entry.properties = [Property.read(r) for _ in range(count)]
            if actions & 2 and r.bool():
                entry.chat_session = (
                    r.uuid(),
                    r.i64(),
                    r.byte_array(512),
                    r.byte_array(4096),
                )
            if actions & 4:
                entry.game_mode = r.varint()
            if actions & 8:
                entry.listed = r.bool()
            if actions & 16:
                entry.latency = r.varint()
            if actions & 32:
                entry.display_name = r.nbt() if r.bool() else None
            if actions & 64:
                entry.list_order = r.varint()
            if actions & 128:
                entry.show_hat = r.bool()
            entries.append(entry)
        return cls(actions, entries)

    def write(self, w: Writer) -> None:
        UByte.write(self.actions, w)
        w.varint(len(self.entries))
        for entry in self.entries:
            Uuid.write(entry.uuid, w)
            if self.actions & 1:
                _STR_16.write(entry.name or "", w)
                w.varint(len(entry.properties))
                for prop in entry.properties:
                    prop.write(w)
            if self.actions & 2:
                w.bool(entry.chat_session is not None)
                if entry.chat_session is not None:
                    session_id, expires, key, signature = entry.chat_session
                    w.uuid(session_id)
                    w.i64(expires)
                    w.byte_array(key)
                    w.byte_array(signature)
            if self.actions & 4:
                w.varint(entry.game_mode or 0)
            if self.actions & 8:
                w.bool(bool(entry.listed))
            if self.actions & 16:
                w.varint(entry.latency or 0)
            if self.actions & 32:
                w.bool(entry.display_name is not None)
                if entry.display_name is not None:
                    w.nbt(entry.display_name)
            if self.actions & 64:
                w.varint(entry.list_order or 0)
            if self.actions & 128:
                w.bool(bool(entry.show_hat))


_STR_16 = StrN(16)


@dataclass
class PlayerInfoRemove(_Packet):
    """ClientboundPlayerInfoRemovePacket: список UUID."""

    uuids: list[int]

    @classmethod
    def read(cls, r: Reader) -> "PlayerInfoRemove":
        return cls(List(Uuid).read(r))

    def write(self, w: Writer) -> None:
        List(Uuid).write(self.uuids, w)


# ---- serverbound: взаимодействие с сущностями ------------------------


@dataclass
class Interact(_Packet):
    """ServerboundInteractPacket: id, hand, точка (LpVec3), secondary."""

    id: int
    hand: int
    location: Tuple[float, float, float]
    secondary: bool

    @classmethod
    def read(cls, r: Reader) -> "Interact":
        return cls(
            VarInt.read(r),
            VarInt.read(r),
            LpVec3.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.hand, w)
        LpVec3.write(self.location, w)
        Bool.write(self.secondary, w)


@dataclass
class PaddleBoat(_Packet):
    """ServerboundPaddleBoatPacket: левое и правое весло."""

    left: bool
    right: bool

    @classmethod
    def read(cls, r: Reader) -> "PaddleBoat":
        return cls(Bool.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Bool.write(self.left, w)
        Bool.write(self.right, w)


@dataclass
class ClientCommand(_Packet):
    """ServerboundClientCommandPacket: action (0 respawn, 1 stats, 2 rules)."""

    action: int

    @classmethod
    def read(cls, r: Reader) -> "ClientCommand":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.action, w)


@dataclass
class PickItemFromEntity(_Packet):
    """ServerboundPickItemFromEntityPacket: id сущности и include_data."""

    id: int
    include_data: bool

    @classmethod
    def read(cls, r: Reader) -> "PickItemFromEntity":
        return cls(VarInt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Bool.write(self.include_data, w)


@dataclass
class MoveVehicleRequest(_Packet):
    """ServerboundMoveVehiclePacket: позиция, углы и on_ground."""

    position: Tuple[float, float, float]
    yaw: float
    pitch: float
    on_ground: bool

    @classmethod
    def read(cls, r: Reader) -> "MoveVehicleRequest":
        return cls(Vec3d.read(r), Float.read(r), Float.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Vec3d.write(self.position, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)
        Bool.write(self.on_ground, w)


# ── PART 4: чат и команды (play.rs) ──────────────────────────────────
#
# Источник — play.rs. Портированы пакеты чата, заголовков и команд.
# NBT-компоненты (тело чата, message, tooltip, заголовок) хранятся как
# сырой Tag: разбор в rich-text — это рендер (PART 6+), не протокол.
# Имена полей и вариантов сохранены дословно как в Rust.
#
# CommandSuggestions / CommandSuggestion: их ID есть в ids.rs
# (play::clientbound::COMMAND_SUGGESTIONS = 15,
# play::serverbound::COMMAND_SUGGESTION = 15), но в packet_enum! Rust они
# не перечислены. Wire-формат взят из vanilla 26.3:
#   clientbound — id VarInt, start VarInt, length VarInt,
#                 list of (String, Optional<Component NBT>);
#   serverbound — id VarInt, text String.
#
# Безопасный чат (secure_chat.rs) как логика НЕ портируется: подписи
# (Signature, PackedSignature) и сессия (ChatSessionUpdate) хранятся как
# байты, криптография не проверяется.

# ---- общие кодеки чата ------------------------------------------------

_SIGNATURE_SIZE = 256

#: Tag::End — заглушка отсутствующего NBT-компонента (play.rs `Tag::End`).
_EMPTY_TAG = Tag(TagType.End, is_end=True)


class Signature:
    """MessageSignature: ровно 256 необработанных байт (play.rs)."""

    @classmethod
    def read(cls, r: Reader) -> bytes:
        return bytes(r.bytes(_SIGNATURE_SIZE))

    @classmethod
    def write(cls, v: bytes, w: Writer) -> None:
        w.bytes(v)


class PackedSignature:
    """MessageSignature.Packed: индекс в кэше или полная подпись.

    Форма на проводе — (i32, Optional[bytes]): varint(index + 1), а
    когда индекс равен -1, следом идут 256 байт подписи.
    """

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, Optional[bytes]]:
        index = r.varint() - 1
        if index == -1:
            return (-1, bytes(r.bytes(_SIGNATURE_SIZE)))
        return (index, None)

    @classmethod
    def write(cls, v: Tuple[int, Optional[bytes]], w: Writer) -> None:
        index, signature = v
        w.varint(index + 1)
        if signature is not None:
            w.bytes(signature)


class FilterMask:
    """FilterMask: 0 pass-through, 1 fully filtered, 2 partially (BitSet)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, list[int]]:
        kind = r.varint()
        return (kind, r.long_array() if kind == 2 else [])

    @classmethod
    def write(cls, v: Tuple[int, list[int]], w: Writer) -> None:
        kind, bits = v
        w.varint(kind)
        if kind == 2:
            w.long_array(bits)


class HolderId:
    """Holder reference: registry id + 1; 0 — inline (не поддержано)."""

    @classmethod
    def read(cls, r: Reader) -> int:
        ident = r.varint()
        if ident == 0:
            raise ProtocolError(
                "[QuadRix] inline registry values are not supported"
            )
        return ident - 1

    @classmethod
    def write(cls, v: int, w: Writer) -> None:
        w.varint(v + 1)


@dataclass(frozen=True)
class ChatTypeBound:
    """ChatType.Bound: holder чата, имя и опциональная цель (NBT)."""

    chat_type: int
    name: object
    target: Optional[object]

    @classmethod
    def read(cls, r: Reader) -> "ChatTypeBound":
        return cls(HolderId.read(r), Nbt.read(r), Opt(Nbt).read(r))

    def write(self, w: Writer) -> None:
        HolderId.write(self.chat_type, w)
        Nbt.write(self.name, w)
        Opt(Nbt).write(self.target, w)


@dataclass(frozen=True)
class Text:
    """play.rs Text: NBT-компонент заголовка/подзаголовка/action bar."""

    text: object

    @classmethod
    def read(cls, r: Reader) -> "Text":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.text, w)


@dataclass(frozen=True)
class TitlesAnimation:
    """ClientboundSetTitlesAnimationPacket: fade_in, stay, fade_out."""

    fade_in: int
    stay: int
    fade_out: int

    @classmethod
    def read(cls, r: Reader) -> "TitlesAnimation":
        return cls(Int.read(r), Int.read(r), Int.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.fade_in, w)
        Int.write(self.stay, w)
        Int.write(self.fade_out, w)


@dataclass(frozen=True)
class LastSeenUpdate:
    """LastSeenMessages.Update: offset, 20-битный BitSet (3 байта), checksum."""

    offset: int
    acknowledged: bytes
    checksum: int

    @classmethod
    def read(cls, r: Reader) -> "LastSeenUpdate":
        return cls(VarInt.read(r), bytes(r.bytes(3)), Byte.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.offset, w)
        w.bytes(self.acknowledged)
        Byte.write(self.checksum, w)


class ArgumentSignatures:
    """ArgumentSignatures: до 8 пар (имя ≤ 16 символов, подпись 256 байт)."""

    @classmethod
    def read(cls, r: Reader) -> list[Tuple[str, bytes]]:
        n = r.count(8)
        return [
            (r.string(16), bytes(r.bytes(_SIGNATURE_SIZE))) for _ in range(n)
        ]

    @classmethod
    def write(cls, v: list[Tuple[str, bytes]], w: Writer) -> None:
        w.varint(len(v))
        for name, signature in v:
            w.string(name)
            w.bytes(signature)


# ---- clientbound: чат -------------------------------------------------

@dataclass
class SystemChat(_Packet):
    """ClientboundSystemChatPacket: NBT-компонент и признак overlay."""

    content: object
    overlay: bool

    @classmethod
    def read(cls, r: Reader) -> "SystemChat":
        return cls(Nbt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.content, w)
        Bool.write(self.overlay, w)


@dataclass
class DisguisedChat(_Packet):
    """ClientboundDisguisedChatPacket: message (NBT) и ChatType.Bound."""

    message: object
    chat_type: ChatTypeBound

    @classmethod
    def read(cls, r: Reader) -> "DisguisedChat":
        return cls(Nbt.read(r), ChatTypeBound.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.message, w)
        self.chat_type.write(w)


@dataclass
class DeleteChat(_Packet):
    """ClientboundDeleteChatPacket: удалённое сообщение по packed signature."""

    signature: Tuple[int, Optional[bytes]]

    @classmethod
    def read(cls, r: Reader) -> "DeleteChat":
        return cls(PackedSignature.read(r))

    def write(self, w: Writer) -> None:
        PackedSignature.write(self.signature, w)


@dataclass
class PlayerChat(_Packet):
    """ClientboundPlayerChatPacket: подписанное сообщение игрока.

    Поля — дословно из play.rs: global_index, sender (UUID),
    index, signature (Optional<256 байт>), content (StrN<256>),
    timestamp, salt, last_seen (индексы/packed), unsigned_content (NBT),
    filter (FilterMask) и chat_type.
    """

    global_index: int
    sender: int
    index: int
    signature: Optional[bytes]
    content: str
    timestamp: int
    salt: int
    last_seen: list[Tuple[int, Optional[bytes]]]
    unsigned_content: Optional[object]
    filter: Tuple[int, list[int]]
    chat_type: ChatTypeBound

    @classmethod
    def read(cls, r: Reader) -> "PlayerChat":
        return cls(
            VarInt.read(r),
            Uuid.read(r),
            VarInt.read(r),
            Opt(Signature).read(r),
            StrN(256).read(r),
            Long.read(r),
            Long.read(r),
            List(PackedSignature).read(r),
            Opt(Nbt).read(r),
            FilterMask.read(r),
            ChatTypeBound.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.global_index, w)
        Uuid.write(self.sender, w)
        VarInt.write(self.index, w)
        Opt(Signature).write(self.signature, w)
        StrN(256).write(self.content, w)
        Long.write(self.timestamp, w)
        Long.write(self.salt, w)
        List(PackedSignature).write(self.last_seen, w)
        Opt(Nbt).write(self.unsigned_content, w)
        FilterMask.write(self.filter, w)
        self.chat_type.write(w)


# ---- clientbound: команды ---------------------------------------------

#: Реестр minecraft:command_argument_type 26.3 в порядке id
#: (play.rs ARGUMENT_TYPES, ArgumentTypeInfos.bootstrap).
ARGUMENT_TYPES: Tuple[str, ...] = (
    "brigadier:bool",
    "brigadier:float",
    "brigadier:double",
    "brigadier:integer",
    "brigadier:long",
    "brigadier:string",
    "minecraft:entity",
    "minecraft:game_profile",
    "minecraft:block_pos",
    "minecraft:column_pos",
    "minecraft:vec3",
    "minecraft:vec2",
    "minecraft:block_state",
    "minecraft:block_predicate",
    "minecraft:item_stack",
    "minecraft:item_predicate",
    "minecraft:team_color",
    "minecraft:hex_color",
    "minecraft:component",
    "minecraft:style",
    "minecraft:message",
    "minecraft:nbt_compound_tag",
    "minecraft:nbt_tag",
    "minecraft:nbt_path",
    "minecraft:objective",
    "minecraft:objective_criteria",
    "minecraft:operation",
    "minecraft:particle",
    "minecraft:angle",
    "minecraft:rotation",
    "minecraft:scoreboard_slot",
    "minecraft:score_holder",
    "minecraft:swizzle",
    "minecraft:team",
    "minecraft:item_slot",
    "minecraft:item_slots",
    "minecraft:resource_location",
    "minecraft:function",
    "minecraft:entity_anchor",
    "minecraft:int_range",
    "minecraft:float_range",
    "minecraft:dimension",
    "minecraft:gamemode",
    "minecraft:time",
    "minecraft:resource_or_tag",
    "minecraft:resource_or_tag_key",
    "minecraft:resource",
    "minecraft:resource_key",
    "minecraft:resource_selector",
    "minecraft:template_mirror",
    "minecraft:template_rotation",
    "minecraft:heightmap",
    "minecraft:loot_table",
    "minecraft:loot_predicate",
    "minecraft:loot_modifier",
    "minecraft:context_float_provider",
    "minecraft:context_int_provider",
    "minecraft:slot_source",
    "minecraft:dialog",
    "minecraft:feature",
    "minecraft:swing_animation",
    "minecraft:uuid",
)


def _read_argument_properties(r: Reader, argument_id: int) -> None:
    """Пропустить свойства парсера аргумента (`ArgumentTypeInfo`).

    Порт ArgumentTypeInfo.deserializeFromNetwork: только те парсеры,
    что несут байты в 26.3. Имена берутся из ARGUMENT_TYPES по id
    (Registry опережает остальные и сдвигает их по кодировке).
    """
    if not 0 <= argument_id < len(ARGUMENT_TYPES):
        raise ProtocolError(
            f"[QuadRix] unknown argument type {argument_id}"
        )
    name = ARGUMENT_TYPES[argument_id]
    if name in ("brigadier:integer", "brigadier:long", "brigadier:float",
                "brigadier:double"):
        flags = r.u8()
        if name == "brigadier:integer":
            if flags & 1:
                r.i32()
            if flags & 2:
                r.i32()
        elif name == "brigadier:long":
            if flags & 1:
                r.i64()
            if flags & 2:
                r.i64()
        elif name == "brigadier:float":
            if flags & 1:
                r.f32()
            if flags & 2:
                r.f32()
        else:
            if flags & 1:
                r.f64()
            if flags & 2:
                r.f64()
    elif name == "brigadier:string":
        r.varint()
    elif name == "minecraft:entity":
        r.u8()
    elif name == "minecraft:score_holder":
        r.u8()
    elif name == "minecraft:time":
        r.i32()
    elif name in (
        "minecraft:resource",
        "minecraft:resource_key",
        "minecraft:resource_or_tag",
        "minecraft:resource_or_tag_key",
        "minecraft:resource_selector",
    ):
        r.string(32767)
    # Остальные парсеры не несут свойств на проводе.


@dataclass(frozen=True)
class CommandNode:
    """Один узел ClientboundCommandsPacket: литерал или аргумент.

    kind: 0 root, 1 literal, 2 argument. parser хранит (id, сырые байты)
    свойств, suggestions — провайдер подсказок (minecraft:ask_server).
    """

    kind: int
    executable: bool
    restricted: bool
    children: list[int]
    redirect: Optional[int]
    name: str
    parser: Optional[Tuple[int, bytes]]
    suggestions: Optional[str]


def _acyclic(nodes: list[CommandNode], edges) -> bool:
    """Порт play.rs `acyclic`: обход без рекурсии, цикл — False."""
    new, on_path, done = 0, 1, 2
    state = [new] * len(nodes)
    for start in range(len(nodes)):
        if state[start] != new:
            continue
        state[start] = on_path
        path: list[list[int]] = [[start, 0]]
        while path:
            node, followed = path[-1]
            edge_list = edges(nodes[node])
            if followed >= len(edge_list):
                state[node] = done
                path.pop()
                continue
            path[-1][1] += 1
            edge = edge_list[followed]
            if edge < 0 or edge >= len(nodes):
                continue
            if state[edge] == on_path:
                return False
            if state[edge] == new:
                state[edge] = on_path
                path.append([edge, 0])
    return True


@dataclass
class Commands(_Packet):
    """ClientboundCommandsPacket: узлы дерева и индекс корня."""

    nodes: list[CommandNode]
    root: int

    @classmethod
    def read(cls, r: Reader) -> "Commands":
        n = r.count(r.remaining())
        nodes: list[CommandNode] = []
        for _ in range(n):
            flags = r.u8()
            count = r.count(r.remaining())
            children = [r.varint() for _ in range(count)]
            redirect = r.varint() if flags & 8 else None
            kind = flags & 3
            name = ""
            parser: Optional[Tuple[int, bytes]] = None
            suggestions: Optional[str] = None
            if kind >= 1:
                name = r.string(32767)
            if kind == 2:
                arg_id = r.varint()
                start = r.position()
                _read_argument_properties(r, arg_id)
                parser = (arg_id, bytes(r.since(start)))
                if flags & 16:
                    suggestions = r.string(32767)
            nodes.append(
                CommandNode(
                    kind=kind,
                    executable=bool(flags & 4),
                    restricted=bool(flags & 32),
                    children=children,
                    redirect=redirect,
                    name=name,
                    parser=parser,
                    suggestions=suggestions,
                )
            )
        # ClientboundCommandsPacket.validateEntries: сначала redirect
        # (canBuild), потом children (canResolve).
        if not _acyclic(nodes, lambda node: [node.redirect] if node.redirect is not None else []):
            raise ProtocolError("[QuadRix] Server sent an impossible command tree")
        if not _acyclic(nodes, lambda node: node.children):
            raise ProtocolError("[QuadRix] Server sent an impossible command tree")
        return cls(nodes, r.varint())

    def write(self, w: Writer) -> None:
        w.varint(len(self.nodes))
        for node in self.nodes:
            flags = node.kind & 3
            if node.executable:
                flags |= 4
            if node.redirect is not None:
                flags |= 8
            if node.suggestions is not None:
                flags |= 16
            if node.restricted:
                flags |= 32
            w.u8(flags)
            w.varint(len(node.children))
            for child in node.children:
                w.varint(child)
            if node.redirect is not None:
                w.varint(node.redirect)
            if node.kind >= 1:
                w.string(node.name)
            if node.kind == 2:
                arg_id, props = node.parser if node.parser is not None else (5, b"")
                w.varint(arg_id)
                w.bytes(props)
                if node.suggestions is not None:
                    w.string(node.suggestions)
        w.varint(self.root)


@dataclass
class CommandSuggestions(_Packet):
    """ClientboundCommandSuggestionsPacket: id, start, length, matches."""

    id: int
    start: int
    length: int
    matches: list[Tuple[str, Optional[object]]]

    @classmethod
    def read(cls, r: Reader) -> "CommandSuggestions":
        ident = VarInt.read(r)
        start = VarInt.read(r)
        length = VarInt.read(r)
        count = r.count(r.remaining())
        matches: list[Tuple[str, Optional[object]]] = []
        for _ in range(count):
            text = r.string(32767)
            tooltip = Opt(Nbt).read(r)
            matches.append((text, tooltip))
        return cls(ident, start, length, matches)

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.start, w)
        VarInt.write(self.length, w)
        w.varint(len(self.matches))
        for text, tooltip in self.matches:
            w.string(text)
            Opt(Nbt).write(tooltip, w)


# ---- clientbound: заголовки -------------------------------------------

@dataclass
class SetTitleText(_Packet):
    """ClientboundSetTitleTextPacket: NBT-компонент заголовка."""

    text: object

    @classmethod
    def read(cls, r: Reader) -> "SetTitleText":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.text, w)


@dataclass
class SetSubtitleText(_Packet):
    """ClientboundSetSubtitleTextPacket: NBT-компонент подзаголовка."""

    text: object

    @classmethod
    def read(cls, r: Reader) -> "SetSubtitleText":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.text, w)


@dataclass
class SetActionBarText(_Packet):
    """ClientboundSetActionBarTextPacket: NBT-компонент action bar."""

    text: object

    @classmethod
    def read(cls, r: Reader) -> "SetActionBarText":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.text, w)


@dataclass
class SetTitlesAnimation(_Packet):
    """ClientboundSetTitlesAnimationPacket (Bool1-независимый)."""

    fade_in: int
    stay: int
    fade_out: int

    @classmethod
    def read(cls, r: Reader) -> "SetTitlesAnimation":
        return cls(Int.read(r), Int.read(r), Int.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.fade_in, w)
        Int.write(self.stay, w)
        Int.write(self.fade_out, w)


@dataclass
class ClearTitles(_Packet):
    """ClientboundClearTitlesPacket: сбрасывать ли и тайминги."""

    value: bool

    @classmethod
    def read(cls, r: Reader) -> "ClearTitles":
        return cls(Bool.read(r))

    def write(self, w: Writer) -> None:
        Bool.write(self.value, w)


# ---- clientbound: команды и очки --------------------------------------

@dataclass(frozen=True)
class TeamParameters:
    """ClientboundSetPlayerTeamPacket.Parameters."""

    display_name: object
    prefix: object
    suffix: object
    name_tag_visibility: int
    collision_rule: int
    color: Optional[int]
    options: int


@dataclass
class SetPlayerTeam(_Packet):
    """ClientboundSetPlayerTeamPacket: method 0 добавляет (параметры и
    игроки), 1 удаляет, 2 меняет (параметры), 3 входит и 4 покидает
    (игроки)."""

    name: str
    method: int
    parameters: Optional[TeamParameters]
    players: list[str]

    @classmethod
    def read(cls, r: Reader) -> "SetPlayerTeam":
        name = Str.read(r)
        method = Byte.read(r)
        parameters = None
        if method in (0, 2):
            parameters = TeamParameters(
                Nbt.read(r),
                Nbt.read(r),
                Nbt.read(r),
                VarInt.read(r),
                VarInt.read(r),
                OptVarInt.read(r),
                Byte.read(r),
            )
        players = List(Str).read(r) if method in (0, 3, 4) else []
        return cls(name, method, parameters, players)

    def write(self, w: Writer) -> None:
        Str.write(self.name, w)
        Byte.write(self.method, w)
        if self.method in (0, 2):
            params = self.parameters or TeamParameters(
                _EMPTY_TAG,
                _EMPTY_TAG,
                _EMPTY_TAG,
                0,
                0,
                None,
                0,
            )
            Nbt.write(params.display_name, w)
            Nbt.write(params.prefix, w)
            Nbt.write(params.suffix, w)
            VarInt.write(params.name_tag_visibility, w)
            VarInt.write(params.collision_rule, w)
            OptVarInt.write(params.color, w)
            Byte.write(params.options, w)
        if self.method in (0, 3, 4):
            List(Str).write(self.players, w)


@dataclass(frozen=True)
class NumberFormat:
    """NumberFormatTypes: 0 blank, 1 styled (стиль), 2 fixed (компонент)."""

    kind: int
    tag: Optional[object] = None

    @classmethod
    def blank(cls) -> "NumberFormat":
        return cls(0)

    @classmethod
    def styled(cls, tag: object) -> "NumberFormat":
        return cls(1, tag)

    @classmethod
    def fixed(cls, tag: object) -> "NumberFormat":
        return cls(2, tag)

    @classmethod
    def read(cls, r: Reader) -> "NumberFormat":
        kind = r.varint()
        if kind == 0:
            return cls(0)
        if kind in (1, 2):
            return cls(kind, Nbt.read(r))
        raise ProtocolError(f"[QuadRix] unknown number format {kind}")

    def write(self, w: Writer) -> None:
        w.varint(self.kind)
        if self.kind in (1, 2):
            Nbt.write(self.tag, w)


@dataclass
class SetScore(_Packet):
    """ClientboundSetScorePacket."""

    owner: str
    objective: str
    score: int
    display: Optional[object]
    number_format: Optional[NumberFormat]

    @classmethod
    def read(cls, r: Reader) -> "SetScore":
        return cls(
            Str.read(r),
            Str.read(r),
            VarInt.read(r),
            Opt(Nbt).read(r),
            Opt(NumberFormat).read(r),
        )

    def write(self, w: Writer) -> None:
        Str.write(self.owner, w)
        Str.write(self.objective, w)
        VarInt.write(self.score, w)
        Opt(Nbt).write(self.display, w)
        Opt(NumberFormat).write(self.number_format, w)


@dataclass
class ResetScore(_Packet):
    """ClientboundResetScorePacket: одна цель или все, если objective None."""

    owner: str
    objective: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "ResetScore":
        return cls(Str.read(r), Opt(Str).read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.owner, w)
        Opt(Str).write(self.objective, w)


# ---- clientbound: прочее (tab list, server data, completions) ---------

@dataclass
class TabList(_Packet):
    """ClientboundTabListPacket: header и footer (NBT)."""

    header: object
    footer: object

    @classmethod
    def read(cls, r: Reader) -> "TabList":
        return cls(Nbt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.header, w)
        Nbt.write(self.footer, w)


@dataclass
class ServerData(_Packet):
    """ClientboundServerDataPacket: motd (NBT) и опциональная иконка."""

    motd: object
    icon: Optional[bytes]

    @classmethod
    def read(cls, r: Reader) -> "ServerData":
        return cls(Nbt.read(r), Opt(Bytes).read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.motd, w)
        Opt(Bytes).write(self.icon, w)


@dataclass
class CustomChatCompletions(_Packet):
    """ClientboundCustomChatCompletionsPacket: действие и строки."""

    action: int
    entries: list[str]

    @classmethod
    def read(cls, r: Reader) -> "CustomChatCompletions":
        return cls(VarInt.read(r), List(Str).read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.action, w)
        List(Str).write(self.entries, w)


# ---- serverbound: чат и команды ---------------------------------------

@dataclass
class Chat(_Packet):
    """ServerboundChatPacket: сообщение, подпись и LastSeenUpdate."""

    message: str
    timestamp: int
    salt: int
    signature: Optional[bytes]
    last_seen: LastSeenUpdate

    @classmethod
    def read(cls, r: Reader) -> "Chat":
        return cls(
            StrN(256).read(r),
            Long.read(r),
            Long.read(r),
            Opt(Signature).read(r),
            LastSeenUpdate.read(r),
        )

    def write(self, w: Writer) -> None:
        StrN(256).write(self.message, w)
        Long.write(self.timestamp, w)
        Long.write(self.salt, w)
        Opt(Signature).write(self.signature, w)
        self.last_seen.write(w)


@dataclass
class ChatCommand(_Packet):
    """ServerboundChatCommandPacket: только строка команды."""

    command: str

    @classmethod
    def read(cls, r: Reader) -> "ChatCommand":
        return cls(Str.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.command, w)


@dataclass
class ChatAck(_Packet):
    """ServerboundChatAckPacket: сколько сообщений подтверждено."""

    offset: int

    @classmethod
    def read(cls, r: Reader) -> "ChatAck":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.offset, w)


@dataclass
class ChatCommandSigned(_Packet):
    """ServerboundChatCommandSignedPacket: команда, подписи аргументов,
    timestamp, salt и LastSeenUpdate."""

    command: str
    timestamp: int
    salt: int
    arguments: list[Tuple[str, bytes]]
    last_seen: LastSeenUpdate

    @classmethod
    def read(cls, r: Reader) -> "ChatCommandSigned":
        return cls(
            Str.read(r),
            Long.read(r),
            Long.read(r),
            ArgumentSignatures.read(r),
            LastSeenUpdate.read(r),
        )

    def write(self, w: Writer) -> None:
        Str.write(self.command, w)
        Long.write(self.timestamp, w)
        Long.write(self.salt, w)
        ArgumentSignatures.write(self.arguments, w)
        self.last_seen.write(w)


@dataclass
class ChatSessionUpdate(_Packet):
    """ServerboundChatSessionUpdatePacket: RemoteChatSession.Data."""

    session: int
    expires_at: int
    key: bytes
    key_signature: bytes

    @classmethod
    def read(cls, r: Reader) -> "ChatSessionUpdate":
        return cls(
            Uuid.read(r),
            Long.read(r),
            BytesN(512).read(r),
            BytesN(4096).read(r),
        )

    def write(self, w: Writer) -> None:
        Uuid.write(self.session, w)
        Long.write(self.expires_at, w)
        BytesN(512).write(self.key, w)
        BytesN(4096).write(self.key_signature, w)


@dataclass
class CommandSuggestion(_Packet):
    """ServerboundCommandSuggestionPacket: id и текст запроса."""

    id: int
    text: str

    @classmethod
    def read(cls, r: Reader) -> "CommandSuggestion":
        return cls(VarInt.read(r), Str.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Str.write(self.text, w)


# ── PART 5: инвентарь, слоты и контейнеры (play.rs) ──────────────────
#
# Источник — play.rs (и item.rs для формы Slot / Hashed). Имена полей и
# вариантов сохранены дословно как в Rust: у ContainerSet* это `container`
# (не window_id), `state` (не state_id); у ContainerClick — `input` (не
# mode) и `changed` пар «(slot, Option<Hashed>)».
#
# Слоты (Slot) кодируются тем же `_Slot` из PART 3: count, item, затем
# patch. Непустые патчи компонентов по-прежнему дают ProtocolError —
# items.rs ещё не портирован, поэтому значения компонентов на проводе
# прочитать нельзя. SetCreativeModeSlot использует DelimitedSlot, но при
# пустом патче он побайтово совпадает со Slot, так что снова `_Slot`.
#
# HashedStack (item.rs:1135) — самодостаточная wire-форма (item, count,
# пары (kind, hash), removed-виды), items.rs для неё НЕ нужен. Ею несут
# ContainerClick (changed и carried).
#
# RecipeBook* / PlaceGhostRecipe / PlaceRecipe живут в recipes.rs —
# отдельном файле, не в этом блоке. update_recipes в packet_enum! play.rs
# отсутствует, поэтому здесь тоже нет.

# ---- общие структуры инвентаря ----------------------------------------


@dataclass(frozen=True)
class Hashed:
    """HashedStack (item.rs:1135): что клиент считает лежащим в слоте.

    Значения компонентов заменены хешами, поэтому items.rs не нужен.
    `added` — пары (id компонента, хеш), `removed` — id компонентов.
    """

    item: int
    count: int
    added: Tuple[Tuple[int, int], ...] = ()
    removed: Tuple[int, ...] = ()

    @classmethod
    def read(cls, r: Reader) -> "Hashed":
        item = r.varint()
        count = r.varint()
        n = r.count(256)
        added = tuple((r.varint(), r.i32()) for _ in range(n))
        n = r.count(256)
        removed = tuple(r.varint() for _ in range(n))
        return cls(item, count, added, removed)

    def write(self, w: Writer) -> None:
        w.varint(self.item)
        w.varint(self.count)
        w.varint(len(self.added))
        for kind, digest in self.added:
            w.varint(kind)
            w.i32(digest)
        w.varint(len(self.removed))
        for kind in self.removed:
            w.varint(kind)


class _HashedSlot:
    """HashedSlot (item.rs:1148): bool-флаг присутствия, затем HashedStack."""

    @classmethod
    def read(cls, r: Reader) -> Optional[Hashed]:
        if not r.bool():
            return None
        return Hashed.read(r)

    @classmethod
    def write(cls, v: Optional[Hashed], w: Writer) -> None:
        w.bool(v is not None)
        if v is not None:
            v.write(w)


class _ChangedSlots:
    """ChangedSlots (play.rs:2300): список пар (slot i16, Option<Hashed>)."""

    @classmethod
    def read(cls, r: Reader) -> list[Tuple[int, Optional[Hashed]]]:
        n = r.count(128)
        return [(r.i16(), _HashedSlot.read(r)) for _ in range(n)]

    @classmethod
    def write(
        cls, v: list[Tuple[int, Optional[Hashed]]], w: Writer
    ) -> None:
        w.varint(len(v))
        for slot, hashed in v:
            w.i16(slot)
            _HashedSlot.write(hashed, w)


class _BookPages:
    """BookPages (play.rs:2551): до 100 страниц по 1024 символа."""

    @classmethod
    def read(cls, r: Reader) -> list[str]:
        n = r.varint()
        if not 0 <= n <= 100:
            raise ProtocolError(f"[QuadRix] {n} book pages, at most 100")
        return [r.string(1024) for _ in range(n)]

    @classmethod
    def write(cls, v: list[str], w: Writer) -> None:
        w.varint(len(v))
        for page in v:
            w.string(page)


@dataclass(frozen=True)
class NetCost:
    """ItemCost.STREAM_CODEC (play.rs:99): item, count и компоненты.

    Форма на проводе не несёт patch-removal count: список идёт сразу.
    Компоненты непустые не читаются (items.rs pending) → ProtocolError.
    """

    item: int
    count: int
    components: Tuple[Tuple[int, object], ...] = ()

    @classmethod
    def read(cls, r: Reader) -> "NetCost":
        item = r.varint()
        count = r.varint()
        n = r.count(r.remaining())
        if n:
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        return cls(item, count)

    def write(self, w: Writer) -> None:
        if self.components:
            raise ProtocolError(
                "[QuadRix] item components are not ported yet (items.rs pending)"
            )
        w.varint(self.item)
        w.varint(self.count)
        w.varint(len(self.components))


@dataclass(frozen=True)
class NetOffer:
    """MerchantOffer.STREAM_CODEC (play.rs:127)."""

    cost_a: NetCost
    result: ItemStack
    cost_b: Optional[NetCost]
    out_of_stock: bool
    uses: int
    max_uses: int
    xp: int
    special_price: int
    price_multiplier: float
    demand: int

    @classmethod
    def read(cls, r: Reader) -> "NetOffer":
        cost_a = NetCost.read(r)
        result = _Slot.read(r)
        if result is None:
            raise ProtocolError("[QuadRix] empty merchant result")
        cost_b = NetCost.read(r) if r.bool() else None
        return cls(
            cost_a,
            result,
            cost_b,
            Bool.read(r),
            Int.read(r),
            Int.read(r),
            Int.read(r),
            Int.read(r),
            Float.read(r),
            Int.read(r),
        )

    def write(self, w: Writer) -> None:
        self.cost_a.write(w)
        _Slot.write(self.result, w)
        Bool.write(self.cost_b is not None, w)
        if self.cost_b is not None:
            self.cost_b.write(w)
        Bool.write(self.out_of_stock, w)
        Int.write(self.uses, w)
        Int.write(self.max_uses, w)
        Int.write(self.xp, w)
        Int.write(self.special_price, w)
        Float.write(self.price_multiplier, w)
        Int.write(self.demand, w)


class _Offers:
    """Offers (play.rs:141): список MerchantOffer."""

    @classmethod
    def read(cls, r: Reader) -> list[NetOffer]:
        return [NetOffer.read(r) for _ in range(r.count(r.remaining()))]

    @classmethod
    def write(cls, v: list[NetOffer], w: Writer) -> None:
        w.varint(len(v))
        for offer in v:
            offer.write(w)


# ---- clientbound: контейнеры и слоты ----------------------------------


@dataclass
class ContainerClose(_Packet):
    """ClientboundContainerClosePacket: id закрываемого окна."""

    container: int

    @classmethod
    def read(cls, r: Reader) -> "ContainerClose":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)


@dataclass
class ContainerSetContent(_Packet):
    """ClientboundContainerSetContentPacket: всё содержимое окна.

    `items` — список Optional<Stack> (List<Slot>), `carried` — стек на
    курсоре.
    """

    container: int
    state: int
    items: list[Optional[ItemStack]]
    carried: Optional[ItemStack]

    @classmethod
    def read(cls, r: Reader) -> "ContainerSetContent":
        return cls(
            VarInt.read(r),
            VarInt.read(r),
            List(_Slot).read(r),
            _Slot.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.state, w)
        List(_Slot).write(self.items, w)
        _Slot.write(self.carried, w)


@dataclass
class ContainerSetSlot(_Packet):
    """ClientboundContainerSetSlotPacket: один слот окна."""

    container: int
    state: int
    slot: int
    item: Optional[ItemStack]

    @classmethod
    def read(cls, r: Reader) -> "ContainerSetSlot":
        return cls(
            VarInt.read(r),
            VarInt.read(r),
            Short.read(r),
            _Slot.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.state, w)
        Short.write(self.slot, w)
        _Slot.write(self.item, w)


@dataclass
class ContainerSetData(_Packet):
    """ClientboundContainerSetDataPacket: свойство окна (id/value, Short)."""

    container: int
    id: int
    value: int

    @classmethod
    def read(cls, r: Reader) -> "ContainerSetData":
        return cls(VarInt.read(r), Short.read(r), Short.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        Short.write(self.id, w)
        Short.write(self.value, w)


@dataclass
class MerchantOffers(_Packet):
    """ClientboundMerchantOffersPacket: предложения торговца."""

    container: int
    offers: list[NetOffer]
    level: int
    xp: int
    show_progress: bool
    can_restock: bool

    @classmethod
    def read(cls, r: Reader) -> "MerchantOffers":
        return cls(
            VarInt.read(r),
            _Offers.read(r),
            VarInt.read(r),
            VarInt.read(r),
            Bool.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        _Offers.write(self.offers, w)
        VarInt.write(self.level, w)
        VarInt.write(self.xp, w)
        Bool.write(self.show_progress, w)
        Bool.write(self.can_restock, w)


@dataclass
class OpenScreen(_Packet):
    """ClientboundOpenScreenPacket: id окна, тип меню и заголовок (NBT)."""

    container: int
    menu: int
    title: object

    @classmethod
    def read(cls, r: Reader) -> "OpenScreen":
        return cls(VarInt.read(r), VarInt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.menu, w)
        Nbt.write(self.title, w)


@dataclass
class SetCursorItem(_Packet):
    """ClientboundSetCursorItemPacket: стек на курсоре (Optional<Stack>)."""

    item: Optional[ItemStack]

    @classmethod
    def read(cls, r: Reader) -> "SetCursorItem":
        return cls(_Slot.read(r))

    def write(self, w: Writer) -> None:
        _Slot.write(self.item, w)


@dataclass
class SetPlayerInventory(_Packet):
    """ClientboundSetPlayerInventoryPacket: слот игрока и предмет."""

    slot: int
    item: Optional[ItemStack]

    @classmethod
    def read(cls, r: Reader) -> "SetPlayerInventory":
        return cls(VarInt.read(r), _Slot.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)
        _Slot.write(self.item, w)


@dataclass
class Cooldown(_Packet):
    """ClientboundCooldownPacket: группа (Ident) и длительность (VarInt)."""

    group: str
    duration: int

    @classmethod
    def read(cls, r: Reader) -> "Cooldown":
        return cls(Ident.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.group, w)
        VarInt.write(self.duration, w)


# ---- serverbound: клики по контейнеру и правки слотов -----------------


@dataclass
class ContainerClick(_Packet):
    """ServerboundContainerClickPacket: клик по слоту контейнера.

    `input` — ContainerInput (0 pickup, 1 quick move, 2 swap, 3 clone,
    4 throw, 5 quick craft, 6 pickup all); `changed` — пары
    (slot, Option<Hashed>); `carried` — стек на курсоре (Option<Hashed>).
    """

    container: int
    state: int
    slot: int
    button: int
    input: int
    changed: list[Tuple[int, Optional[Hashed]]]
    carried: Optional[Hashed]

    @classmethod
    def read(cls, r: Reader) -> "ContainerClick":
        return cls(
            VarInt.read(r),
            VarInt.read(r),
            Short.read(r),
            Byte.read(r),
            VarInt.read(r),
            _ChangedSlots.read(r),
            _HashedSlot.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.state, w)
        Short.write(self.slot, w)
        Byte.write(self.button, w)
        VarInt.write(self.input, w)
        _ChangedSlots.write(self.changed, w)
        _HashedSlot.write(self.carried, w)


@dataclass
class ContainerButtonClick(_Packet):
    """ServerboundContainerButtonClickPacket: нажатие кнопки окна."""

    container: int
    button: int

    @classmethod
    def read(cls, r: Reader) -> "ContainerButtonClick":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.button, w)


@dataclass
class ContainerSlotStateChanged(_Packet):
    """ServerboundContainerSlotStateChangedPacket: переключатель слота."""

    slot: int
    container: int
    enabled: bool

    @classmethod
    def read(cls, r: Reader) -> "ContainerSlotStateChanged":
        return cls(VarInt.read(r), VarInt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)
        VarInt.write(self.container, w)
        Bool.write(self.enabled, w)


@dataclass
class RenameItem(_Packet):
    """ServerboundRenameItemPacket: новое имя предмета на наковальне."""

    name: str

    @classmethod
    def read(cls, r: Reader) -> "RenameItem":
        return cls(Str.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.name, w)


@dataclass
class EditBook(_Packet):
    """ServerboundEditBookPacket: слот, страницы и опциональный заголовок."""

    slot: int
    pages: list[str]
    title: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "EditBook":
        return cls(
            VarInt.read(r),
            _BookPages.read(r),
            Opt(StrN(32)).read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)
        _BookPages.write(self.pages, w)
        Opt(StrN(32)).write(self.title, w)


@dataclass
class SetCreativeModeSlot(_Packet):
    """ServerboundSetCreativeModeSlotPacket: слот и предмет (Short, Slot)."""

    slot: int
    item: Optional[ItemStack]

    @classmethod
    def read(cls, r: Reader) -> "SetCreativeModeSlot":
        return cls(Short.read(r), _Slot.read(r))

    def write(self, w: Writer) -> None:
        Short.write(self.slot, w)
        _Slot.write(self.item, w)


@dataclass
class SelectTrade(_Packet):
    """ServerboundSelectTradePacket: индекс выбранного предложения."""

    item: int

    @classmethod
    def read(cls, r: Reader) -> "SelectTrade":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.item, w)


# ── PART 6: мир, чанки, свет, границы, погода, рецепты и остаток ─────
#
# Источник — play.rs (packet! + packet_enum!), chunk.rs (ChunkData /
# LightData / Paletted / Layers), recipes.rs (RecipeBook*) и adapter/ids.rs
# (переадресация id ещё не портирована, поэтому item/component/
# slot_display/sound_event — тождественные отображения).
#
# Форма чанка на проводе сохраняется сырой: heightmaps как long-массивы,
# buffer — необработанные байты секций, light — байтовые слои по 2048.
# В полноценный Chunk это НЕ разбирается (это делает mesher клиента).

# ---- общие структуры (play.rs:27-58) ---------------------------------


@dataclass
class GlobalPos(_Packet):
    """GlobalPos: измерение (Identifier) и позиция блока."""

    dimension: str
    pos: Tuple[int, int, int]

    @classmethod
    def read(cls, r: Reader) -> "GlobalPos":
        return cls(Ident.read(r), Pos.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.dimension, w)
        Pos.write(self.pos, w)


@dataclass
class SpawnInfo(_Packet):
    """CommonPlayerSpawnInfo (play.rs:33)."""

    dimension_type: int
    dimension: str
    seed: int
    game_type: int
    previous_game_type: Optional[int]
    debug: bool
    flat: bool
    last_death: Optional[GlobalPos]
    portal_cooldown: int
    sea_level: int

    @classmethod
    def read(cls, r: Reader) -> "SpawnInfo":
        return cls(
            VarInt.read(r),
            Ident.read(r),
            Long.read(r),
            VarInt.read(r),
            OptVarInt.read(r),
            Bool.read(r),
            Bool.read(r),
            Opt(GlobalPos).read(r),
            VarInt.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.dimension_type, w)
        Ident.write(self.dimension, w)
        Long.write(self.seed, w)
        VarInt.write(self.game_type, w)
        OptVarInt.write(self.previous_game_type, w)
        Bool.write(self.debug, w)
        Bool.write(self.flat, w)
        Opt(GlobalPos).write(self.last_death, w)
        VarInt.write(self.portal_cooldown, w)
        VarInt.write(self.sea_level, w)


# ---- общие кодеки PART 6 ---------------------------------------------


class _StatList:
    """StatList (play.rs:1827): (тип, значение, счётчик) по сети."""

    @classmethod
    def read(cls, r: Reader) -> list[Tuple[int, int, int]]:
        n = r.count(r.remaining())
        return [(r.varint(), r.varint(), r.varint()) for _ in range(n)]

    @classmethod
    def write(cls, v: list[Tuple[int, int, int]], w: Writer) -> None:
        w.varint(len(v))
        for a, b, c in v:
            w.varint(a)
            w.varint(b)
            w.varint(c)


class _SoundHolder:
    """SoundHolder (play.rs:903): id реестра, иначе location + Opt(range)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, Optional[Tuple[str, Optional[float]]]]:
        ident = r.varint()
        if ident != 0:
            return (ident - 1, None)
        location = r.string(32767)
        return (-1, (location, r.f32() if r.bool() else None))

    @classmethod
    def write(
        cls,
        v: Tuple[int, Optional[Tuple[str, Optional[float]]]],
        w: Writer,
    ) -> None:
        ident, direct = v
        if direct is None:
            w.varint(ident + 1)
            return
        w.varint(0)
        w.string(direct[0])
        Opt(Float).write(direct[1], w)


class _Equipment:
    """Equipment (play.rs:861): пары (ordinal, стек) с битом продолжения."""

    @classmethod
    def read(cls, r: Reader) -> list[Tuple[int, Optional[ItemStack]]]:
        out: list[Tuple[int, Optional[ItemStack]]] = []
        while True:
            slot = r.u8()
            out.append((slot & 127, _Slot.read(r)))
            if slot & 128 == 0:
                return out

    @classmethod
    def write(cls, v: list[Tuple[int, Optional[ItemStack]]], w: Writer) -> None:
        for i, (slot, stack) in enumerate(v):
            w.u8((slot | 128) if i + 1 < len(v) else slot)
            _Slot.write(stack, w)


@dataclass
class MapDecoration(_Packet):
    """MapDecoration (play.rs:398): holder, позиция, поворот, имя."""

    kind: int
    x: int
    y: int
    rot: int
    name: object

    @classmethod
    def read(cls, r: Reader) -> "MapDecoration":
        return cls(
            VarInt.read(r),
            Byte.read(r),
            Byte.read(r),
            Byte.read(r),
            Opt(Nbt).read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.kind, w)
        Byte.write(self.x, w)
        Byte.write(self.y, w)
        Byte.write(self.rot, w)
        Opt(Nbt).write(self.name, w)


@dataclass(frozen=True)
class MapPatch:
    """MapItemSavedData.MapPatch (play.rs:409): ширина 0 — пусто."""

    start_x: int
    start_y: int
    width: int
    height: int
    colors: bytes


class _MapPatchOpt:
    """MapPatchOpt (play.rs:416): Option<MapPatch> как в Rust."""

    @classmethod
    def read(cls, r: Reader) -> Optional[MapPatch]:
        width = r.u8()
        if width == 0:
            return None
        height = r.u8()
        start_x = r.u8()
        start_y = r.u8()
        colors = bytes(r.bytes(r.count(r.remaining())))
        return MapPatch(start_x, start_y, width, height, colors)

    @classmethod
    def write(cls, v: Optional[MapPatch], w: Writer) -> None:
        if v is None:
            w.u8(0)
            return
        w.u8(v.width)
        w.u8(v.height)
        w.u8(v.start_x)
        w.u8(v.start_y)
        w.varint(len(v.colors))
        w.bytes(v.colors)


@dataclass
class BossAction:
    """BossEvent.Action (play.rs:1847): операция (0..5) и её поля."""

    op: int
    name: object = None
    progress: float = 0.0
    color: int = 0
    overlay: int = 0
    darken: bool = False
    music: bool = False
    fog: bool = False


def _boss_flags(darken: bool, music: bool, fog: bool) -> int:
    return int(darken) | (int(music) << 1) | (int(fog) << 2)


def _split_flags(flags: int) -> Tuple[bool, bool, bool]:
    return (flags & 1 != 0, flags & 2 != 0, flags & 4 != 0)


@dataclass
class BossEvent(_Packet):
    """ClientboundBossEventPacket (play.rs:1878)."""

    id: int
    action: BossAction

    @classmethod
    def read(cls, r: Reader) -> "BossEvent":
        boss_id = r.uuid()
        op = r.varint()
        if op == 0:
            action = BossAction(
                0,
                name=Nbt.read(r),
                progress=Float.read(r),
                color=VarInt.read(r),
                overlay=VarInt.read(r),
            )
            action.darken, action.music, action.fog = _split_flags(r.u8())
        elif op == 1:
            action = BossAction(1)
        elif op == 2:
            action = BossAction(2, progress=Float.read(r))
        elif op == 3:
            action = BossAction(3, name=Nbt.read(r))
        elif op == 4:
            action = BossAction(4, color=VarInt.read(r), overlay=VarInt.read(r))
        elif op == 5:
            action = BossAction(5)
            action.darken, action.music, action.fog = _split_flags(r.u8())
        else:
            raise ProtocolError(f"[QuadRix] unknown boss event operation {op}")
        return cls(boss_id, action)

    def write(self, w: Writer) -> None:
        Uuid.write(self.id, w)
        action = self.action
        w.varint(action.op)
        if action.op == 0:
            Nbt.write(action.name, w)
            w.f32(action.progress)
            w.varint(action.color)
            w.varint(action.overlay)
            w.u8(_boss_flags(action.darken, action.music, action.fog))
        elif action.op == 2:
            w.f32(action.progress)
        elif action.op == 3:
            Nbt.write(action.name, w)
        elif action.op == 4:
            w.varint(action.color)
            w.varint(action.overlay)
        elif action.op == 5:
            w.u8(_boss_flags(action.darken, action.music, action.fog))


@dataclass(frozen=True)
class DialogHolder:
    """Holder<Dialog> (play.rs:253): запись реестра или сам диалог."""

    registry: Optional[int] = None
    direct: object = None

    @classmethod
    def read(cls, r: Reader) -> "DialogHolder":
        ident = r.varint()
        if ident == 0:
            return cls(None, Nbt.read(r))
        return cls(ident - 1, None)

    def write(self, w: Writer) -> None:
        if self.registry is not None:
            w.varint(self.registry + 1)
        else:
            w.varint(0)
            Nbt.write(self.direct, w)


def _read_sign_side(r: Reader) -> bool:
    """SignTextSlot: VarInt 1 — front, любой другой id — back."""
    return r.varint() == 1


def _write_sign_side(v: bool, w: Writer) -> None:
    w.varint(1 if v else 0)


def _read_sign_lines(r: Reader) -> list[str]:
    """SignLines: четыре строки без счётчика (по 384 символа)."""
    return [r.string(384) for _ in range(4)]


def _write_sign_lines(v: list[str], w: Writer) -> None:
    for line in v:
        w.string(line)


def _read_fixed3(r: Reader) -> bytes:
    return bytes(r.bytes(3))


@dataclass
class TestInstanceData(_Packet):
    """TestInstanceBlockEntity.Data (play.rs:2403)."""

    test: Optional[str]
    size: Tuple[int, int, int]
    rotation: int
    ignore_entities: bool
    status: int
    error_message: object

    @classmethod
    def read(cls, r: Reader) -> "TestInstanceData":
        return cls(
            Opt(Ident).read(r),
            VarVec3i.read(r),
            VarInt.read(r),
            Bool.read(r),
            VarInt.read(r),
            Opt(Nbt).read(r),
        )

    def write(self, w: Writer) -> None:
        Opt(Ident).write(self.test, w)
        VarVec3i.write(self.size, w)
        VarInt.write(self.rotation, w)
        Bool.write(self.ignore_entities, w)
        VarInt.write(self.status, w)
        Opt(Nbt).write(self.error_message, w)


# ---- чанки и свет (chunk.rs) -----------------------------------------


@dataclass
class BlockEntityInfo(_Packet):
    """ChunkData.BlockEntityInfo (chunk.rs:270)."""

    packed_xz: int
    y: int
    kind: int
    tag: object

    @classmethod
    def read(cls, r: Reader) -> "BlockEntityInfo":
        return cls(Byte.read(r), Short.read(r), VarInt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        Byte.write(self.packed_xz, w)
        Short.write(self.y, w)
        VarInt.write(self.kind, w)
        Nbt.write(self.tag, w)


class _Heightmaps:
    """Heightmaps (chunk.rs:278): (тип, long-массив), не больше 16."""

    @classmethod
    def read(cls, r: Reader) -> list[Tuple[int, list[int]]]:
        n = r.count(16)
        return [(r.varint(), r.long_array()) for _ in range(n)]

    @classmethod
    def write(cls, v: list[Tuple[int, list[int]]], w: Writer) -> None:
        w.varint(len(v))
        for kind, data in v:
            w.varint(kind)
            Longs.write(data, w)


@dataclass
class ChunkData(_Packet):
    """ClientboundLevelChunkPacketData (chunk.rs:294).

    buffer хранится сырым: секции декодируются mesher'ом, а не здесь.
    """

    heightmaps: list[Tuple[int, list[int]]]
    buffer: bytes
    block_entities: list[BlockEntityInfo]

    @classmethod
    def read(cls, r: Reader) -> "ChunkData":
        heightmaps = _Heightmaps.read(r)
        buffer = bytes(Bytes.read(r))
        n = r.count(r.remaining())
        block_entities = [BlockEntityInfo.read(r) for _ in range(n)]
        return cls(heightmaps, buffer, block_entities)

    def write(self, w: Writer) -> None:
        _Heightmaps.write(self.heightmaps, w)
        Bytes.write(self.buffer, w)
        w.varint(len(self.block_entities))
        for entity in self.block_entities:
            entity.write(w)


class _Layers:
    """Layers (chunk.rs:318): слои по 2048 байт, иначе отказ."""

    @classmethod
    def read(cls, r: Reader) -> list[bytes]:
        n = r.count(r.remaining())
        out: list[bytes] = []
        for _ in range(n):
            layer = bytes(r.byte_array(2048))
            if len(layer) != 2048:
                raise ProtocolError(
                    f"[QuadRix] DataLayer should be 2048 bytes not: "
                    f"{len(layer)}"
                )
            out.append(layer)
        return out

    @classmethod
    def write(cls, v: list[bytes], w: Writer) -> None:
        w.varint(len(v))
        for layer in v:
            w.byte_array(layer)


@dataclass
class LightData(_Packet):
    """ClientboundLightUpdatePacketData (chunk.rs:346)."""

    sky_mask: bytearray
    block_mask: bytearray
    empty_sky_mask: bytearray
    empty_block_mask: bytearray
    sky: list[bytes]
    block: list[bytes]

    @classmethod
    def read(cls, r: Reader) -> "LightData":
        return cls(
            BitSet.read(r),
            BitSet.read(r),
            BitSet.read(r),
            BitSet.read(r),
            _Layers.read(r),
            _Layers.read(r),
        )

    def write(self, w: Writer) -> None:
        BitSet.write(self.sky_mask, w)
        BitSet.write(self.block_mask, w)
        BitSet.write(self.empty_sky_mask, w)
        BitSet.write(self.empty_block_mask, w)
        _Layers.write(self.sky, w)
        _Layers.write(self.block, w)


@dataclass
class ChunkBiomeData(_Packet):
    """ClientboundChunksBiomesPacket.ChunkBiomeData (play.rs:334)."""

    pos: Tuple[int, int]
    buffer: bytes

    @classmethod
    def read(cls, r: Reader) -> "ChunkBiomeData":
        return cls(ChunkPos.read(r), bytes(BytesN(2097152).read(r)))

    def write(self, w: Writer) -> None:
        ChunkPos.write(self.pos, w)
        BytesN(2097152).write(self.buffer, w)


@dataclass
class ChunksBiomes(_Packet):
    """ClientboundChunksBiomesPacket (play.rs:362)."""

    chunks: list[ChunkBiomeData]

    @classmethod
    def read(cls, r: Reader) -> "ChunksBiomes":
        return cls(List(ChunkBiomeData).read(r))

    def write(self, w: Writer) -> None:
        List(ChunkBiomeData).write(self.chunks, w)


@dataclass
class LevelChunkWithLight(_Packet):
    """ClientboundLevelChunkWithLightPacket (play.rs:378)."""

    x: int
    z: int
    chunk: ChunkData
    light: LightData

    @classmethod
    def read(cls, r: Reader) -> "LevelChunkWithLight":
        return cls(Int.read(r), Int.read(r), ChunkData.read(r), LightData.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.x, w)
        Int.write(self.z, w)
        self.chunk.write(w)
        self.light.write(w)


@dataclass
class LightUpdate(_Packet):
    """ClientboundLightUpdatePacket (play.rs:380)."""

    x: int
    z: int
    light: LightData

    @classmethod
    def read(cls, r: Reader) -> "LightUpdate":
        return cls(VarInt.read(r), VarInt.read(r), LightData.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.x, w)
        VarInt.write(self.z, w)
        self.light.write(w)


@dataclass
class ForgetLevelChunk(_Packet):
    """ClientboundForgetLevelChunkPacket (play.rs:330)."""

    pos: Tuple[int, int]

    @classmethod
    def read(cls, r: Reader) -> "ForgetLevelChunk":
        return cls(ChunkPos.read(r))

    def write(self, w: Writer) -> None:
        ChunkPos.write(self.pos, w)


# ---- clientbound: блоки, время и события ------------------------------


@dataclass
class BlockChangedAck(_Packet):
    """ClientboundBlockChangedAckPacket (play.rs:74)."""

    sequence: int

    @classmethod
    def read(cls, r: Reader) -> "BlockChangedAck":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.sequence, w)


@dataclass
class BlockDestruction(_Packet):
    """ClientboundBlockDestructionPacket (play.rs:81)."""

    id: int
    pos: Tuple[int, int, int]
    progress: int

    @classmethod
    def read(cls, r: Reader) -> "BlockDestruction":
        return cls(VarInt.read(r), Pos.read(r), UByte.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Pos.write(self.pos, w)
        UByte.write(self.progress, w)


@dataclass
class BlockEntityData(_Packet):
    """ClientboundBlockEntityDataPacket (play.rs:82)."""

    pos: Tuple[int, int, int]
    kind: int
    tag: object

    @classmethod
    def read(cls, r: Reader) -> "BlockEntityData":
        return cls(Pos.read(r), VarInt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.kind, w)
        Nbt.write(self.tag, w)


@dataclass
class BlockUpdate(_Packet):
    """ClientboundBlockUpdatePacket (play.rs:83)."""

    pos: Tuple[int, int, int]
    state: int

    @classmethod
    def read(cls, r: Reader) -> "BlockUpdate":
        return cls(Pos.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.state, w)


@dataclass
class AddTransientBlock(_Packet):
    """ClientboundAddTransientBlockPacket (play.rs:86)."""

    pos: Tuple[int, int, int]
    state: int

    @classmethod
    def read(cls, r: Reader) -> "AddTransientBlock":
        return cls(Pos.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.state, w)


@dataclass
class BlockEvent(_Packet):
    """ClientboundBlockEventPacket (play.rs:952)."""

    pos: Tuple[int, int, int]
    b0: int
    b1: int
    block: int

    @classmethod
    def read(cls, r: Reader) -> "BlockEvent":
        return cls(Pos.read(r), UByte.read(r), UByte.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        UByte.write(self.b0, w)
        UByte.write(self.b1, w)
        VarInt.write(self.block, w)


@dataclass
class LevelEvent(_Packet):
    """ClientboundLevelEventPacket (play.rs:379)."""

    kind: int
    pos: Tuple[int, int, int]
    data: int
    global_: bool

    @classmethod
    def read(cls, r: Reader) -> "LevelEvent":
        return cls(Int.read(r), Pos.read(r), Int.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.kind, w)
        Pos.write(self.pos, w)
        Int.write(self.data, w)
        Bool.write(self.global_, w)


@dataclass
class SectionBlocksUpdate(_Packet):
    """ClientboundSectionBlocksUpdatePacket (play.rs:811).

    Каждое изменение: state << 12 | x << 8 | z << 4 | y внутри секции.
    """

    section: Tuple[int, int, int]
    changes: list[int]

    @classmethod
    def read(cls, r: Reader) -> "SectionBlocksUpdate":
        return cls(SectionPos.read(r), List(VarLong).read(r))

    def write(self, w: Writer) -> None:
        SectionPos.write(self.section, w)
        List(VarLong).write(self.changes, w)


@dataclass
class ChangeDifficulty(_Packet):
    """ClientboundChangeDifficultyPacket (play.rs:87)."""

    difficulty: int
    locked: bool

    @classmethod
    def read(cls, r: Reader) -> "ChangeDifficulty":
        return cls(VarInt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.difficulty, w)
        Bool.write(self.locked, w)


@dataclass
class GameRuleEntry(_Packet):
    """GameRuleEntry (play.rs:89): имя правила и его значение."""

    name: str
    value: str

    @classmethod
    def read(cls, r: Reader) -> "GameRuleEntry":
        return cls(Ident.read(r), Str.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.name, w)
        Str.write(self.value, w)


@dataclass
class GameRuleValues(_Packet):
    """ClientboundGameRuleValuesPacket (play.rs:90)."""

    entries: list[GameRuleEntry]

    @classmethod
    def read(cls, r: Reader) -> "GameRuleValues":
        return cls(List(GameRuleEntry).read(r))

    def write(self, w: Writer) -> None:
        List(GameRuleEntry).write(self.entries, w)


@dataclass
class ChunkBatchFinished(_Packet):
    """ClientboundChunkBatchFinishedPacket (play.rs:91)."""

    size: int

    @classmethod
    def read(cls, r: Reader) -> "ChunkBatchFinished":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.size, w)


class ChunkBatchStart(Empty):
    """ClientboundChunkBatchStartPacket (пустой payload)."""


class LowDiskSpaceWarning(Empty):
    """ClientboundLowDiskSpaceWarningPacket (пустой payload)."""


class StartConfiguration(Empty):
    """ClientboundStartConfigurationPacket (пустой payload)."""


@dataclass
class DistanceBase(_Packet):
    """Distance (play.rs:823): один VarInt. Используется двумя ID."""

    distance: int

    @classmethod
    def read(cls, r: Reader) -> "DistanceBase":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.distance, w)


@dataclass
class SetChunkCacheRadius(DistanceBase):
    """ClientboundSetChunkCacheRadiusPacket (Distance, play.rs:823)."""


@dataclass
class SetSimulationDistance(DistanceBase):
    """ClientboundSetSimulationDistancePacket (Distance, play.rs:823)."""


@dataclass
class SetDefaultSpawnPosition(_Packet):
    """ClientboundSetDefaultSpawnPositionPacket (play.rs:825)."""

    pos: GlobalPos
    yaw: float
    pitch: float

    @classmethod
    def read(cls, r: Reader) -> "SetDefaultSpawnPosition":
        return cls(GlobalPos.read(r), Float.read(r), Float.read(r))

    def write(self, w: Writer) -> None:
        self.pos.write(w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)


@dataclass
class SetDisplayObjective(_Packet):
    """ClientboundSetDisplayObjectivePacket (play.rs:990)."""

    slot: int
    objective: str

    @classmethod
    def read(cls, r: Reader) -> "SetDisplayObjective":
        return cls(VarInt.read(r), Str.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)
        Str.write(self.objective, w)


@dataclass
class SetExperience(_Packet):
    """ClientboundSetExperiencePacket (play.rs:881)."""

    progress: float
    level: int
    total: int

    @classmethod
    def read(cls, r: Reader) -> "SetExperience":
        return cls(Float.read(r), VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Float.write(self.progress, w)
        VarInt.write(self.level, w)
        VarInt.write(self.total, w)


@dataclass
class UpdateMobEffect(_Packet):
    """ClientboundUpdateMobEffectPacket (play.rs:1267)."""

    id: int
    effect: int
    amplifier: int
    duration: int
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "UpdateMobEffect":
        return cls(
            VarInt.read(r), VarInt.read(r), VarInt.read(r), VarInt.read(r), Byte.read(r)
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.effect, w)
        VarInt.write(self.amplifier, w)
        VarInt.write(self.duration, w)
        Byte.write(self.flags, w)


@dataclass
class RemoveMobEffect(_Packet):
    """ClientboundRemoveMobEffectPacket (play.rs:1269)."""

    id: int
    effect: int

    @classmethod
    def read(cls, r: Reader) -> "RemoveMobEffect":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        VarInt.write(self.effect, w)


@dataclass
class InitializeBorder(_Packet):
    """ClientboundInitializeBorderPacket (play.rs:955)."""

    center_x: float
    center_z: float
    old_size: float
    new_size: float
    lerp_time: int
    absolute_max_size: int
    warning_blocks: int
    warning_time: int

    @classmethod
    def read(cls, r: Reader) -> "InitializeBorder":
        return cls(
            Double.read(r),
            Double.read(r),
            Double.read(r),
            Double.read(r),
            VarLong.read(r),
            VarInt.read(r),
            VarInt.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        Double.write(self.center_x, w)
        Double.write(self.center_z, w)
        Double.write(self.old_size, w)
        Double.write(self.new_size, w)
        VarLong.write(self.lerp_time, w)
        VarInt.write(self.absolute_max_size, w)
        VarInt.write(self.warning_blocks, w)
        VarInt.write(self.warning_time, w)


@dataclass
class SetBorderCenter(_Packet):
    """ClientboundSetBorderCenterPacket (play.rs:969)."""

    x: float
    z: float

    @classmethod
    def read(cls, r: Reader) -> "SetBorderCenter":
        return cls(Double.read(r), Double.read(r))

    def write(self, w: Writer) -> None:
        Double.write(self.x, w)
        Double.write(self.z, w)


@dataclass
class SetBorderLerpSize(_Packet):
    """ClientboundSetBorderLerpSizePacket (play.rs:973)."""

    old_size: float
    new_size: float
    lerp_time: int

    @classmethod
    def read(cls, r: Reader) -> "SetBorderLerpSize":
        return cls(Double.read(r), Double.read(r), VarLong.read(r))

    def write(self, w: Writer) -> None:
        Double.write(self.old_size, w)
        Double.write(self.new_size, w)
        VarLong.write(self.lerp_time, w)


@dataclass
class SetBorderSize(_Packet):
    """ClientboundSetBorderSizePacket (play.rs:977)."""

    size: float

    @classmethod
    def read(cls, r: Reader) -> "SetBorderSize":
        return cls(Double.read(r))

    def write(self, w: Writer) -> None:
        Double.write(self.size, w)


@dataclass
class SetBorderWarningDelay(_Packet):
    """ClientboundSetBorderWarningDelayPacket (play.rs:981)."""

    delay: int

    @classmethod
    def read(cls, r: Reader) -> "SetBorderWarningDelay":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.delay, w)


@dataclass
class SetBorderWarningDistance(_Packet):
    """ClientboundSetBorderWarningDistancePacket (play.rs:985)."""

    blocks: int

    @classmethod
    def read(cls, r: Reader) -> "SetBorderWarningDistance":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.blocks, w)


# ---- clientbound: звук, частицы, вспышка ------------------------------


@dataclass
class Sound(_Packet):
    """ClientboundSoundPacket (play.rs:925)."""

    sound: Tuple[int, Optional[Tuple[str, Optional[float]]]]
    source: int
    x: int
    y: int
    z: int
    volume: float
    pitch: float
    seed: int

    @classmethod
    def read(cls, r: Reader) -> "Sound":
        return cls(
            _SoundHolder.read(r),
            VarInt.read(r),
            Int.read(r),
            Int.read(r),
            Int.read(r),
            Float.read(r),
            Float.read(r),
            Long.read(r),
        )

    def write(self, w: Writer) -> None:
        _SoundHolder.write(self.sound, w)
        VarInt.write(self.source, w)
        Int.write(self.x, w)
        Int.write(self.y, w)
        Int.write(self.z, w)
        Float.write(self.volume, w)
        Float.write(self.pitch, w)
        Long.write(self.seed, w)


@dataclass
class SoundEntity(_Packet):
    """ClientboundSoundEntityPacket (play.rs:1293)."""

    sound: Tuple[int, Optional[Tuple[str, Optional[float]]]]
    source: int
    id: int
    volume: float
    pitch: float
    seed: int

    @classmethod
    def read(cls, r: Reader) -> "SoundEntity":
        return cls(
            _SoundHolder.read(r),
            VarInt.read(r),
            VarInt.read(r),
            Float.read(r),
            Float.read(r),
            Long.read(r),
        )

    def write(self, w: Writer) -> None:
        _SoundHolder.write(self.sound, w)
        VarInt.write(self.source, w)
        VarInt.write(self.id, w)
        Float.write(self.volume, w)
        Float.write(self.pitch, w)
        Long.write(self.seed, w)


@dataclass
class StopSound(_Packet):
    """ClientboundStopSoundPacket (play.rs:1304): бит 0 — source, бит 1 — id."""

    source: Optional[int]
    sound: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "StopSound":
        flags = r.u8()
        source = None
        if flags & 1 != 0:
            value = r.varint()
            if not 0 <= value < 11:
                raise ProtocolError("[QuadRix] invalid sound source")
            source = value
        sound = r.string(32767) if flags & 2 != 0 else None
        return cls(source, sound)

    def write(self, w: Writer) -> None:
        flags = int(self.source is not None) | (int(self.sound is not None) << 1)
        w.u8(flags)
        if self.source is not None:
            w.varint(self.source)
        if self.sound is not None:
            w.string(self.sound)


@dataclass
class LevelParticles(_Packet):
    """ClientboundLevelParticlesPacket (play.rs:1081)."""

    particle: Particle
    override_limiter: bool
    always_show: bool
    pos: Tuple[float, float, float]
    dist: Tuple[float, float, float]
    max_speed: Tuple[float, float, float]
    count: int
    randomization: int

    @classmethod
    def read(cls, r: Reader) -> "LevelParticles":
        particle = Particle.read(r)
        override_limiter = Bool.read(r)
        always_show = Bool.read(r)
        pos = Vec3d.read(r)
        dist = (Float.read(r), Float.read(r), Float.read(r))
        max_speed = (Float.read(r), Float.read(r), Float.read(r))
        return cls(
            particle,
            override_limiter,
            always_show,
            pos,
            dist,
            max_speed,
            VarInt.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        self.particle.write(w)
        Bool.write(self.override_limiter, w)
        Bool.write(self.always_show, w)
        Vec3d.write(self.pos, w)
        for value in (*self.dist, *self.max_speed):
            Float.write(value, w)
        VarInt.write(self.count, w)
        VarInt.write(self.randomization, w)


@dataclass
class ExplosionParticle(_Packet):
    """ExplosionParticleInfo (play.rs:1119)."""

    particle: Particle
    scaling: float
    speed: float
    weight: int

    @classmethod
    def read(cls, r: Reader) -> "ExplosionParticle":
        return cls(
            Particle.read(r), Float.read(r), Float.read(r), VarInt.read(r)
        )

    def write(self, w: Writer) -> None:
        self.particle.write(w)
        Float.write(self.scaling, w)
        Float.write(self.speed, w)
        VarInt.write(self.weight, w)


@dataclass
class Explode(_Packet):
    """ClientboundExplodePacket (play.rs:1129)."""

    center: Tuple[float, float, float]
    radius: float
    block_count: int
    knockback: Optional[Tuple[float, float, float]]
    particle: Particle
    sound: Tuple[int, Optional[Tuple[str, Optional[float]]]]
    block_particles: list[ExplosionParticle]
    play_sound: bool

    @classmethod
    def read(cls, r: Reader) -> "Explode":
        center = Vec3d.read(r)
        radius = Float.read(r)
        block_count = Int.read(r)
        knockback = Opt(Vec3d).read(r)
        particle = Particle.read(r)
        sound = _SoundHolder.read(r)
        n = r.varint()
        block_particles = [ExplosionParticle.read(r) for _ in range(n)]
        return cls(
            center,
            radius,
            block_count,
            knockback,
            particle,
            sound,
            block_particles,
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        Vec3d.write(self.center, w)
        Float.write(self.radius, w)
        Int.write(self.block_count, w)
        Opt(Vec3d).write(self.knockback, w)
        self.particle.write(w)
        _SoundHolder.write(self.sound, w)
        w.varint(len(self.block_particles))
        for part in self.block_particles:
            part.write(w)
        Bool.write(self.play_sound, w)


# ---- clientbound: экраны, статистика, достижения ----------------------


@dataclass
class MountScreenOpen(_Packet):
    """ClientboundMountScreenOpenPacket (play.rs:584)."""

    container: int
    columns: int
    entity: int

    @classmethod
    def read(cls, r: Reader) -> "MountScreenOpen":
        return cls(VarInt.read(r), VarInt.read(r), Int.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.columns, w)
        Int.write(self.entity, w)


@dataclass
class OpenBook(_Packet):
    """ClientboundOpenBookPacket (play.rs:592)."""

    hand: int

    @classmethod
    def read(cls, r: Reader) -> "OpenBook":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.hand, w)


@dataclass
class OpenSignEditor(_Packet):
    """ClientboundOpenSignEditorPacket (play.rs:587)."""

    pos: Tuple[int, int, int]
    front: bool

    @classmethod
    def read(cls, r: Reader) -> "OpenSignEditor":
        return cls(Pos.read(r), _read_sign_side(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        _write_sign_side(self.front, w)


@dataclass
class PlayerCombatKill(_Packet):
    """ClientboundPlayerCombatKillPacket (play.rs:662)."""

    id: int
    message: object

    @classmethod
    def read(cls, r: Reader) -> "PlayerCombatKill":
        return cls(VarInt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Nbt.write(self.message, w)


@dataclass
class TagQuery(_Packet):
    """ClientboundTagQueryPacket (play.rs:939)."""

    transaction: int
    tag: object

    @classmethod
    def read(cls, r: Reader) -> "TagQuery":
        return cls(VarInt.read(r), Nbt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.transaction, w)
        Nbt.write(self.tag, w)


@dataclass
class AwardStats(_Packet):
    """ClientboundAwardStatsPacket (play.rs:1824)."""

    stats: list[Tuple[int, int, int]]

    @classmethod
    def read(cls, r: Reader) -> "AwardStats":
        return cls(_StatList.read(r))

    def write(self, w: Writer) -> None:
        _StatList.write(self.stats, w)


@dataclass
class SelectAdvancementsTab(_Packet):
    """ClientboundSelectAdvancementsTabPacket (play.rs:79)."""

    tab: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "SelectAdvancementsTab":
        return cls(Opt(Ident).read(r))

    def write(self, w: Writer) -> None:
        Opt(Ident).write(self.tab, w)


@dataclass
class AdvancementDisplay(_Packet):
    """DisplayInfo достижения (play.rs:1658)."""

    title: object
    description: object
    icon: ItemStack
    frame: int
    show_toast: bool
    hidden: bool
    background: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "AdvancementDisplay":
        title = Nbt.read(r)
        description = Nbt.read(r)
        icon = _Template.read(r)
        frame = VarInt.read(r)
        flags = Int.read(r)
        background = r.string(32767) if flags & 1 != 0 else None
        return cls(
            title,
            description,
            icon,
            frame,
            flags & 2 != 0,
            flags & 4 != 0,
            background,
        )

    def write(self, w: Writer) -> None:
        Nbt.write(self.title, w)
        Nbt.write(self.description, w)
        _Template.write(self.icon, w)
        VarInt.write(self.frame, w)
        flags = (
            int(self.background is not None)
            | int(self.show_toast) << 1
            | int(self.hidden) << 2
        )
        Int.write(flags, w)
        if self.background is not None:
            w.string(self.background)


@dataclass
class Advancement(_Packet):
    """PositionedAdvancement (play.rs:1670)."""

    id: str
    parent: Optional[str]
    display: Optional[AdvancementDisplay]
    requirements: list[list[str]]
    telemetry: bool
    x: float
    y: float

    @classmethod
    def read(cls, r: Reader) -> "Advancement":
        ident = r.string(32767)
        parent = r.string(32767) if r.bool() else None
        display = AdvancementDisplay.read(r) if r.bool() else None
        groups = r.count(r.remaining())
        requirements = [
            [r.string(32767) for _ in range(r.count(r.remaining()))]
            for _ in range(groups)
        ]
        telemetry = Bool.read(r)
        x = Float.read(r)
        y = Float.read(r)
        return cls(ident, parent, display, requirements, telemetry, x, y)

    def write(self, w: Writer) -> None:
        w.string(self.id)
        Bool.write(self.parent is not None, w)
        if self.parent is not None:
            w.string(self.parent)
        Bool.write(self.display is not None, w)
        if self.display is not None:
            self.display.write(w)
        w.varint(len(self.requirements))
        for group in self.requirements:
            w.varint(len(group))
            for criterion in group:
                w.string(criterion)
        Bool.write(self.telemetry, w)
        Float.write(self.x, w)
        Float.write(self.y, w)


@dataclass
class UpdateAdvancements(_Packet):
    """ClientboundUpdateAdvancementsPacket (play.rs:1684)."""

    reset: bool
    added: list[Advancement]
    removed: list[str]
    progress: list[Tuple[str, list[Tuple[str, Optional[int]]]]]
    show: bool

    @classmethod
    def read(cls, r: Reader) -> "UpdateAdvancements":
        reset = Bool.read(r)
        n = r.count(r.remaining())
        added = [Advancement.read(r) for _ in range(n)]
        n = r.count(r.remaining())
        removed = [r.string(32767) for _ in range(n)]
        n = r.count(r.remaining())
        progress = []
        for _ in range(n):
            ident = r.string(32767)
            k = r.count(r.remaining())
            criteria = []
            for _ in range(k):
                name = r.string(32767)
                at = Long.read(r) if r.bool() else None
                criteria.append((name, at))
            progress.append((ident, criteria))
        show = Bool.read(r)
        return cls(reset, added, removed, progress, show)

    def write(self, w: Writer) -> None:
        Bool.write(self.reset, w)
        w.varint(len(self.added))
        for adv in self.added:
            adv.write(w)
        w.varint(len(self.removed))
        for ident in self.removed:
            w.string(ident)
        w.varint(len(self.progress))
        for ident, criteria in self.progress:
            w.string(ident)
            w.varint(len(criteria))
            for name, at in criteria:
                w.string(name)
                Bool.write(at is not None, w)
                if at is not None:
                    Long.write(at, w)
        Bool.write(self.show, w)


@dataclass
class SetObjective(_Packet):
    """ClientboundSetObjectivePacket (play.rs:1043)."""

    name: str
    method: int
    display: Optional[Tuple[object, int, Optional[NumberFormat]]]

    @classmethod
    def read(cls, r: Reader) -> "SetObjective":
        name = r.string(32767)
        method = Byte.read(r)
        display = None
        if method in (0, 2):
            display = (Nbt.read(r), VarInt.read(r), Opt(NumberFormat).read(r))
        return cls(name, method, display)

    def write(self, w: Writer) -> None:
        w.string(self.name)
        Byte.write(self.method, w)
        if self.method in (0, 2):
            name, render, fmt = self.display or (
                Tag(TagType.End, is_end=True),
                0,
                None,
            )
            Nbt.write(name, w)
            VarInt.write(render, w)
            Opt(NumberFormat).write(fmt, w)


# ---- clientbound: карта предмета -------------------------------------


@dataclass
class MapItemData(_Packet):
    """ClientboundMapItemDataPacket (play.rs:450)."""

    map_id: int
    scale: int
    locked: bool
    decorations: Optional[list[MapDecoration]]
    patch: Optional[MapPatch]

    @classmethod
    def read(cls, r: Reader) -> "MapItemData":
        return cls(
            VarInt.read(r),
            Byte.read(r),
            Bool.read(r),
            Opt(List(MapDecoration)).read(r),
            _MapPatchOpt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.map_id, w)
        Byte.write(self.scale, w)
        Bool.write(self.locked, w)
        Opt(List(MapDecoration)).write(self.decorations, w)
        _MapPatchOpt.write(self.patch, w)


# ---- clientbound: локатор (waypoint) ----------------------------------


@dataclass
class TrackedWaypoint(_Packet):
    """ClientboundTrackedWaypointPacket (play.rs:2136).

    id: ("uuid", value) | ("name", value).
    target: ("empty",) | ("block", (x,y,z)) | ("chunk", (x,z)) | ("azimuth", f).
    """

    operation: int
    id: Tuple[str, object]
    style: str
    color: Optional[int]
    target: tuple

    @classmethod
    def read(cls, r: Reader) -> "TrackedWaypoint":
        operation = r.varint()
        if not 0 <= operation <= 2:
            raise ProtocolError(f"[QuadRix] waypoint operation {operation}")
        ident = ("uuid", Uuid.read(r)) if r.bool() else ("name", r.string(32767))
        style = Ident.read(r)
        color = None
        if r.bool():
            red, green, blue = r.u8(), r.u8(), r.u8()
            color = -16777216 | red << 16 | green << 8 | blue
        kind = r.varint()
        if kind == 0:
            target = ("empty",)
        elif kind == 1:
            target = ("block", (r.varint(), r.varint(), r.varint()))
        elif kind == 2:
            target = ("chunk", (r.varint(), r.varint()))
        elif kind == 3:
            target = ("azimuth", Float.read(r))
        else:
            raise ProtocolError(f"[QuadRix] waypoint type {kind}")
        return cls(operation, ident, style, color, target)

    def write(self, w: Writer) -> None:
        VarInt.write(self.operation, w)
        if self.id[0] == "uuid":
            Bool.write(True, w)
            Uuid.write(self.id[1], w)
        else:
            Bool.write(False, w)
            w.string(self.id[1])
        w.string(self.style)
        Bool.write(self.color is not None, w)
        if self.color is not None:
            for shift in (16, 8, 0):
                w.u8((self.color >> shift) & 0xFF)
        target = self.target
        if target[0] == "empty":
            w.varint(0)
        elif target[0] == "block":
            w.varint(1)
            for value in target[1]:
                w.varint(value)
        elif target[0] == "chunk":
            w.varint(2)
            for value in target[1]:
                w.varint(value)
        else:
            w.varint(3)
            Float.write(target[1], w)


# ---- clientbound: вход и возрождение ----------------------------------


@dataclass
class Login(_Packet):
    """ClientboundLoginPacket (play.rs:381)."""

    player_id: int
    hardcore: bool
    levels: list[str]
    max_players: int
    chunk_radius: int
    simulation_distance: int
    reduced_debug_info: bool
    show_death_screen: bool
    limited_crafting: bool
    spawn: SpawnInfo
    online_mode: bool
    enforces_secure_chat: bool

    @classmethod
    def read(cls, r: Reader) -> "Login":
        return cls(
            Int.read(r),
            Bool.read(r),
            List(Ident).read(r),
            VarInt.read(r),
            VarInt.read(r),
            VarInt.read(r),
            Bool.read(r),
            Bool.read(r),
            Bool.read(r),
            SpawnInfo.read(r),
            Bool.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        Int.write(self.player_id, w)
        Bool.write(self.hardcore, w)
        List(Ident).write(self.levels, w)
        VarInt.write(self.max_players, w)
        VarInt.write(self.chunk_radius, w)
        VarInt.write(self.simulation_distance, w)
        Bool.write(self.reduced_debug_info, w)
        Bool.write(self.show_death_screen, w)
        Bool.write(self.limited_crafting, w)
        self.spawn.write(w)
        Bool.write(self.online_mode, w)
        Bool.write(self.enforces_secure_chat, w)


@dataclass
class Respawn(_Packet):
    """ClientboundRespawnPacket (play.rs:807)."""

    spawn: SpawnInfo
    keep: int

    @classmethod
    def read(cls, r: Reader) -> "Respawn":
        return cls(SpawnInfo.read(r), Byte.read(r))

    def write(self, w: Writer) -> None:
        self.spawn.write(w)
        Byte.write(self.keep, w)


# ---- рецепты (recipes.rs) ---------------------------------------------


@dataclass(frozen=True)
class HolderSet:
    """HolderSet<Item> (recipes.rs:14): тег по имени или id предметов."""

    tag: Optional[str] = None
    items: tuple = ()

    @classmethod
    def read(cls, r: Reader) -> "HolderSet":
        n = r.varint() - 1
        if n == -1:
            return cls(tag=r.string(32767))
        if n < 0:
            raise ProtocolError("[QuadRix] negative holder set size")
        if n > r.remaining():
            raise ProtocolError("[QuadRix] holder set larger than the packet")
        return cls(items=tuple(r.varint() for _ in range(n)))

    def write(self, w: Writer) -> None:
        if self.tag is not None:
            w.varint(0)
            w.string(self.tag)
            return
        w.varint(len(self.items) + 1)
        for ident in self.items:
            w.varint(ident)


@dataclass(frozen=True)
class TrimPattern:
    """TrimPattern (recipes.rs:50): id реестра или сам шаблон."""

    id: Optional[int] = None
    asset: str = ""
    description: object = None
    decal: bool = False

    @classmethod
    def read(cls, r: Reader) -> "TrimPattern":
        ident = r.varint()
        if ident == 0:
            return cls(
                None, r.string(32767), Nbt.read(r), Bool.read(r)
            )
        return cls(ident - 1)

    def write(self, w: Writer) -> None:
        if self.id is not None:
            w.varint(self.id + 1)
            return
        w.varint(0)
        w.string(self.asset)
        Nbt.write(self.description, w)
        Bool.write(self.decal, w)


_MAX_SLOT_DEPTH = 32


@dataclass(frozen=True)
class SlotDisplay:
    """SlotDisplay (recipes.rs:61): kind + аргументы (см. чтение)."""

    kind: str
    args: tuple = ()

    @classmethod
    def read(cls, r: Reader) -> "SlotDisplay":
        return cls._read_at(r, 0)

    @classmethod
    def _read_at(cls, r: Reader, depth: int) -> "SlotDisplay":
        if depth > _MAX_SLOT_DEPTH:
            raise ProtocolError("[QuadRix] slot displays nest too deep")

        def inner() -> "SlotDisplay":
            return cls._read_at(r, depth + 1)

        kind = r.varint()
        if kind == 0:
            return cls("empty")
        if kind == 1:
            return cls("any_fuel")
        if kind == 2:
            return cls("with_any_potion", (inner(),))
        if kind == 3:
            return cls("only_with_component", (inner(), r.varint()))
        if kind == 4:
            return cls("item", (r.varint(),))
        if kind == 5:
            return cls("item_stack", (_Template.read(r),))
        if kind == 6:
            return cls("tag", (HolderSet.read(r),))
        if kind == 7:
            return cls("dyed", (inner(), inner()))
        if kind == 8:
            base = inner()
            material = inner()
            pattern = TrimPattern.read(r)
            return cls("smithing_trim", (base, material, pattern))
        if kind == 9:
            return cls("with_remainder", (inner(), inner()))
        if kind == 10:
            n = r.count(r.remaining())
            return cls(
                "composite",
                (tuple(cls._read_at(r, depth + 1) for _ in range(n)),),
            )
        raise ProtocolError(f"[QuadRix] unknown slot display {kind}")

    def write(self, w: Writer) -> None:
        args = self.args
        if self.kind == "empty":
            w.varint(0)
        elif self.kind == "any_fuel":
            w.varint(1)
        elif self.kind == "with_any_potion":
            w.varint(2)
            args[0].write(w)
        elif self.kind == "only_with_component":
            w.varint(3)
            args[0].write(w)
            w.varint(args[1])
        elif self.kind == "item":
            w.varint(4)
            w.varint(args[0])
        elif self.kind == "item_stack":
            w.varint(5)
            _Template.write(args[0], w)
        elif self.kind == "tag":
            w.varint(6)
            args[0].write(w)
        elif self.kind == "dyed":
            w.varint(7)
            args[0].write(w)
            args[1].write(w)
        elif self.kind == "smithing_trim":
            w.varint(8)
            args[0].write(w)
            args[1].write(w)
            args[2].write(w)
        elif self.kind == "with_remainder":
            w.varint(9)
            args[0].write(w)
            args[1].write(w)
        else:
            w.varint(10)
            w.varint(len(args[0]))
            for display in args[0]:
                display.write(w)


@dataclass(frozen=True)
class RecipeDisplay:
    """RecipeDisplay (recipes.rs:229): kind + аргументы (см. чтение)."""

    kind: str
    args: tuple = ()

    @classmethod
    def read(cls, r: Reader) -> "RecipeDisplay":
        kind = r.varint()
        if kind == 0:
            ingredients = [SlotDisplay.read(r) for _ in range(r.count(r.remaining()))]
            return cls("shapeless", (ingredients, SlotDisplay.read(r), SlotDisplay.read(r)))
        if kind == 1:
            width = r.varint()
            height = r.varint()
            ingredients = [SlotDisplay.read(r) for _ in range(r.count(r.remaining()))]
            if width * height != len(ingredients):
                raise ProtocolError("[QuadRix] shaped display size mismatch")
            return cls(
                "shaped",
                (width, height, ingredients, SlotDisplay.read(r), SlotDisplay.read(r)),
            )
        if kind == 2:
            return cls(
                "furnace",
                (
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    VarInt.read(r),
                    Float.read(r),
                ),
            )
        if kind == 3:
            return cls(
                "stonecutter",
                (SlotDisplay.read(r), SlotDisplay.read(r), SlotDisplay.read(r)),
            )
        if kind == 4:
            return cls(
                "smithing",
                (
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                    SlotDisplay.read(r),
                ),
            )
        raise ProtocolError(f"[QuadRix] unknown recipe display {kind}")

    def write(self, w: Writer) -> None:
        args = self.args
        if self.kind == "shapeless":
            w.varint(0)
            w.varint(len(args[0]))
            for display in args[0]:
                display.write(w)
            args[1].write(w)
            args[2].write(w)
        elif self.kind == "shaped":
            w.varint(1)
            w.varint(args[0])
            w.varint(args[1])
            w.varint(len(args[2]))
            for display in args[2]:
                display.write(w)
            args[3].write(w)
            args[4].write(w)
        elif self.kind == "furnace":
            w.varint(2)
            for display in args[:4]:
                display.write(w)
            w.varint(args[4])
            w.f32(args[5])
        elif self.kind == "stonecutter":
            w.varint(3)
            for display in args:
                display.write(w)
        else:
            w.varint(4)
            for display in args:
                display.write(w)


@dataclass
class RecipeBookEntry(_Packet):
    """RecipeDisplayEntry (recipes.rs:393)."""

    id: int
    display: RecipeDisplay
    group: int
    category: int
    requirements: Optional[list[HolderSet]]
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookEntry":
        ident = VarInt.read(r)
        display = RecipeDisplay.read(r)
        group = VarInt.read(r)
        category = VarInt.read(r)
        requirements = None
        if r.bool():
            n = r.count(r.remaining())
            requirements = [HolderSet.read(r) for _ in range(n)]
        return cls(ident, display, group, category, requirements, Byte.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        self.display.write(w)
        VarInt.write(self.group, w)
        VarInt.write(self.category, w)
        Bool.write(self.requirements is not None, w)
        if self.requirements is not None:
            w.varint(len(self.requirements))
            for requirement in self.requirements:
                requirement.write(w)
        Byte.write(self.flags, w)


@dataclass
class RecipeBookAdd(_Packet):
    """ClientboundRecipeBookAddPacket (recipes.rs:408)."""

    entries: list[RecipeBookEntry]
    replace: bool

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookAdd":
        n = r.count(r.remaining())
        entries = [RecipeBookEntry.read(r) for _ in range(n)]
        return cls(entries, Bool.read(r))

    def write(self, w: Writer) -> None:
        w.varint(len(self.entries))
        for entry in self.entries:
            entry.write(w)
        Bool.write(self.replace, w)


@dataclass
class RecipeBookRemove(_Packet):
    """ClientboundRecipeBookRemovePacket (recipes.rs:470)."""

    ids: list[int]

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookRemove":
        return cls([r.varint() for _ in range(r.count(r.remaining()))])

    def write(self, w: Writer) -> None:
        w.varint(len(self.ids))
        for ident in self.ids:
            w.varint(ident)


@dataclass
class RecipeBookSettings(_Packet):
    """RecipeBookSettings (recipes.rs:489): 4 книги (open, filtering)."""

    books: list[Tuple[bool, bool]]

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookSettings":
        return cls([(Bool.read(r), Bool.read(r)) for _ in range(4)])

    def write(self, w: Writer) -> None:
        for open_, filtering in self.books:
            Bool.write(open_, w)
            Bool.write(filtering, w)


@dataclass
class RecipeBookSeenRecipe(_Packet):
    """ServerboundRecipeBookSeenRecipePacket (recipes.rs:511)."""

    recipe: int

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookSeenRecipe":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.recipe, w)


@dataclass
class RecipeBookChangeSettings(_Packet):
    """ServerboundRecipeBookChangeSettingsPacket (recipes.rs:528)."""

    book_type: int
    open: bool
    filtering: bool

    @classmethod
    def read(cls, r: Reader) -> "RecipeBookChangeSettings":
        book_type = VarInt.read(r)
        if not 0 <= book_type < 4:
            raise ProtocolError("[QuadRix] invalid recipe book type")
        return cls(book_type, Bool.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.book_type, w)
        Bool.write(self.open, w)
        Bool.write(self.filtering, w)


@dataclass
class PlaceGhostRecipe(_Packet):
    """ClientboundPlaceGhostRecipePacket (recipes.rs:555)."""

    container: int
    display: RecipeDisplay

    @classmethod
    def read(cls, r: Reader) -> "PlaceGhostRecipe":
        return cls(VarInt.read(r), RecipeDisplay.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        self.display.write(w)


@dataclass
class PlaceRecipe(_Packet):
    """ServerboundPlaceRecipePacket (recipes.rs:575)."""

    container: int
    recipe: int
    use_max: bool

    @classmethod
    def read(cls, r: Reader) -> "PlaceRecipe":
        return cls(VarInt.read(r), VarInt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.container, w)
        VarInt.write(self.recipe, w)
        Bool.write(self.use_max, w)


# ---- clientbound: диалог (play-локальный ShowDialog) ------------------


@dataclass
class ShowDialog(_Packet):
    """ClientboundShowDialogPacket (play.rs:276): Holder<Dialog>."""

    dialog: DialogHolder

    @classmethod
    def read(cls, r: Reader) -> "ShowDialog":
        return cls(DialogHolder.read(r))

    def write(self, w: Writer) -> None:
        self.dialog.write(w)


@dataclass
class MinecartStep(_Packet):
    """NewMinecartBehavior.MinecartStep (play.rs:846)."""

    position: Tuple[float, float, float]
    movement: Tuple[float, float, float]
    yaw: int
    pitch: int
    weight: float

    @classmethod
    def read(cls, r: Reader) -> "MinecartStep":
        return cls(
            Vec3d.read(r),
            Vec3d.read(r),
            Byte.read(r),
            Byte.read(r),
            Float.read(r),
        )

    def write(self, w: Writer) -> None:
        Vec3d.write(self.position, w)
        Vec3d.write(self.movement, w)
        Byte.write(self.yaw, w)
        Byte.write(self.pitch, w)
        Float.write(self.weight, w)


@dataclass
class MoveMinecartAlongTrack(_Packet):
    """ClientboundMoveMinecartPacket (play.rs:858)."""

    id: int
    steps: list[MinecartStep]

    @classmethod
    def read(cls, r: Reader) -> "MoveMinecartAlongTrack":
        return cls(VarInt.read(r), List(MinecartStep).read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        List(MinecartStep).write(self.steps, w)


@dataclass
class PostEffects(_Packet):
    """ClientboundPostEffectsPacket (play.rs:803)."""

    effects: list[str]

    @classmethod
    def read(cls, r: Reader) -> "PostEffects":
        return cls(List(Ident).read(r))

    def write(self, w: Writer) -> None:
        List(Ident).write(self.effects, w)


@dataclass
class GameTestHighlightPos(_Packet):
    """ClientboundGameTestHighlightPosPacket (play.rs:2420)."""

    absolute: Tuple[int, int, int]
    relative: Tuple[int, int, int]

    @classmethod
    def read(cls, r: Reader) -> "GameTestHighlightPos":
        return cls(Pos.read(r), Pos.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.absolute, w)
        Pos.write(self.relative, w)


@dataclass
class TestInstanceBlockStatus(_Packet):
    """ClientboundTestInstanceBlockStatus (play.rs:2425)."""

    status: object
    size: Optional[Tuple[int, int, int]]

    @classmethod
    def read(cls, r: Reader) -> "TestInstanceBlockStatus":
        return cls(Nbt.read(r), Opt(VarVec3i).read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.status, w)
        Opt(VarVec3i).write(self.size, w)


# ---- serverbound: остаток play.rs -------------------------------------


@dataclass
class AcceptTeleportation(_Packet):
    """ServerboundAcceptTeleportationPacket (play.rs:2222)."""

    id: int
    x: float
    y: float
    z: float
    yaw: float
    pitch: float

    @classmethod
    def read(cls, r: Reader) -> "AcceptTeleportation":
        return cls(
            VarInt.read(r),
            Double.read(r),
            Double.read(r),
            Double.read(r),
            Float.read(r),
            Float.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)
        Double.write(self.x, w)
        Double.write(self.y, w)
        Double.write(self.z, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)


@dataclass
class Attack(_Packet):
    """ServerboundAttackPacket (play.rs:2223)."""

    id: int

    @classmethod
    def read(cls, r: Reader) -> "Attack":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.id, w)


@dataclass
class TeleportToEntity(_Packet):
    """ServerboundTeleportToEntityPacket (play.rs:2224)."""

    uuid: int

    @classmethod
    def read(cls, r: Reader) -> "TeleportToEntity":
        return cls(Uuid.read(r))

    def write(self, w: Writer) -> None:
        Uuid.write(self.uuid, w)


@dataclass
class SpectatorAction(_Packet):
    """ServerboundSpectatorActionPacket (play.rs:2228)."""

    target: Optional[int]

    @classmethod
    def read(cls, r: Reader) -> "SpectatorAction":
        return cls(OptVarInt.read(r))

    def write(self, w: Writer) -> None:
        OptVarInt.write(self.target, w)


@dataclass
class ChangeGameMode(_Packet):
    """ServerboundChangeGameModePacket (play.rs:2232)."""

    mode: int

    @classmethod
    def read(cls, r: Reader) -> "ChangeGameMode":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.mode, w)


@dataclass
class ChangeDifficultyRequest(_Packet):
    """ServerboundChangeDifficultyPacket (play.rs:2289)."""

    difficulty: int

    @classmethod
    def read(cls, r: Reader) -> "ChangeDifficultyRequest":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.difficulty, w)


@dataclass
class LockDifficulty(_Packet):
    """ServerboundLockDifficultyPacket (play.rs:2290)."""

    locked: bool

    @classmethod
    def read(cls, r: Reader) -> "LockDifficulty":
        return cls(Bool.read(r))

    def write(self, w: Writer) -> None:
        Bool.write(self.locked, w)


@dataclass
class SetGameRule(_Packet):
    """ServerboundSetGameRulePacket (play.rs:2293)."""

    entries: list[GameRuleEntry]

    @classmethod
    def read(cls, r: Reader) -> "SetGameRule":
        return cls(List(GameRuleEntry).read(r))

    def write(self, w: Writer) -> None:
        List(GameRuleEntry).write(self.entries, w)


@dataclass
class ChunkBatchReceived(_Packet):
    """ServerboundChunkBatchReceivedPacket (play.rs:2294)."""

    chunks_per_tick: float

    @classmethod
    def read(cls, r: Reader) -> "ChunkBatchReceived":
        return cls(Float.read(r))

    def write(self, w: Writer) -> None:
        Float.write(self.chunks_per_tick, w)


@dataclass
class SeenAdvancements(_Packet):
    """ServerboundSeenAdvancementsPacket (play.rs:2331)."""

    action: int
    tab: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "SeenAdvancements":
        action = VarInt.read(r)
        return cls(action, r.string(32767) if action == 0 else None)

    def write(self, w: Writer) -> None:
        VarInt.write(self.action, w)
        if self.action == 0:
            w.string(self.tab or "")


@dataclass
class BlockEntityTagQuery(_Packet):
    """ServerboundBlockEntityTagQueryPacket (play.rs:2356)."""

    transaction: int
    pos: Tuple[int, int, int]

    @classmethod
    def read(cls, r: Reader) -> "BlockEntityTagQuery":
        return cls(VarInt.read(r), Pos.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.transaction, w)
        Pos.write(self.pos, w)


@dataclass
class EntityTagQuery(_Packet):
    """ServerboundEntityTagQueryPacket (play.rs:2361)."""

    transaction: int
    entity: int

    @classmethod
    def read(cls, r: Reader) -> "EntityTagQuery":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.transaction, w)
        VarInt.write(self.entity, w)


@dataclass
class SignUpdate(_Packet):
    """ServerboundSignUpdatePacket (play.rs:2379)."""

    pos: Tuple[int, int, int]
    lines: list[str]
    front: bool

    @classmethod
    def read(cls, r: Reader) -> "SignUpdate":
        return cls(Pos.read(r), _read_sign_lines(r), _read_sign_side(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        _write_sign_lines(self.lines, w)
        _write_sign_side(self.front, w)


@dataclass
class SetJigsawBlock(_Packet):
    """ServerboundSetJigsawBlockPacket (play.rs:2384)."""

    pos: Tuple[int, int, int]
    name: str
    target: str
    pool: str
    final_state: str
    joint: str
    selection_priority: int
    placement_priority: int

    @classmethod
    def read(cls, r: Reader) -> "SetJigsawBlock":
        return cls(
            Pos.read(r),
            Ident.read(r),
            Ident.read(r),
            Ident.read(r),
            Str.read(r),
            Str.read(r),
            VarInt.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        Ident.write(self.name, w)
        Ident.write(self.target, w)
        Ident.write(self.pool, w)
        Str.write(self.final_state, w)
        Str.write(self.joint, w)
        VarInt.write(self.selection_priority, w)
        VarInt.write(self.placement_priority, w)


@dataclass
class SetTestBlock(_Packet):
    """ServerboundSetTestBlockPacket (play.rs:2398)."""

    pos: Tuple[int, int, int]
    mode: int
    message: str

    @classmethod
    def read(cls, r: Reader) -> "SetTestBlock":
        return cls(Pos.read(r), VarInt.read(r), Str.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.mode, w)
        Str.write(self.message, w)


@dataclass
class TestInstanceBlockAction(_Packet):
    """ServerboundTestInstanceBlockActionPacket (play.rs:2415)."""

    pos: Tuple[int, int, int]
    action: int
    data: TestInstanceData

    @classmethod
    def read(cls, r: Reader) -> "TestInstanceBlockAction":
        return cls(Pos.read(r), VarInt.read(r), TestInstanceData.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.action, w)
        self.data.write(w)


@dataclass
class JigsawGenerate(_Packet):
    """ServerboundJigsawGeneratePacket (play.rs:2429)."""

    pos: Tuple[int, int, int]
    levels: int
    keep_jigsaws: bool

    @classmethod
    def read(cls, r: Reader) -> "JigsawGenerate":
        return cls(Pos.read(r), VarInt.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.levels, w)
        Bool.write(self.keep_jigsaws, w)


@dataclass
class SetCommandBlock(_Packet):
    """ServerboundSetCommandBlockPacket (play.rs:2435)."""

    pos: Tuple[int, int, int]
    command: str
    mode: int
    flags: int

    @classmethod
    def read(cls, r: Reader) -> "SetCommandBlock":
        return cls(Pos.read(r), Str.read(r), VarInt.read(r), Byte.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        Str.write(self.command, w)
        VarInt.write(self.mode, w)
        Byte.write(self.flags, w)


@dataclass
class SetCommandMinecart(_Packet):
    """ServerboundSetCommandMinecartPacket (play.rs:2440)."""

    entity: int
    command: str
    track_output: bool

    @classmethod
    def read(cls, r: Reader) -> "SetCommandMinecart":
        return cls(VarInt.read(r), Str.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.entity, w)
        Str.write(self.command, w)
        Bool.write(self.track_output, w)


@dataclass
class SetStructureBlock(_Packet):
    """ServerboundSetStructureBlockPacket (play.rs:2446)."""

    pos: Tuple[int, int, int]
    update_type: int
    mode: int
    name: str
    offset: Tuple[int, int, int]
    size: Tuple[int, int, int]
    mirror: int
    rotation: int
    data: str
    ignore_entities: bool
    strict: bool
    show_air: bool
    show_bounding_box: bool
    integrity: float
    seed: int

    @classmethod
    def read(cls, r: Reader) -> "SetStructureBlock":
        pos = Pos.read(r)
        update_type = VarInt.read(r)
        mode = VarInt.read(r)
        name = r.string(32767)
        offset = tuple(max(-48, min(48, r.i8())) for _ in range(3))
        size = tuple(max(0, min(48, r.i8())) for _ in range(3))
        mirror = VarInt.read(r)
        rotation = VarInt.read(r)
        data = r.string(128)
        integrity = max(0.0, min(1.0, Float.read(r)))
        seed = VarLong.read(r)
        flags = Byte.read(r)
        return cls(
            pos,
            update_type,
            mode,
            name,
            offset,
            size,
            mirror,
            rotation,
            data,
            flags & 1 != 0,
            flags & 8 != 0,
            flags & 2 != 0,
            flags & 4 != 0,
            integrity,
            seed,
        )

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        VarInt.write(self.update_type, w)
        VarInt.write(self.mode, w)
        w.string(self.name)
        for value in self.offset:
            w.i8(value)
        for value in self.size:
            w.i8(value)
        VarInt.write(self.mirror, w)
        VarInt.write(self.rotation, w)
        w.string(self.data)
        Float.write(self.integrity, w)
        VarLong.write(self.seed, w)
        flags = 0
        if self.ignore_entities:
            flags |= 1
        if self.show_air:
            flags |= 2
        if self.show_bounding_box:
            flags |= 4
        if self.strict:
            flags |= 8
        Byte.write(flags, w)


@dataclass
class SetBeacon(_Packet):
    """ServerboundSetBeaconPacket (play.rs:2595)."""

    primary: Optional[int]
    secondary: Optional[int]

    @classmethod
    def read(cls, r: Reader) -> "SetBeacon":
        return cls(OptVarInt.read(r), OptVarInt.read(r))

    def write(self, w: Writer) -> None:
        OptVarInt.write(self.primary, w)
        OptVarInt.write(self.secondary, w)


@dataclass
class PickItemFromBlock(_Packet):
    """ServerboundPickItemFromBlockPacket (play.rs:2614)."""

    pos: Tuple[int, int, int]
    include_data: bool

    @classmethod
    def read(cls, r: Reader) -> "PickItemFromBlock":
        return cls(Pos.read(r), Bool.read(r))

    def write(self, w: Writer) -> None:
        Pos.write(self.pos, w)
        Bool.write(self.include_data, w)


@dataclass
class SelectBundleItem(_Packet):
    """ServerboundSelectBundleItemPacket (play.rs:2634)."""

    slot: int
    index: int

    @classmethod
    def read(cls, r: Reader) -> "SelectBundleItem":
        return cls(VarInt.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.slot, w)
        VarInt.write(self.index, w)


@dataclass
class UseItem(_Packet):
    """ServerboundUseItemPacket (play.rs:2638)."""

    hand: int
    sequence: int
    yaw: float
    pitch: float

    @classmethod
    def read(cls, r: Reader) -> "UseItem":
        return cls(
            VarInt.read(r), VarInt.read(r), Float.read(r), Float.read(r)
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.hand, w)
        VarInt.write(self.sequence, w)
        Float.write(self.yaw, w)
        Float.write(self.pitch, w)


@dataclass
class UseItemOn(_Packet):
    """ServerboundUseItemOnPacket (play.rs:2639)."""

    hand: int
    pos: Tuple[int, int, int]
    face: int
    cursor: Tuple[float, float, float]
    inside: bool
    world_border: bool
    sequence: int

    @classmethod
    def read(cls, r: Reader) -> "UseItemOn":
        return cls(
            VarInt.read(r),
            Pos.read(r),
            VarInt.read(r),
            (Float.read(r), Float.read(r), Float.read(r)),
            Bool.read(r),
            Bool.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.hand, w)
        Pos.write(self.pos, w)
        VarInt.write(self.face, w)
        for value in self.cursor:
            Float.write(value, w)
        Bool.write(self.inside, w)
        Bool.write(self.world_border, w)
        VarInt.write(self.sequence, w)


class ConfigurationAcknowledged(Empty):
    """ServerboundConfigurationAcknowledgedPacket (пустой payload)."""


class Punch(Empty):
    """ServerboundPunchPacket (пустой payload)."""


# ---- id, которые Rust не моделирует: raw passthrough ------------------

DebugBlockValue = _raw_packet("debug/block_value")
DebugChunkValue = _raw_packet("debug/chunk_value")
DebugEntityValue = _raw_packet("debug/entity_value")
DebugEvent = _raw_packet("debug/event")
DebugSample = _raw_packet("debug_sample")
PlayerCombatEnd = _raw_packet("player_combat_end")
PlayerCombatEnter = _raw_packet("player_combat_enter")
UpdateRecipes = _raw_packet("update_recipes")
CustomReportDetails = _raw_packet("custom_report_details")
DebugSubscriptionRequest = _raw_packet("debug_subscription_request")


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
    # PART 3: entity/player sync
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
    # PART 4: чат, заголовки и команды
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
    # PART 5: контейнеры и слоты
    "container_close": ContainerClose,
    "container_set_content": ContainerSetContent,
    "container_set_data": ContainerSetData,
    "container_set_slot": ContainerSetSlot,
    "merchant_offers": MerchantOffers,
    "open_screen": OpenScreen,
    "set_cursor_item": SetCursorItem,
    "set_player_inventory": SetPlayerInventory,
    "cooldown": Cooldown,
    # PART 6: мир, чанки, свет, границы, погода и рецепты
    "add_transient_block": AddTransientBlock,
    "award_stats": AwardStats,
    "block_changed_ack": BlockChangedAck,
    "block_destruction": BlockDestruction,
    "block_entity_data": BlockEntityData,
    "block_event": BlockEvent,
    "block_update": BlockUpdate,
    "boss_event": BossEvent,
    "change_difficulty": ChangeDifficulty,
    "chunk_batch_finished": ChunkBatchFinished,
    "chunk_batch_start": ChunkBatchStart,
    "chunks_biomes": ChunksBiomes,
    "clear_dialog": ClearDialog,
    "cookie_request": CookieRequest,
    "custom_payload": CustomPayload,
    "explode": Explode,
    "forget_level_chunk": ForgetLevelChunk,
    "game_rule_values": GameRuleValues,
    "game_test_highlight_pos": GameTestHighlightPos,
    "initialize_border": InitializeBorder,
    "level_chunk_with_light": LevelChunkWithLight,
    "level_event": LevelEvent,
    "level_particles": LevelParticles,
    "light_update": LightUpdate,
    "login": Login,
    "low_disk_space_warning": LowDiskSpaceWarning,
    "map_item_data": MapItemData,
    "mount_screen_open": MountScreenOpen,
    "move_minecart_along_track": MoveMinecartAlongTrack,
    "open_book": OpenBook,
    "open_sign_editor": OpenSignEditor,
    "ping": ConfigurationPing,
    "place_ghost_recipe": PlaceGhostRecipe,
    "player_combat_kill": PlayerCombatKill,
    "pong_response": StatusPing,
    "post_effects": PostEffects,
    "recipe_book_add": RecipeBookAdd,
    "recipe_book_remove": RecipeBookRemove,
    "recipe_book_settings": RecipeBookSettings,
    "remove_mob_effect": RemoveMobEffect,
    "resource_pack_pop": ResourcePackPop,
    "resource_pack_push": ResourcePackPush,
    "respawn": Respawn,
    "section_blocks_update": SectionBlocksUpdate,
    "select_advancements_tab": SelectAdvancementsTab,
    "server_links": ServerLinks,
    "set_border_center": SetBorderCenter,
    "set_border_lerp_size": SetBorderLerpSize,
    "set_border_size": SetBorderSize,
    "set_border_warning_delay": SetBorderWarningDelay,
    "set_border_warning_distance": SetBorderWarningDistance,
    "set_chunk_cache_radius": SetChunkCacheRadius,
    "set_default_spawn_position": SetDefaultSpawnPosition,
    "set_display_objective": SetDisplayObjective,
    "set_experience": SetExperience,
    "set_objective": SetObjective,
    "set_simulation_distance": SetSimulationDistance,
    "show_dialog": ShowDialog,
    "sound": Sound,
    "sound_entity": SoundEntity,
    "start_configuration": StartConfiguration,
    "stop_sound": StopSound,
    "store_cookie": StoreCookie,
    "tag_query": TagQuery,
    "test_instance_block_status": TestInstanceBlockStatus,
    "transfer": Transfer,
    "update_advancements": UpdateAdvancements,
    "update_mob_effect": UpdateMobEffect,
    "update_tags": UpdateTags,
    "waypoint": TrackedWaypoint,
    # raw passthrough: ID, которые Rust не моделирует (Unknown)
    "custom_report_details": CustomReportDetails,
    "debug/block_value": DebugBlockValue,
    "debug/chunk_value": DebugChunkValue,
    "debug/entity_value": DebugEntityValue,
    "debug/event": DebugEvent,
    "debug_sample": DebugSample,
    "player_combat_end": PlayerCombatEnd,
    "player_combat_enter": PlayerCombatEnter,
    "update_recipes": UpdateRecipes,
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
    # PART 3: взаимодействие с сущностями
    "interact": Interact,
    "paddle_boat": PaddleBoat,
    "client_command": ClientCommand,
    "pick_item_from_entity": PickItemFromEntity,
    "move_vehicle": MoveVehicleRequest,
    # PART 4: чат и команды
    "chat": Chat,
    "chat_command": ChatCommand,
    "chat_ack": ChatAck,
    "chat_command_signed": ChatCommandSigned,
    "chat_session_update": ChatSessionUpdate,
    "command_suggestion": CommandSuggestion,
    # PART 5: клики и правки слотов
    "container_button_click": ContainerButtonClick,
    "container_click": ContainerClick,
    "container_close": ContainerClose,
    "container_slot_state_changed": ContainerSlotStateChanged,
    "edit_book": EditBook,
    "rename_item": RenameItem,
    "set_creative_mode_slot": SetCreativeModeSlot,
    "select_trade": SelectTrade,
    # PART 6: остаток serverbound play.rs
    "accept_teleportation": AcceptTeleportation,
    "attack": Attack,
    "block_entity_tag_query": BlockEntityTagQuery,
    "bundle_item_selected": SelectBundleItem,
    "change_difficulty": ChangeDifficultyRequest,
    "change_game_mode": ChangeGameMode,
    "chunk_batch_received": ChunkBatchReceived,
    "client_information": ClientInformation,
    "configuration_acknowledged": ConfigurationAcknowledged,
    "cookie_response": CookieResponse,
    "custom_click_action": CustomClickAction,
    "custom_payload": CustomPayload,
    "entity_tag_query": EntityTagQuery,
    "jigsaw_generate": JigsawGenerate,
    "lock_difficulty": LockDifficulty,
    "pick_item_from_block": PickItemFromBlock,
    "ping_request": StatusPing,
    "place_recipe": PlaceRecipe,
    "pong": ConfigurationPing,
    "punch": Punch,
    "recipe_book_change_settings": RecipeBookChangeSettings,
    "recipe_book_seen_recipe": RecipeBookSeenRecipe,
    "resource_pack": ResourcePackResponse,
    "seen_advancements": SeenAdvancements,
    "set_beacon": SetBeacon,
    "set_command_block": SetCommandBlock,
    "set_command_minecart": SetCommandMinecart,
    "set_game_rule": SetGameRule,
    "set_jigsaw_block": SetJigsawBlock,
    "set_structure_block": SetStructureBlock,
    "set_test_block": SetTestBlock,
    "sign_update": SignUpdate,
    "spectator_action": SpectatorAction,
    "teleport_to_entity": TeleportToEntity,
    "test_instance_block_action": TestInstanceBlockAction,
    "use_item": UseItem,
    "use_item_on": UseItemOn,
    # raw passthrough: ID, которые Rust не моделирует
    "debug_subscription_request": DebugSubscriptionRequest,
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
