#!/usr/bin/env python3
"""Тесты quadrix/protocol/buf.py (порт horizon-protocol/src/buf.rs).

Проверяются точные байты из тестов Rust и round-trip всех примитивов.
buf.rs не читает файлы из .local (это чистый кодек провода), поэтому
тестов с реальными данными .local здесь нет — загружать нечего.
"""

from __future__ import annotations

import math

import pytest

from quadrix.protocol.buf import (
    BitSet,
    Bool,
    Byte,
    Bytes,
    ChunkPos,
    Double,
    Float,
    Ident,
    Int,
    List,
    Long,
    Longs,
    LpVec3,
    Opt,
    OptVarInt,
    PacketFrame,
    Pos,
    ProtocolError,
    Reader,
    SectionPos,
    Short,
    Str,
    Uuid,
    VarInt,
    VarLong,
    Writer,
    bit,
    frame_header,
    pack_block_pos,
    pack_degrees,
    pack_varint,
    packet_utf8,
    read_angle,
    read_packet_frame,
    read_position,
    set_bit,
    unpack_block_pos,
    unpack_degrees,
    varint_size,
    write_angle,
    write_packet_frame,
    write_position,
)
from quadrix.world.nbt import Tag, TagType


def round_trip(codec, value):
    """Записать значение кодеком и прочитать обратно; проверить остаток."""
    w = Writer()
    codec.write(value, w)
    r = Reader(w.data)
    result = codec.read(r)
    assert r.remaining() == 0
    return result, bytes(w.data)


# ── VarInt ───────────────────────────────────────────────────────────

def test_varint_round_trip_values():
    for value in [0, 1, 127, 128, 255, 300, 2**31 - 1]:
        assert round_trip(VarInt, value)[0] == value


def test_varint_matches_vanilla_examples():
    examples = {
        0: b"\x00",
        1: b"\x01",
        127: b"\x7f",
        128: b"\x80\x01",
        255: b"\xff\x01",
        25565: b"\xdd\xc7\x01",
        2097151: b"\xff\xff\x7f",
        2**31 - 1: b"\xff\xff\xff\xff\x07",
        -1: b"\xff\xff\xff\xff\x0f",
        -(2**31): b"\x80\x80\x80\x80\x08",
    }
    for value, expected in examples.items():
        assert pack_varint(value) == expected
        r = Reader(expected)
        assert r.varint() == value
        assert varint_size(value) == len(expected)
        assert r.remaining() == 0


def test_varint_rejects_six_continuation_bytes():
    with pytest.raises(ProtocolError, match="VarInt too big"):
        Reader(b"\xff" * 6).varint()


# ── VarLong ──────────────────────────────────────────────────────────

def test_varlong_round_trip():
    for value in [0, 1, 2**63 - 1, -1, -(2**63)]:
        assert round_trip(VarLong, value)[0] == value


def test_varlong_matches_vanilla_examples():
    assert round_trip(VarLong, 0)[1] == b"\x00"
    assert (
        round_trip(VarLong, 2**63 - 1)[1]
        == b"\xff\xff\xff\xff\xff\xff\xff\xff\x7f"
    )
    assert (
        round_trip(VarLong, -1)[1]
        == b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01"
    )


# ── Строки ───────────────────────────────────────────────────────────

def test_string_round_trip():
    for text in ["hello", "привет", ""]:
        assert round_trip(Ident, text)[0] == text
    # "héllo" из теста Rust: длина в байтах = 6.
    assert round_trip(Str, "héllo")[1] == b"\x06h\xc3\xa9llo"


def test_string_limit_and_utf16_counting():
    w = Writer()
    w.string("x" * 32768)
    with pytest.raises(ValueError, match="string longer than 32767"):
        Reader(w.data).string(32767)

    # Java считает UTF-16 единицы: 8 эмодзи — это 16 единиц.
    w = Writer()
    w.string("😀" * 8)
    assert Reader(w.data).string(16) == "😀" * 8
    with pytest.raises(ProtocolError):
        Reader(w.data).string(15)


