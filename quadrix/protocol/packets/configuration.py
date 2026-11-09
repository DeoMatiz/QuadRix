# Порт horizon-protocol/src/packets/configuration.rs.
#
# Состояние Configuration: синхронизация реестров и тегов, known packs,
# feature flags, resource packs и общие пакеты (keep-alive, ping,
# custom payload, server links, диалоги).
#
# Clientbound (configuration.rs:123-143):
#   CookieRequest, CustomPayload, Disconnect, FinishConfiguration,
#   KeepAlive, Ping, ResetChat, RegistryData, ResourcePackPop,
#   ResourcePackPush, StoreCookie, Transfer, UpdateEnabledFeatures,
#   UpdateTags, SelectKnownPacks, ClearDialog, ServerLinks, ShowDialog,
#   CodeOfConduct.
# Serverbound (configuration.rs:211-222):
#   ClientInformation, CookieResponse, CustomPayload, FinishConfiguration,
#   KeepAlive, Pong, ResourcePack(ResourcePackResponse), SelectKnownPacks,
#   AcceptCodeOfConduct, CustomClickAction.
#
# Имена и поля взяты из Rust дословно. В частности:
#   * CustomPayload        — не PluginMessage;
#   * ResourcePackPop/Push — не Remove/AddResourcePack;
#   * UpdateEnabledFeatures — не FeatureFlags;
#   * SelectKnownPacks     — не KnownPacks;
#   * Pong использует ту же структуру Ping { id: i32 };
#   * TagEntry.ids         — List<VarInt>, а не long array;
#   * ClientInformation    — chat_colors/model_customisation, не
#     allow_text_colors/skin_parts.
#
# Сознательно НЕ портируется:
#   * play.rs — PART 1 (следующая сессия);
#   * crypto.rs — отдельная задача.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from quadrix.protocol.buf import (
    Bool,
    Byte,
    Bytes,
    Ident,
    Int,
    List,
    Long,
    Nbt,
    Opt,
    Reader,
    Str,
    StrN,
    UByte,
    Uuid,
    VarInt,
    Writer,
)
from quadrix.protocol.ids import Direction, State
from quadrix.protocol.packets.handshake import Empty, _Packet, _PacketSet
from quadrix.world.nbt import Tag, TagType

__all__ = [
    # общие кодеки
    "RegistryEntry",
    "TagEntry",
    "RegistryTags",
    "KnownPack",
    "Known",
    "Custom",
    "ServerLinkKind",
    "ServerLink",
    "ClickPayload",
    # Clientbound
    "CookieRequest",
    "CustomPayload",
    "Disconnect",
    "FinishConfiguration",
    "KeepAlive",
    "Ping",
    "ResetChat",
    "RegistryData",
    "ResourcePackPop",
    "ResourcePackPush",
    "StoreCookie",
    "Transfer",
    "UpdateEnabledFeatures",
    "UpdateTags",
    "SelectKnownPacks",
    "ClearDialog",
    "ServerLinks",
    "ShowDialog",
    "CodeOfConduct",
    # Serverbound
    "ClientInformation",
    "CookieResponse",
    "Pong",
    "ResourcePackResponse",
    "AcceptCodeOfConduct",
    "CustomClickAction",
    # направления
    "Clientbound",
    "Serverbound",
    # имена из задания (Rust называет структуры иначе)
    "PluginMessage",
    "RemoveResourcePack",
    "AddResourcePack",
    "FeatureFlags",
    "KnownPacks",
    "AcknowledgeFinishConfiguration",
]

# Кодеки с фиксированными лимитами полей (buf.rs).
_HASH = StrN(40)


# ── Общие кодеки configuration.rs:14-47 ──────────────────────────────


@dataclass
class CookieRequest(_Packet):
    """CookieRequest: ключ cookie (Identifier)."""

    key: str

    @classmethod
    def read(cls, r: Reader) -> "CookieRequest":
        return cls(Ident.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.key, w)


@dataclass
class CustomPayload(_Packet):
    """CustomPayload: канал (Identifier) и сырые данные."""

    channel: str
    data: bytes

    @classmethod
    def read(cls, r: Reader) -> "CustomPayload":
        return cls(Ident.read(r), r.rest())

    def write(self, w: Writer) -> None:
        Ident.write(self.channel, w)
        w.bytes(self.data)


@dataclass
class Disconnect(_Packet):
    """Common disconnect: причина — chat component в NBT."""

    reason: Tag

    @classmethod
    def read(cls, r: Reader) -> "Disconnect":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.reason, w)


@dataclass
class KeepAlive(_Packet):
    """KeepAlive: идентификатор long."""

    id: int

    @classmethod
    def read(cls, r: Reader) -> "KeepAlive":
        return cls(Long.read(r))

    def write(self, w: Writer) -> None:
        Long.write(self.id, w)


