# Порт horizon-protocol/src/packets/handshake.rs (+ общие части
# packets/mod.rs: Empty и сгенерированный packet_enum!).
#
# Состояние Handshake — единственный пакет ClientIntention:
#   протокол (VarInt), адрес сервера (строка ≤ 255), порт (u16),
#   намерение (VarInt: 1 = status, 2 = login, 3 = transfer).
#
# Здесь же лежат два общих примитива из packets/mod.rs, на которые
# ссылаются status.rs и login.rs: Empty и Unknown.
#
# Сознательно НЕ портируется:
#   * configuration.rs — следующая сессия;
#   * play.rs         — PART 1 после configuration;
#   * crypto.rs       — отдельная задача.

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Type

from quadrix.protocol.buf import (
    ProtocolError,
    Reader,
    StrN,
    UShort,
    VarInt,
    Writer,
)
from quadrix.protocol.ids import Direction, State, id_of

__all__ = [
    "STATUS",
    "LOGIN",
    "TRANSFER",
    "Empty",
    "Unknown",
    "Intention",
    "HandshakePacket",
    "Serverbound",
]

# handshake.rs:8-10 — ClientIntent ids.
STATUS: int = 1
LOGIN: int = 2
TRANSFER: int = 3

# Кодеки полей (buf.rs: StrN<255>, UShort, VarInt).
_HOST = StrN(255)


# ── Общие примитивы packets/mod.rs ────────────────────────────────────


class _Packet:
    """Общая часть packet!: encode() тела и decode() с проверкой остатка."""

    def encode(self) -> bytes:
        """Тело пакета без VarInt-id (как Codec::write у packet!)."""
        w = Writer()
        self.write(w)
        return bytes(w.data)

    @classmethod
    def decode(cls, data: bytes | bytearray | memoryview):
        """Прочитать тело пакета и отвергнуть лишние байты."""
        r = Reader(data)
        packet = cls.read(r)
        if r.remaining() != 0:
            raise ProtocolError(
                f"packet {cls.__name__} was larger than expected: "
                f"{r.remaining()} extra bytes"
            )
        return packet


@dataclass
class Empty(_Packet):
    """Пакет без полей (packets/mod.rs:74)."""

    def write(self, w: Writer) -> None:
        return None

    @classmethod
    def read(cls, r: Reader) -> "Empty":
        return cls()


@dataclass
class Unknown:
    """Пакет, который QuadRix не моделирует: id и сырой payload.

    В Rust это вариант сгенерированного enum, а не самостоятельный
    Codec: таблица направлений создаёт его при неизвестном id и пишет
    payload как есть.
    """

    packet_id: int
    payload: bytes


# ── packet_enum! для одного (State, Direction) ────────────────────────


class _PacketSet:
    """Аналог packet_enum!: id, name, decode и encode для направления.

    Подкласс задаёт ``_STATE``, ``_DIRECTION`` и ``_ENTRIES`` — список
    троек (имя варианта, имя ID в ids.py, класс пакета). Таблица
    заполняется в ``__init_subclass__``, поэтому ID не хардкодятся.
    """

    _STATE: State = State.PLAY
    _DIRECTION: Direction = Direction.CLIENTBOUND
    _ENTRIES: Tuple[Tuple[str, str, Type[_Packet]], ...] = ()

    _BY_ID: Dict[int, Type[_Packet]]
    _NAME_BY_TYPE: Dict[Type[_Packet], str]
    _ID_BY_TYPE: Dict[Type[_Packet], int]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        cls._BY_ID = {}
        cls._NAME_BY_TYPE = {}
        cls._ID_BY_TYPE = {}
        for variant, ids_name, packet_cls in cls._ENTRIES:
            packet_id = id_of(ids_name, cls._STATE, cls._DIRECTION)
            cls._BY_ID[packet_id] = packet_cls
            cls._NAME_BY_TYPE[packet_cls] = variant
            cls._ID_BY_TYPE[packet_cls] = packet_id

    @classmethod
    def id(cls, packet: _Packet) -> int:
        """ID пакета; у Unknown — его собственный id."""
        if isinstance(packet, Unknown):
            return packet.packet_id
        try:
            return cls._ID_BY_TYPE[type(packet)]
        except KeyError:
            raise KeyError(
                f"[QuadRix] пакет {type(packet).__name__} не принадлежит "
                f"{cls.__name__} ({cls._STATE.value}/{cls._DIRECTION.value})"
            ) from None

    @classmethod
    def name(cls, packet: _Packet) -> str:
        """Имя варианта для логов (MoveVehicle, Unknown)."""
        if isinstance(packet, Unknown):
            return "Unknown"
        try:
            return cls._NAME_BY_TYPE[type(packet)]
        except KeyError:
            raise KeyError(
                f"[QuadRix] пакет {type(packet).__name__} не принадлежит "
                f"{cls.__name__} ({cls._STATE.value}/{cls._DIRECTION.value})"
            ) from None

    @classmethod
    def decode(
        cls,
        packet_id: int,
        payload: bytes | bytearray | memoryview,
        *,
        strict: bool = False,
    ) -> _Packet:
        """Разобрать тело после id (как packet_enum!::decode).

        Неизвестный id, как и в Rust, даёт ``Unknown`` с сырым payload.
        ``strict=True`` превращает это в KeyError (удобно для тестов).
        """
        packet_cls = cls._BY_ID.get(packet_id)
        if packet_cls is None:
            if strict:
                raise KeyError(
                    f"[QuadRix] нет пакета с id={packet_id} "
                    f"для {cls._STATE.value}/{cls._DIRECTION.value}"
                )
            return Unknown(packet_id, bytes(payload))
        r = Reader(payload)
        packet = packet_cls.read(r)
        if r.remaining() != 0:
            raise ProtocolError(
                f"packet {packet_id} ({cls.__name__}) was larger than "
                f"expected: {r.remaining()} extra bytes"
            )
        return packet

    @classmethod
    def encode(cls, packet: _Packet) -> bytes:
        """Тело с VarInt-id впереди (как packet_enum!::encode)."""
        w = Writer()
        w.varint(cls.id(packet))
        if isinstance(packet, Unknown):
            w.bytes(packet.payload)
        else:
            packet.write(w)
        return bytes(w.data)


# ── Intention (handshake.rs:12) ───────────────────────────────────────


@dataclass
class Intention(_Packet):
    """ClientIntention: протокол, хост, порт и следующее состояние."""

    protocol: int
    host: str
    port: int
    intent: int

    @classmethod
    def read(cls, r: Reader) -> "Intention":
        return cls(
            VarInt.read(r),
            _HOST.read(r),
            UShort.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.protocol, w)
        _HOST.write(self.host, w)
        UShort.write(self.port, w)
        VarInt.write(self.intent, w)


#: Имя из задания; в Rust структура называется Intention.
HandshakePacket = Intention


class Serverbound(_PacketSet):
    """handshake::Serverbound: Intention(Intention) = INTENTION."""

    _STATE = State.HANDSHAKE
    _DIRECTION = Direction.SERVERBOUND
    _ENTRIES = (("Intention", "intention", Intention),)
