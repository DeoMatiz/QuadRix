# Порт horizon-protocol/src/packets/play.rs — PART 1 (framework).
#
# play.rs — самое большое состояние протокола (мир, сущности, инвентарь,
# чат, чанки). Здесь портируется только КАРКАС:
#   * полные таблицы ID clientbound и serverbound (из ids.py, как
#     packet_enum! в Rust);
#   * диспетчеризация decode/encode по ID и по типу пакета;
#   * три простых clientbound-пакета: BundleDelimiter, Disconnect,
#     KeepAlive;
#   * три простых serverbound-пакета: ClientTickEnd, KeepAlive,
#     PlayerLoaded.
#
# Остальные payload'ы сознательно НЕ портируются в PART 1. Для каждого
# такого ID создаётся отдельный класс-заглушка: его read/write сразу
# бросают именованный Unsupported("play.rs PART 2+: <packet>"). Это не
# pass и не NotImplementedError — PART 2-6 просто заменят заглушку на
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

from typing import Dict, Tuple, Type

from quadrix.protocol import ids
from quadrix.protocol.buf import ProtocolError, Reader, Writer
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


# ── Реализованные ID (3 clientbound + 3 serverbound) ─────────────────

_CLIENTBOUND_IMPLEMENTED: Dict[str, Type[_Packet]] = {
    "bundle_delimiter": BundleDelimiter,
    "disconnect": Disconnect,
    "keep_alive": KeepAlive,
}

_SERVERBOUND_IMPLEMENTED: Dict[str, Type[_Packet]] = {
    "keep_alive": KeepAlive,
    "client_tick_end": ClientTickEnd,
    "player_loaded": PlayerLoaded,
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