@dataclass
class Ping(_Packet):
    """Ping (и Serverbound Pong): идентификатор int."""

    id: int

    @classmethod
    def read(cls, r: Reader) -> "Ping":
        return cls(Int.read(r))

    def write(self, w: Writer) -> None:
        Int.write(self.id, w)


@dataclass
class RegistryEntry(_Packet):
    """PackedRegistryEntry: data отсутствует, если запись есть в known pack."""

    id: str
    data: Optional[Tag]

    @classmethod
    def read(cls, r: Reader) -> "RegistryEntry":
        return cls(Ident.read(r), Opt(Nbt).read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.id, w)
        Opt(Nbt).write(self.data, w)


@dataclass
class RegistryData(_Packet):
    """RegistryData: реестр и его записи."""

    registry: str
    entries: list[RegistryEntry]

    @classmethod
    def read(cls, r: Reader) -> "RegistryData":
        return cls(Ident.read(r), List(RegistryEntry).read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.registry, w)
        List(RegistryEntry).write(self.entries, w)


@dataclass
class ResourcePackPop(_Packet):
    """ResourcePackPop: UUID или None (снять все паки)."""

    id: Optional[int]

    @classmethod
    def read(cls, r: Reader) -> "ResourcePackPop":
        return cls(Opt(Uuid).read(r))

    def write(self, w: Writer) -> None:
        Opt(Uuid).write(self.id, w)


@dataclass
class ResourcePackPush(_Packet):
    """ResourcePackPush: id, url, hash, required и необязательный prompt."""

    id: int
    url: str
    hash: str
    required: bool
    prompt: Optional[Tag]

    @classmethod
    def read(cls, r: Reader) -> "ResourcePackPush":
        return cls(
            Uuid.read(r),
            Str.read(r),
            _HASH.read(r),
            Bool.read(r),
            Opt(Nbt).read(r),
        )

    def write(self, w: Writer) -> None:
        Uuid.write(self.id, w)
        Str.write(self.url, w)
        _HASH.write(self.hash, w)
        Bool.write(self.required, w)
        Opt(Nbt).write(self.prompt, w)


@dataclass
class StoreCookie(_Packet):
    """StoreCookie: ключ cookie и payload (VarInt-префикс + байты)."""

    key: str
    payload: bytes

    @classmethod
    def read(cls, r: Reader) -> "StoreCookie":
        return cls(Ident.read(r), Bytes.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.key, w)
        Bytes.write(self.payload, w)


@dataclass
class Transfer(_Packet):
    """Transfer: хост и порт (VarInt)."""

    host: str
    port: int

    @classmethod
    def read(cls, r: Reader) -> "Transfer":
        return cls(Str.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.host, w)
        VarInt.write(self.port, w)


@dataclass
class UpdateEnabledFeatures(_Packet):
    """UpdateEnabledFeatures: список Identifier."""

    features: list[str]

    @classmethod
    def read(cls, r: Reader) -> "UpdateEnabledFeatures":
        return cls(List(Ident).read(r))

    def write(self, w: Writer) -> None:
        List(Ident).write(self.features, w)


@dataclass
class TagEntry(_Packet):
    """TagEntry: имя тега и ids (List<VarInt>)."""

    name: str
    ids: list[int]

    @classmethod
    def read(cls, r: Reader) -> "TagEntry":
        return cls(Ident.read(r), List(VarInt).read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.name, w)
        List(VarInt).write(self.ids, w)


@dataclass
class RegistryTags(_Packet):
    """RegistryTags: реестр и его теги."""

    registry: str
    tags: list[TagEntry]

    @classmethod
    def read(cls, r: Reader) -> "RegistryTags":
        return cls(Ident.read(r), List(TagEntry).read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.registry, w)
        List(TagEntry).write(self.tags, w)


@dataclass
class UpdateTags(_Packet):
    """ClientboundUpdateTagsPacket: теги по реестрам."""

    registries: list[RegistryTags]

    @classmethod
    def read(cls, r: Reader) -> "UpdateTags":
        return cls(List(RegistryTags).read(r))

    def write(self, w: Writer) -> None:
        List(RegistryTags).write(self.registries, w)


@dataclass
class KnownPack(_Packet):
    """KnownPack: namespace, id и version (все Str)."""

    namespace: str
    id: str
    version: str

    @classmethod
    def read(cls, r: Reader) -> "KnownPack":
        return cls(Str.read(r), Str.read(r), Str.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.namespace, w)
        Str.write(self.id, w)
        Str.write(self.version, w)


