# Порт horizon-protocol/src/packets/login.rs.
#
# Состояние Login: offline/online hello, encryption request,
# сжатие, login plugin queries и готовый профиль игрока.
#
# Clientbound (login.rs:37-44):
#   Disconnect, Hello (EncryptionRequest), LoginFinished (LoginSuccess),
#   Compression, CustomQuery, CookieRequest.
# Serverbound (login.rs:51-57):
#   Hello (LoginStart), Key (EncryptionResponse), CustomQueryAnswer,
#   LoginAcknowledged, CookieResponse.
#
# Набор и поля взяты из Rust дословно. В частности, LoginStart (ServerHello)
# содержит обязательные name + uuid (u128), а не Option<Uuid>; UUID со
# значением 0 — это offline-профиль.
#
# Сознательно НЕ портируется:
#   * crypto.rs       — отдельная задача (offline_uuid и т. п.);
#   * configuration.rs — следующая сессия;
#   * play.rs         — PART 1 после configuration.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quadrix.protocol.buf import (
    Bool,
    Bytes,
    Ident,
    List,
    Opt,
    Reader,
    Rest,
    Str,
    StrN,
    Uuid,
    VarInt,
    Writer,
)
from quadrix.protocol.ids import Direction, State
from quadrix.protocol.packets.handshake import Empty, _Packet, _PacketSet

__all__ = [
    "Property",
    "GameProfile",
    "Disconnect",
    "Hello",
    "LoginFinished",
    "Compression",
    "CustomQuery",
    "CookieRequest",
    "ServerHello",
    "Key",
    "CustomQueryAnswer",
    "CookieResponse",
    # имена из задания
    "LoginStart",
    "LoginSuccess",
    "EncryptionRequest",
    "EncryptionResponse",
    "LoginDisconnect",
    "LoginAcknowledged",
    "Clientbound",
    "Serverbound",
]


# ── Общие данные профиля (login.rs:9-24) ──────────────────────────────


@dataclass
class Property(_Packet):
    """com.mojang.authlib.properties.Property."""

    name: str
    value: str
    signature: Optional[str]

    @classmethod
    def read(cls, r: Reader) -> "Property":
        return cls(
            StrN(64).read(r),
            Str.read(r),
            Opt(StrN(1024)).read(r),
        )

    def write(self, w: Writer) -> None:
        StrN(64).write(self.name, w)
        Str.write(self.value, w)
        Opt(StrN(1024)).write(self.signature, w)


@dataclass
class GameProfile(_Packet):
    """ByteBufCodecs.GAME_PROFILE: UUID, имя и свойства."""

    uuid: int
    name: str
    properties: list[Property]

    @classmethod
    def read(cls, r: Reader) -> "GameProfile":
        return cls(
            Uuid.read(r),
            StrN(16).read(r),
            List(Property).read(r),
        )

    def write(self, w: Writer) -> None:
        Uuid.write(self.uuid, w)
        StrN(16).write(self.name, w)
        List(Property).write(self.properties, w)


# ── Clientbound (login.rs:25-35) ──────────────────────────────────────


@dataclass
class Disconnect(_Packet):
    """LoginDisconnect: причина в виде JSON (до 262144 символов)."""

    reason_json: str

    @classmethod
    def read(cls, r: Reader) -> "Disconnect":
        return cls(StrN(262144).read(r))

    def write(self, w: Writer) -> None:
        StrN(262144).write(self.reason_json, w)


@dataclass
class Hello(_Packet):
    """Clientbound EncryptionRequest (login.rs:26-31)."""

    server_id: str
    public_key: bytes
    challenge: bytes
    should_authenticate: bool

    @classmethod
    def read(cls, r: Reader) -> "Hello":
        return cls(
            StrN(20).read(r),
            Bytes.read(r),
            Bytes.read(r),
            Bool.read(r),
        )

    def write(self, w: Writer) -> None:
        StrN(20).write(self.server_id, w)
        Bytes.write(self.public_key, w)
        Bytes.write(self.challenge, w)
        Bool.write(self.should_authenticate, w)


@dataclass
class LoginFinished(_Packet):
    """LoginSuccess: профиль игрока и UUID сессии."""

    profile: GameProfile
    session: int

    @classmethod
    def read(cls, r: Reader) -> "LoginFinished":
        return cls(GameProfile.read(r), Uuid.read(r))

    def write(self, w: Writer) -> None:
        GameProfile.write(self.profile, w)
        Uuid.write(self.session, w)