def test_packet_utf8_replaces_malformed_like_java():
    cases = [
        (b"\xff", "\ufffd"),
        (b"\xed\xa0\x80", "\ufffd"),
        (b"\xed\xa0", "\ufffd"),
        (b"\xe0\x80\x80", "\ufffd\ufffd\ufffd"),
        (b"\xe2\x82A", "\ufffdA"),
        (b"\xf0\x9f\x98", "\ufffd"),
    ]
    for raw, expected in cases:
        assert packet_utf8(raw) == expected


def test_truncated_string_does_not_advance_cursor():
    # Длина 4, но всего два байта: чтение падает до сдвига позиции.
    r = Reader(b"\x04\xff\xff\xff\xff"[:2])
    with pytest.raises(ProtocolError):
        r.string(1)


# ── Примитивы ────────────────────────────────────────────────────────

def test_primitives_round_trip():
    values = [
        (Bool, True),
        (Byte, -128),
        (Byte, 127),
        (Short, -32768),
        (Int, 123456789),
        (Int, -1),
        (Long, -(2**63)),
        (Float, 1.5),
        (Double, -3.25),
        (Uuid, 0x0123_4567_89ab_cdef_0011_2233_4455_6677),
    ]
    for codec, value in values:
        assert round_trip(codec, value)[0] == value


def test_bool_and_bytes_are_big_endian_on_the_wire():
    w = Writer()
    w.bool(True)
    w.bool(False)
    w.u16(0x1234)
    w.i32(0x01020304)
    assert bytes(w.data) == b"\x01\x00\x12\x34\x01\x02\x03\x04"


# ── Позиции ──────────────────────────────────────────────────────────

def test_block_pos_pack_round_trip():
    for pos in [
        (10, 64, -5),
        (0, 0, 0),
        (-1, -64, -1),
        (33_554_431, 2047, -33_554_432),
        (123, -2048, -456),
    ]:
        assert unpack_block_pos(pack_block_pos(pos)) == pos

    # BlockPos.asLong(1, 2, 3) из теста Rust.
    assert pack_block_pos((1, 2, 3)) == (1 << 38) | (3 << 12) | 2


def test_write_position_read_position():
    w = Writer()
    write_position(w, (10, 64, -5))
    assert read_position(Reader(w.data)) == (10, 64, -5)
    assert round_trip(Pos, (10, 64, -5))[0] == (10, 64, -5)


def test_chunk_and_section_pos_round_trip():
    assert round_trip(ChunkPos, (-7, 12))[0] == (-7, 12)
    assert round_trip(SectionPos, (-5, -4, 1000))[0] == (-5, -4, 1000)
    assert round_trip(SectionPos, (0, 0, 0))[0] == (0, 0, 0)


# ── Углы ─────────────────────────────────────────────────────────────

def test_angles_pack_like_mth():
    assert pack_degrees(90.0) == 64
    assert pack_degrees(-90.0) == -64
    # Байт знаковый: 180° на проводе — это -128.
    assert pack_degrees(180.0) == -128
    assert unpack_degrees(0) == 0.0
    assert unpack_degrees(64) == 90.0
    assert unpack_degrees(-128) == -180.0

    w = Writer()
    write_angle(w, 90.0)
    assert bytes(w.data) == b"\x40"
    assert read_angle(Reader(w.data)) == 90.0


# ── Кадры пакетов ────────────────────────────────────────────────────

def test_packet_frame_round_trip():
    frame = write_packet_frame(0x00, b"\x01\x02")
    assert frame == b"\x03\x00\x01\x02"  # длина 3, id 0, payload
    assert read_packet_frame(frame) == (0x00, b"\x01\x02")