@dataclass
class SelectKnownPacks(_Packet):
    """SelectKnownPacks: список known packs."""

    packs: list[KnownPack]

    @classmethod
    def read(cls, r: Reader) -> "SelectKnownPacks":
        return cls(List(KnownPack).read(r))

    def write(self, w: Writer) -> None:
        List(KnownPack).write(self.packs, w)


@dataclass
class CodeOfConduct(_Packet):
    """CodeOfConduct: текст правил."""

    text: str

    @classmethod
    def read(cls, r: Reader) -> "CodeOfConduct":
        return cls(Str.read(r))

    def write(self, w: Writer) -> None:
        Str.write(self.text, w)


# ── ServerLinks (configuration.rs:51-95) ─────────────────────────────


@dataclass
class Known(_Packet):
    """ServerLinkKind::Known(i32) — id известной ссылки."""

    id: int


@dataclass
class Custom(_Packet):
    """ServerLinkKind::Custom(Tag) — собственная подпись в NBT."""

    tag: Tag


#: Rust ServerLinkKind { Known(i32), Custom(Tag) }.
ServerLinkKind = Union[Known, Custom]


@dataclass
class ServerLink(_Packet):
    """UntrustedEntry: вид ссылки и необработанная строка link."""

    kind: ServerLinkKind
    link: str

    @classmethod
    def read(cls, r: Reader) -> "ServerLink":
        if Bool.read(r):
            kind: ServerLinkKind = Known(VarInt.read(r))
        else:
            kind = Custom(Nbt.read(r))
        return cls(kind, Str.read(r))

    def write(self, w: Writer) -> None:
        if isinstance(self.kind, Known):
            Bool.write(True, w)
            VarInt.write(self.kind.id, w)
        else:
            Bool.write(False, w)
            Nbt.write(self.kind.tag, w)
        Str.write(self.link, w)


@dataclass
class ServerLinks(_Packet):
    """ClientboundServerLinksPacket: ссылки для меню паузы."""

    links: list[ServerLink]

    @classmethod
    def read(cls, r: Reader) -> "ServerLinks":
        return cls(List(ServerLink).read(r))

    def write(self, w: Writer) -> None:
        List(ServerLink).write(self.links, w)


@dataclass
class ShowDialog(_Packet):
    """ClientboundShowDialogPacket: диалог как NBT."""

    dialog: Tag

    @classmethod
    def read(cls, r: Reader) -> "ShowDialog":
        return cls(Nbt.read(r))

    def write(self, w: Writer) -> None:
        Nbt.write(self.dialog, w)


# ── CustomClickAction (configuration.rs:101-121) ─────────────────────


class ClickPayload:
    """ServerboundCustomClickActionPacket.UNTRUSTED_TAG_CODEC.

    Необязательный tag за VarInt-длиной (не больше 65536 байт); при
    отсутствии пишется одиночный End.
    """

    MAX_BYTES: int = 65536

    @classmethod
    def read(cls, r: Reader) -> Optional[Tag]:
        n = r.count(cls.MAX_BYTES)
        tag = Reader(r.bytes(n)).nbt()
        return None if tag.is_end else tag

    @classmethod
    def write(cls, v: Optional[Tag], w: Writer) -> None:
        payload = Writer()
        payload.nbt(v if v is not None else Tag(TagType.End, is_end=True))
        w.varint(len(payload.data))
        w.bytes(payload.data)


@dataclass
class CustomClickAction(_Packet):
    """ServerboundCustomClickActionPacket: id и необязательный payload."""

    id: str
    payload: Optional[Tag]

    @classmethod
    def read(cls, r: Reader) -> "CustomClickAction":
        return cls(Ident.read(r), ClickPayload.read(r))

    def write(self, w: Writer) -> None:
        Ident.write(self.id, w)
        ClickPayload.write(self.payload, w)


# ── Пустые пакеты (packets::Empty с разными вариантами) ──────────────
#
# packet_enum! различает варианты по имени, хотя у всех payload Empty.
# Python-таблица направлений различает пакеты по классу, поэтому каждому
# пустому варианту нужен свой подкласс Empty, иначе encode выбрал бы
# последний зарегистрированный id.


class FinishConfiguration(Empty):
    """Clientbound/Serverbound FinishConfiguration (пустой payload)."""


class ResetChat(Empty):
    """ClientboundResetChat (пустой payload)."""


class ClearDialog(Empty):
    """ClientboundClearDialog (пустой payload)."""


class AcceptCodeOfConduct(Empty):
    """ServerboundAcceptCodeOfConduct (пустой payload)."""


# ── Serverbound (configuration.rs:145-209) ───────────────────────────