@dataclass
class Compression(_Packet):
    """LoginCompression: порог сжатия VarInt."""

    threshold: int

    @classmethod
    def read(cls, r: Reader) -> "Compression":
        return cls(VarInt.read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.threshold, w)


@dataclass
class CustomQuery(_Packet):
    """Login plugin query: transaction, канал и сырые данные."""

    transaction: int
    channel: str
    data: bytes

    @classmethod
    def read(cls, r: Reader) -> "CustomQuery":
        return cls(
            VarInt.read(r),
            Ident.read(r),
            Rest.read(r),
        )

    def write(self, w: Writer) -> None:
        VarInt.write(self.transaction, w)
        Ident.write(self.channel, w)
        Rest.write(self.data, w)


@dataclass
class CookieRequest(_Packet):
    """CookieRequest: ключ cookie (Identifier)."""

    key: str

    @classmethod
    def read(cls, r: Reader) -> "CookieRequest":
        return cls(Ident.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.key, w)


# ── Serverbound (login.rs:46-49) ──────────────────────────────────────


@dataclass
class ServerHello(_Packet):
    """LoginStart: имя игрока и UUID (0 — offline-профиль)."""

    name: str
    uuid: int

    @classmethod
    def read(cls, r: Reader) -> "ServerHello":
        return cls(StrN(16).read(r), Uuid.read(r))

    def write(self, w: Writer) -> None:
        StrN(16).write(self.name, w)
        Uuid.write(self.uuid, w)


@dataclass
class Key(_Packet):
    """EncryptionResponse: зашифрованный секрет и challenge."""

    key: bytes
    challenge: bytes

    @classmethod
    def read(cls, r: Reader) -> "Key":
        return cls(Bytes.read(r), Bytes.read(r))

    def write(self, w: Writer) -> None:
        Bytes.write(self.key, w)
        Bytes.write(self.challenge, w)


@dataclass
class CustomQueryAnswer(_Packet):
    """Ответ на login plugin query; payload может отсутствовать."""

    transaction: int
    payload: Optional[bytes]

    @classmethod
    def read(cls, r: Reader) -> "CustomQueryAnswer":
        return cls(VarInt.read(r), Opt(Rest).read(r))

    def write(self, w: Writer) -> None:
        VarInt.write(self.transaction, w)
        Opt(Rest).write(self.payload, w)


@dataclass
class CookieResponse(_Packet):
    """CookieResponse: ключ cookie и необязательный payload."""

    key: str
    payload: Optional[bytes]

    @classmethod
    def read(cls, r: Reader) -> "CookieResponse":
        return cls(Ident.read(r), Opt(Bytes).read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.key, w)
        Opt(Bytes).write(self.payload, w)


# ── Имена из задания (Rust называет структуры иначе) ──────────────────

LoginStart = ServerHello
LoginSuccess = LoginFinished
EncryptionRequest = Hello
EncryptionResponse = Key
LoginDisconnect = Disconnect
LoginAcknowledged = Empty


# ── Направления (login.rs:37-57) ─────────────────────────────────────


class Clientbound(_PacketSet):
    """login::Clientbound."""

    _STATE = State.LOGIN
    _DIRECTION = Direction.CLIENTBOUND
    _ENTRIES = (
        ("Disconnect", "login_disconnect", Disconnect),
        ("Hello", "hello", Hello),
        ("LoginFinished", "login_finished", LoginFinished),
        ("Compression", "login_compression", Compression),
        ("CustomQuery", "custom_query", CustomQuery),
        ("CookieRequest", "cookie_request", CookieRequest),
    )


class Serverbound(_PacketSet):
    """login::Serverbound."""

    _STATE = State.LOGIN
    _DIRECTION = Direction.SERVERBOUND
    _ENTRIES = (
        ("Hello", "hello", ServerHello),
        ("Key", "key", Key),
        ("CustomQueryAnswer", "custom_query_answer", CustomQueryAnswer),
        ("LoginAcknowledged", "login_acknowledged", Empty),
        ("CookieResponse", "cookie_response", CookieResponse),
    )