def test_packet_frame_with_multibyte_id_and_empty_payload():
    frame = write_packet_frame(300, b"")
    assert frame[0] == 2  # 300 занимает два байта VarInt
    assert read_packet_frame(frame) == (300, b"")
    assert PacketFrame(0x2A, b"abc").to_bytes() == write_packet_frame(
        0x2A, b"abc"
    )
    assert PacketFrame.from_bytes(
        write_packet_frame(0x2A, b"abc")
    ) == PacketFrame(0x2A, b"abc")


def test_frame_header_reports_incomplete_and_bad_frames():
    assert frame_header(b"\x03") == (1, 3)
    assert frame_header(b"") is None
    assert frame_header(b"\x80") is None
    with pytest.raises(ProtocolError, match="zero"):
        frame_header(b"\x00")
    with pytest.raises(ProtocolError, match="21 bits"):
        frame_header(b"\xff\xff\xff\xff")
    with pytest.raises(ProtocolError, match="incomplete frame"):
        read_packet_frame(b"\x05\x00\x01")


# ── Составные кодеки ─────────────────────────────────────────────────

def test_list_and_optional_codecs():
    assert round_trip(List(VarInt), [1, 300, -1])[0] == [1, 300, -1]
    assert round_trip(Opt(Str), "x")[0] == "x"
    assert round_trip(Opt(Str), None)[0] is None
    assert round_trip(OptVarInt, 0)[0] == 0
    assert round_trip(OptVarInt, None)[0] is None
    assert round_trip(Bytes, b"\xde\xad")[0] == b"\xde\xad"
    assert round_trip(Longs, [1, -2, 2**62])[0] == [1, -2, 2**62]


def test_bitset_drops_trailing_zero_bytes():
    bits = bytearray(4)
    set_bit(bits, 3)
    set_bit(bits, 9)
    w = Writer()
    BitSet.write(bits, w)
    assert bytes(w.data) == bytes([2, 0b1000, 0b10])
    read_back = BitSet.read(Reader(w.data))
    assert bit(read_back, 3) and bit(read_back, 9)
    assert not bit(read_back, 4) and not bit(read_back, 100)


def test_network_nbt_round_trip():
    tag = Tag(
        TagType.Compound,
        compound_val={
            "name": Tag(TagType.String, str_val="Стив"),
            "health": Tag(TagType.Float, float_val=20.0),
            "mix": Tag(
                TagType.List,
                list_val=[
                    Tag(TagType.String, str_val="x"),
                    Tag(TagType.Int, int_val=2),
                ],
            ),
            "ids": Tag(TagType.LongArray, longarray_val=[1, -2, 3]),
        },
    )
    w = Writer()
    w.nbt(tag)
    # Первый байт — id Compound (10), имя корня не пишется.
    assert bytes(w.data)[0] == TagType.Compound
    r = Reader(w.data)
    back = r.nbt()
    assert r.remaining() == 0
    assert back.is_compound
    assert back.compound_val["name"].str_val == "Стив"
    assert back.compound_val["health"].float_val == 20.0
    assert [v.tag_type for v in back.compound_val["mix"].list_val] == [
        TagType.String,
        TagType.Int,
    ]
    assert back.compound_val["ids"].longarray_val == [1, -2, 3]


def test_nbt_absent_tag_is_end():
    w = Writer()
    w.nbt(Tag(TagType.End, is_end=True))
    assert bytes(w.data) == b"\x00"
    assert Reader(w.data).nbt().is_end


def test_lp_vec3_round_trips_within_precision():
    for vec in [
        (0.0, 0.0, 0.0),
        (0.1, -0.2, 0.3),
        (1.5, -3.25, 0.0),
        (12.0, 0.0, -40.5),
    ]:
        back = LpVec3.quantize(vec)
        scale = max(1.0, math.ceil(max(abs(c) for c in vec)))
        for i in range(3):
            assert abs(back[i] - vec[i]) <= scale / 32766.0 * 1.01

    # Почти ноль — один байт 0.
    w = Writer()
    LpVec3.write((0.0, 1e-9, 0.0), w)
    assert bytes(w.data) == b"\x00"