@dataclass
class ClientInformation(_Packet):
    """ClientInformation: настройки клиента (все поля как в Rust)."""

    language: str
    view_distance: int
    chat_visibility: int
    chat_colors: bool
    model_customisation: int
    main_hand: int
    text_filtering: bool
    allows_listing: bool
    particle_status: int

    def __post_init__(self) -> None:
        # i8 view_distance, как Byte в Rust: приводим к знаковому байту.
        self.view_distance = ((int(self.view_distance) + 128) % 256) - 128
        # u8 model_customisation, как UByte в Rust.
        self.model_customisation = int(self.model_customisation) & 0xFF

    @classmethod
    def new(cls, view_distance: int) -> "ClientInformation":
        """ClientInformation.createDefault с заданной view distance."""
        return cls(
            language="en_us",
            view_distance=view_distance,
            chat_visibility=0,
            chat_colors=True,
            model_customisation=0x7F,
            main_hand=1,
            text_filtering=False,
            allows_listing=True,
            particle_status=0,
        )

    @classmethod
    def read(cls, r: Reader) -> "ClientInformation":
        return cls(
            StrN(16).read(r),
            Byte.read(r),
            VarInt.read(r),
            Bool.read(r),
            UByte.read(r),
            VarInt.read(r),
            Bool.read(r),
            Bool.read(r),
            VarInt.read(r),
        )

    def write(self, w: Writer) -> None:
        w.string(self.language)
        w.i8(self.view_distance)
        w.varint(self.chat_visibility)
        w.bool(self.chat_colors)
        w.u8(self.model_customisation)
        w.varint(self.main_hand)
        w.bool(self.text_filtering)
        w.bool(self.allows_listing)
        w.varint(self.particle_status)


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


@dataclass
class ResourcePackResponse(_Packet):
    """ServerboundResourcePackPacket.Action: UUID и VarInt-код действия."""

    id: int
    action: int

    @classmethod
    def read(cls, r: Reader) -> "ResourcePackResponse":
        return cls(Uuid.read(r), VarInt.read(r))

    def write(self, w: Writer) -> None:
        Uuid.write(self.id, w)
        VarInt.write(self.action, w)


# Pong использует ту же структуру Ping { id: i32 }.
Pong = Ping


# ── Направления (configuration.rs:123-222) ───────────────────────────


class Clientbound(_PacketSet):
    """configuration::Clientbound."""

    _STATE = State.CONFIGURATION
    _DIRECTION = Direction.CLIENTBOUND
    _ENTRIES = (
        ("CookieRequest", "cookie_request", CookieRequest),
        ("CustomPayload", "custom_payload", CustomPayload),
        ("Disconnect", "disconnect", Disconnect),
        ("FinishConfiguration", "finish_configuration", FinishConfiguration),
        ("KeepAlive", "keep_alive", KeepAlive),
        ("Ping", "ping", Ping),
        ("ResetChat", "reset_chat", ResetChat),
        ("RegistryData", "registry_data", RegistryData),
        ("ResourcePackPop", "resource_pack_pop", ResourcePackPop),
        ("ResourcePackPush", "resource_pack_push", ResourcePackPush),
        ("StoreCookie", "store_cookie", StoreCookie),
        ("Transfer", "transfer", Transfer),
        ("UpdateEnabledFeatures", "update_enabled_features", UpdateEnabledFeatures),
        ("UpdateTags", "update_tags", UpdateTags),
        ("SelectKnownPacks", "select_known_packs", SelectKnownPacks),
        ("ClearDialog", "clear_dialog", ClearDialog),
        ("ServerLinks", "server_links", ServerLinks),
        ("ShowDialog", "show_dialog", ShowDialog),
        ("CodeOfConduct", "code_of_conduct", CodeOfConduct),
    )


class Serverbound(_PacketSet):
    """configuration::Serverbound."""

    _STATE = State.CONFIGURATION
    _DIRECTION = Direction.SERVERBOUND
    _ENTRIES = (
        ("ClientInformation", "client_information", ClientInformation),
        ("CookieResponse", "cookie_response", CookieResponse),
        ("CustomPayload", "custom_payload", CustomPayload),
        ("FinishConfiguration", "finish_configuration", FinishConfiguration),
        ("KeepAlive", "keep_alive", KeepAlive),
        ("Pong", "pong", Ping),
        ("ResourcePack", "resource_pack", ResourcePackResponse),
        ("SelectKnownPacks", "select_known_packs", SelectKnownPacks),
        ("AcceptCodeOfConduct", "accept_code_of_conduct", AcceptCodeOfConduct),
        ("CustomClickAction", "custom_click_action", CustomClickAction),
    )


# ── Имена из задания (Rust называет структуры иначе) ──────────────────

PluginMessage = CustomPayload
RemoveResourcePack = ResourcePackPop
AddResourcePack = ResourcePackPush
FeatureFlags = UpdateEnabledFeatures
KnownPacks = SelectKnownPacks
AcknowledgeFinishConfiguration = FinishConfiguration
