#!/usr/bin/env python3
"""Тесты состояния Configuration протокола QuadRix.

Источник: horizon-protocol/src/packets/configuration.rs.

Это чистые кодеки провода: .local-файлов они не читают. Точные байты
для ClickPayload взяты из теста click_payload_is_length_prefixed.
"""

from __future__ import annotations

import pytest

from quadrix.protocol.buf import ProtocolError, Reader, Writer
from quadrix.protocol.packets.configuration import (
    AcceptCodeOfConduct,
    ClearDialog,
    ClickPayload,
    ClientInformation,
    Clientbound,
    CodeOfConduct,
    CookieResponse,
    Custom,
    CustomClickAction,
    CustomPayload,
    Disconnect,
    FinishConfiguration,
    KeepAlive,
    Known,
    KnownPack,
    Ping,
    RegistryData,
    RegistryEntry,
    RegistryTags,
    ResetChat,
    ResourcePackResponse,
    ResourcePackPop,
    ResourcePackPush,
    SelectKnownPacks,
    ServerLinks,
    ServerLink,
    Serverbound,
    ShowDialog,
    StoreCookie,
    TagEntry,
    Transfer,
    UpdateEnabledFeatures,
    UpdateTags,
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


def byte(n: int) -> Tag:
    return Tag(TagType.Byte, byte_val=n)


def string(s: str) -> Tag:
    return Tag(TagType.String, str_val=s)


def compound(**fields: Tag) -> Tag:
    return Tag(TagType.Compound, compound_val=fields)


# ── ClientInformation ────────────────────────────────────────────────


def test_client_information_round_trip_with_every_field():
    packet = ClientInformation(
        language="ru_ru",
        view_distance=12,
        chat_visibility=2,
        chat_colors=False,
        model_customisation=0x7F,
        main_hand=0,
        text_filtering=True,
        allows_listing=False,
        particle_status=1,
    )

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == 0
    # id(1 байт) + длина строки(1) + "ru_ru"(5) + view_distance(1)
    assert body[1] == 5
    assert body[2:7] == b"ru_ru"
    assert body[7] == 12
    assert body[8] == 2          # chat_visibility VarInt
    assert body[9] == 0          # chat_colors
    assert body[10] == 0x7F      # model_customisation u8
    assert body[11] == 0         # main_hand VarInt
    assert body[12] == 1         # text_filtering
    assert body[13] == 0         # allows_listing
    assert body[14] == 1         # particle_status VarInt


def test_client_information_new_matches_create_default():
    packet = ClientInformation.new(12)

    assert packet.language == "en_us"
    assert packet.view_distance == 12
    assert packet.chat_visibility == 0
    assert packet.chat_colors is True
    assert packet.model_customisation == 0x7F
    assert packet.main_hand == 1
    assert packet.text_filtering is False
    assert packet.allows_listing is True
    assert packet.particle_status == 0

    round_trip(Serverbound, packet)


# ── Пустые пакеты ────────────────────────────────────────────────────


def test_finish_configuration_round_trip_in_both_directions():
    clientbound_id, body = round_trip(Clientbound, FinishConfiguration())
    assert clientbound_id == 3
    assert body == b"\x03"  # только id, payload пустой

    serverbound_id, body = round_trip(Serverbound, FinishConfiguration())
    assert serverbound_id == 3
    assert body == b"\x03"

    round_trip(Serverbound, AcceptCodeOfConduct())
    round_trip(Clientbound, ResetChat())
    round_trip(Clientbound, ClearDialog())

    # Разные пустые варианты не должны схлопываться в один класс/ID.
    assert ResetChat is not ClearDialog
    assert Clientbound.id(ResetChat()) == 6
    assert Clientbound.id(ClearDialog()) == 18
    assert Serverbound.id(AcceptCodeOfConduct()) == 9


# ── KeepAlive / Ping ─────────────────────────────────────────────────


def test_keep_alive_round_trip_long():
    for value in (99, -1, 2**63 - 1, -(2**63)):
        packet_id, body = round_trip(
            Clientbound, KeepAlive(id=value)
        )
        assert packet_id == 4
        assert len(body) == 9  # id VarInt + 8 байт long

        packet_id, _ = round_trip(Serverbound, KeepAlive(id=value))
        assert packet_id == 4


def test_ping_and_pong_round_trip_int():
    packet_id, body = round_trip(Clientbound, Ping(id=-3))
    assert packet_id == 5
    assert body[1:] == (-3).to_bytes(4, "big", signed=True)

    # Serverbound Pong — это та же структура Ping { id: i32 }.
    packet_id, _ = round_trip(Serverbound, Ping(id=-3))
    assert packet_id == 5


# ── RegistryData / UpdateTags ────────────────────────────────────────


def test_registry_data_round_trip_with_network_nbt():
    biome = compound(
        has_precipitation=byte(1),
        name=string("plains"),
    )
    packet = RegistryData(
        registry="minecraft:worldgen/biome",
        entries=[
            RegistryEntry(id="minecraft:plains", data=biome),
            RegistryEntry(id="minecraft:desert", data=None),
        ],
    )

    packet_id, body = round_trip(Clientbound, packet)

    assert packet_id == 7
    assert packet.entries[0].data == biome
    assert packet.entries[1].data is None
    # Пустая запись пишет bool 0 и не пишет NBT.
    assert body[-1] == 0


def test_update_tags_round_trip_registries_and_tag_ids():
    packet = UpdateTags(
        registries=[
            RegistryTags(
                registry="minecraft:block",
                tags=[
                    TagEntry(name="minecraft:logs", ids=[1, 2, 300]),
                    TagEntry(name="minecraft:empty", ids=[]),
                ],
            ),
            RegistryTags(registry="minecraft:item", tags=[]),
        ]
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == 14
    assert packet.registries[0].tags[0].ids == [1, 2, 300]
    assert packet.registries[1].tags == []


# ── Resource packs / known packs ─────────────────────────────────────


def test_resource_pack_push_and_pop_round_trip():
    push = ResourcePackPush(
        id=5,
        url="http://example.net/pack.zip",
        hash="a" * 40,
        required=True,
        prompt=compound(text=string("Ставить?")),
    )
    packet_id, _ = round_trip(Clientbound, push)
    assert packet_id == 9
    assert push.prompt == compound(text=string("Ставить?"))

    for pack_id in (None, 5, 2**127 + 1):
        packet_id, _ = round_trip(
            Clientbound, ResourcePackPop(id=pack_id)
        )
        assert packet_id == 8


def test_resource_pack_response_round_trip_uuid_and_action():
    packet = ResourcePackResponse(id=5, action=1)

    packet_id, body = round_trip(Serverbound, packet)

    assert packet_id == 6
    assert body[1:17] == (5).to_bytes(16, "big")
    assert body[17] == 1  # action VarInt


def test_select_known_packs_round_trip():
    packet = SelectKnownPacks(
        packs=[
            KnownPack(namespace="minecraft", id="core", version="26.3"),
            KnownPack(namespace="quadrix", id="extra", version="1"),
        ]
    )

    packet_id, _ = round_trip(Clientbound, packet)
    assert packet_id == 15

    packet_id, body = round_trip(Serverbound, SelectKnownPacks(packs=[]))
    assert packet_id == 7
    assert body == b"\x07\x00"  # id + пустой список


# ── Прочие Clientbound ───────────────────────────────────────────────


def test_custom_payload_disconnect_and_feature_flags_round_trip():
    payload = CustomPayload(
        channel="minecraft:brand",
        data=bytes([7]) + b"vanilla",
    )
    packet_id, _ = round_trip(Clientbound, payload)
    assert packet_id == 1
    assert payload.data == b"\x07vanilla"

    reason = compound(text=string("bye"))
    packet_id, _ = round_trip(Clientbound, Disconnect(reason=reason))
    assert packet_id == 2

    features = UpdateEnabledFeatures(features=["minecraft:vanilla"])
    packet_id, _ = round_trip(Clientbound, features)
    assert packet_id == 13

    packet_id, _ = round_trip(
        Clientbound, Transfer(host="play.example.net", port=25565)
    )
    assert packet_id == 12

    packet_id, _ = round_trip(
        Clientbound, StoreCookie(key="quadrix:token", payload=b"\x01\x02")
    )
    assert packet_id == 11

    packet_id, _ = round_trip(Clientbound, CodeOfConduct(text="Be nice"))
    assert packet_id == 20

    packet_id, _ = round_trip(
        Clientbound, ShowDialog(dialog=compound(type=string("minecraft:notice")))
    )
    assert packet_id == 19


def test_server_links_round_trip_known_and_custom():
    packet = ServerLinks(
        links=[
            ServerLink(kind=Known(0), link="https://bugs.example.net"),
            ServerLink(
                kind=Custom(compound(text=string("Custom link"))),
                link="https://example.net",
            ),
        ]
    )

    packet_id, _ = round_trip(Clientbound, packet)

    assert packet_id == 17
    assert isinstance(packet.links[0].kind, Known)
    assert isinstance(packet.links[1].kind, Custom)
    # Custom пишется как bool=false + NBT, Known — как bool=true + VarInt.
    assert packet.links[0].kind.id == 0


# ── CustomClickAction / ClickPayload ─────────────────────────────────


def test_click_payload_matches_vanilla_bytes():
    # click_payload_is_length_prefixed: None -> [1, 0], Byte(1) -> [2, 1, 1].
    w = Writer()
    ClickPayload.write(None, w)
    assert w.data == bytearray(b"\x01\x00")

    w = Writer()
    ClickPayload.write(byte(1), w)
    assert w.data == bytearray(b"\x02\x01\x01")

    assert ClickPayload.read(Reader(b"\x01\x00")) is None
    assert ClickPayload.read(Reader(b"\x02\x01\x01")) == byte(1)


def test_custom_click_action_round_trip_with_and_without_payload():
    with_payload = CustomClickAction(
        id="authme:prejoin-register/submit",
        payload=compound(password=string("hunter2")),
    )
    packet_id, _ = round_trip(Serverbound, with_payload)
    assert packet_id == 8
    assert with_payload.payload == compound(password=string("hunter2"))

    without_payload = CustomClickAction(id="minecraft:x", payload=None)
    packet_id, _ = round_trip(Serverbound, without_payload)
    assert packet_id == 8
    assert without_payload.payload is None


# ── Cookie / ошибки ──────────────────────────────────────────────────


def test_cookie_response_round_trip_optional_payload():
    for payload in (None, b"\x01", b"many-bytes"):
        packet_id, _ = round_trip(
            Serverbound,
            CookieResponse(key="quadrix:test", payload=payload),
        )
        assert packet_id == 1


def test_unknown_id_is_unknown_by_default_and_strict_raises():
    unknown = Clientbound.decode(99, b"\xAA\xBB")
    assert unknown.packet_id == 99
    assert unknown.payload == b"\xAA\xBB"
    assert Clientbound.name(unknown) == "Unknown"
    assert Clientbound.id(unknown) == 99

    with pytest.raises(KeyError):
        Clientbound.decode(99, b"", strict=True)
    with pytest.raises(KeyError):
        Serverbound.decode(99, b"", strict=True)


def test_trailing_bytes_are_rejected():
    body = Serverbound.encode(ClientInformation.new(12))
    r = Reader(body)
    packet_id = r.varint()

    with pytest.raises(ValueError):
        Serverbound.decode(packet_id, r.rest() + b"\x00")

    with pytest.raises(ProtocolError):
        FinishConfiguration.decode(b"\x00")
