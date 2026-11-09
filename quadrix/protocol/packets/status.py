# Порт horizon-protocol/src/packets/status.rs.
#
# Состояние Status — server list ping:
#   Clientbound: StatusResponse (json-строка) и PongResponse (long);
#   Serverbound: StatusRequest (пустой) и PingRequest (long).
#
# В Rust у PongResponse и PingRequest один общий тип Ping, поэтому здесь
# Ping один, а PingResponse / PingRequest — его псевдонимы. Имя варианта
# (PongResponse или PingRequest) зависит от направления, а не от класса.
#
# Сознательно НЕ портируется:
#   * configuration.rs — следующая сессия;
#   * play.rs         — PART 1 после configuration.

from __future__ import annotations

from dataclasses import dataclass

from quadrix.protocol.buf import Long, Reader, Str, Writer
from quadrix.protocol.ids import Direction, State
from quadrix.protocol.packets.handshake import Empty, _Packet, _PacketSet

__all__ = [
    "StatusResponse",
    "Ping",
    "PingRequest",
    "PingResponse",
    "StatusRequest",
    "Clientbound",
    "Serverbound",
]


# ── Пакеты (status.rs:8-9) ────────────────────────────────────────────


@dataclass
class StatusResponse(_Packet):
    """Статус сервера: JSON-строка (Str, до 32767 символов)."""

    json: str

    @classmethod
    def read(cls, r: Reader) -> "StatusResponse":
        return cls(Str.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.json, w)


@dataclass
class Ping(_Packet):
    """Ping / Pong: 64-битное время в миллисекундах."""

    time: int

    @classmethod
    def read(cls, r: Reader) -> "Ping":
        return cls(Long.read(r))

    def write(self, w: Writer) -> None:
        Long.write(self.time, w)


#: Имена из задания; в Rust это варианты PongResponse / PingRequest.
PingResponse = Ping
PingRequest = Ping
#: Имя из задания; в Rust это вариант StatusRequest(Empty).
StatusRequest = Empty


# ── Направления (status.rs:11-18) ─────────────────────────────────────


class Clientbound(_PacketSet):
    """status::Clientbound: StatusResponse и PongResponse."""

    _STATE = State.STATUS
    _DIRECTION = Direction.CLIENTBOUND
    _ENTRIES = (
        ("StatusResponse", "status_response", StatusResponse),
        ("PongResponse", "pong_response", Ping),
    )


class Serverbound(_PacketSet):
    """status::Serverbound: StatusRequest и PingRequest."""

    _STATE = State.STATUS
    _DIRECTION = Direction.SERVERBOUND
    _ENTRIES = (
        ("StatusRequest", "status_request", Empty),
        ("PingRequest", "ping_request", Ping),
    )
