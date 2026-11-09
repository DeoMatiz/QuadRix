# Порт horizon-protocol/src/buf.rs (+ только незашифрованная часть frame.rs).
#
# Здесь лежат примитивы сетевого протокола vanilla: FriendlyByteBuf,
# VarInt/VarLong, строки UTF-8, UUID, упакованные позиции, углы,
# низкоточные векторы и StreamCodec-совместимые кодеки.
#
# Сознательно НЕ портируется:
#   * crypto.rs            — шифрование;
#   * compression.rs       — zlib выше порога;
#   * packets/*.rs         — конкретные пакеты.
#
# Кадр (frame) реализован в несжатом виде — так же, как ветка
# `threshold = None` в frame.rs.

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence, Tuple

from quadrix.world.nbt import (
    JavaString,
    Tag,
    TagType,
    _modified_utf8_decode_units,
    _modified_utf8_encode_byte_count,
    _modified_utf8_encode_units,
)

__all__ = [
    "NBT_QUOTA",
    "NBT_MAX_TAGS",
    "MAX_FRAME",
    "ProtocolError",
    "Reader",
    "ByteReader",
    "Writer",
    "ByteWriter",
    "packet_utf8",
    "write_varint",
    "varint_size",
    "read_varint",
    "write_varlong",
    "pack_varint",
    "pack_varlong",
    "pack_block_pos",
    "unpack_block_pos",
    "pack_degrees",
    "unpack_degrees",
    "write_position",
    "read_position",
    "write_angle",
    "read_angle",
    "PacketFrame",
    "frame_header",
    "read_packet_frame",
    "write_packet_frame",
    # кодеки (StreamCodec)
    "Bool",
    "Byte",
    "UByte",
    "Short",
    "UShort",
    "Int",
    "Long",
    "Float",
    "Double",
    "VarInt",
    "VarLong",
    "Uuid",
    "Str",
    "StrN",
    "Ident",
    "Bytes",
    "BytesN",
    "Rest",
    "Nbt",
    "Longs",
    "List",
    "Opt",
    "OptVarInt",
    "VarVec3i",
    "Vec3d",
    "Pos",
    "ChunkPos",
    "SectionPos",
    "BitSet",
    "bit",
    "set_bit",
    "LpVec3",
]


# ── Константы (buf.rs) ────────────────────────────────────────────────

# buf.rs:9 — NbtAccounter.defaultQuota.
NBT_QUOTA: int = 2_097_152
# buf.rs:12 — EndTag::SELF_SIZE_IN_BYTES, минимальная цена одного тега.
MIN_TAG_COST: int = 8
# buf.rs:17 — больше тегов, чем допускает квота vanilla, отклоняем.
NBT_MAX_TAGS: int = NBT_QUOTA // MIN_TAG_COST

# frame.rs:11 — кадр не длиннее трёх байт VarInt (21 бит).
MAX_FRAME: int = (1 << 21) - 1


class ProtocolError(ValueError):
    """Ошибка чтения/записи протокола (аналог horizon_protocol::Error).

    Наследует ValueError, чтобы переполнение строки/счётчика можно было
    ловить и как ValueError.
    """


# ── Приведение типов как Rust `as` ────────────────────────────────────

_U64 = 0xFFFFFFFFFFFFFFFF
_U32 = 0xFFFFFFFF
_I64_SIGN = 0x8000000000000000
_I32_SIGN = 0x80000000


def _to_u64(v: int) -> int:
    return int(v) & _U64


def _to_i64(v: int) -> int:
    v = int(v) & _U64
    return v - 0x1_0000_0000_0000_0000 if v >= _I64_SIGN else v


def _to_i32(v: int) -> int:
    v = int(v) & _U32
    return v - 0x1_0000_0000 if v >= _I32_SIGN else v


def _to_u32(v: int) -> int:
    return int(v) & _U32


def _to_i16(v: int) -> int:
    v = int(v) & 0xFFFF
    return v - 0x1_0000 if v >= 0x8000 else v


def _to_u16(v: int) -> int:
    return int(v) & 0xFFFF


def _to_i8(v: int) -> int:
    v = int(v) & 0xFF
    return v - 0x100 if v >= 0x80 else v


def _to_u8(v: int) -> int:
    return int(v) & 0xFF


def _f32(v: float) -> float:
    """Округление до IEEE-754 binary32 (как f32 в Rust)."""
    return struct.unpack(">f", struct.pack(">f", float(v)))[0]


def _round_away(value: float) -> int:
    """f64::round: половина уходит от нуля (Python round — к чётному)."""
    if value >= 0.0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def _xyz(v: Any) -> Tuple[Any, Any, Any]:
    """Достать три компоненты из кортежа/списка/Vec3/BlockPos."""
    if isinstance(v, (tuple, list)):
        return v[0], v[1], v[2]
    return v.x, v.y, v.z


# ── Reader / ByteReader (buf.rs:20) ──────────────────────────────────

class Reader:
    """Курсор по телу принятого пакета (buf.rs:20)."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes | bytearray | memoryview):
        self.data = bytes(data)
        self.pos = 0

    # -- состояние --

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def position(self) -> int:
        return self.pos

    def since(self, start: int) -> bytes:
        """Байты, прочитанные с позиции `start` (buf.rs:35)."""
        return self.data[min(start, self.pos):self.pos]

    def rest(self) -> bytes:
        rest = self.data[self.pos:]
        self.pos = len(self.data)
        return rest

    def bytes(self, n: int) -> bytes:
        if self.remaining() < n:
            raise ProtocolError(
                f"needed {n} bytes, {self.remaining()} left"
            )
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def _array(self, n: int) -> bytes:
        return self.bytes(n)

    # -- примитивы --

    def u8(self) -> int:
        return self._array(1)[0]

    def i8(self) -> int:
        return _to_i8(self.u8())

    def bool(self) -> bool:
        return self.u8() != 0

    def i16(self) -> int:
        return struct.unpack(">h", self._array(2))[0]

    def u16(self) -> int:
        return struct.unpack(">H", self._array(2))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._array(4))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self._array(4))[0]

    def i64(self) -> int:
        return struct.unpack(">q", self._array(8))[0]

    def f32(self) -> float:
        return struct.unpack(">f", self._array(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self._array(8))[0]

    # -- VarInt / VarLong (buf.rs:88, 100) --

    def varint(self) -> int:
        value = 0
        for i in range(5):  # buf.rs:90 — не больше пяти 7-битных групп
            b = self.u8()
            value |= (b & 0x7F) << (7 * i)
            if b & 0x80 == 0:
                return _to_i32(value)
        raise ProtocolError("VarInt too big")

    def varlong(self) -> int:
        value = 0
        for i in range(10):  # buf.rs:101 — не больше десяти групп
            b = self.u8()
            value |= (b & 0x7F) << (7 * i)
            if b & 0x80 == 0:
                return _to_i64(value)
        raise ProtocolError("VarLong too big")

    def count(self, max_count: int) -> int:
        """VarInt-счётчик, который обязан влезть в `max_count` (buf.rs:112)."""
        n = self.varint()
        if n < 0:
            raise ProtocolError(f"negative count {n}")
        if n > max_count:
            raise ProtocolError(
                f"{n} elements is more than allowed {max_count}"
            )
        return n

    def string(self, max_chars: int) -> str:
        """Utf8String.read (buf.rs:124): VarInt-длина в байтах + UTF-8."""
        length = self.count(max_chars * 3)  # buf.rs:125
        s = packet_utf8(self.bytes(length))
        if len(s.encode("utf-16-le")) // 2 > max_chars:
            raise ProtocolError(f"string longer than {max_chars} chars")
        return s

    def byte_array(self, max_len: int) -> bytes:
        length = self.count(max_len)
        return self.bytes(length)

    def uuid(self) -> int:
        """UUID как u128 big-endian (buf.rs:136)."""
        return int.from_bytes(self._array(16), "big")

    def nbt(self):
        """Сетевой NBT-тег без имени корня (buf.rs:140).

        Формат: id тега, затем payload (Compound хранит имена полей,
        List — только id элемента). NbtIo.readAnyTag.
        """
        cursor = _NbtCursor(self.data, self.pos, NBT_QUOTA, NBT_MAX_TAGS)
        try:
            tag = cursor.root()
        except _NbtError as exc:
            raise ProtocolError(f"NBT: {exc}") from exc
        self.pos = cursor.pos
        return tag

    def long_array(self) -> list[int]:
        n = self.count(self.remaining() // 8)
        return [self.i64() for _ in range(n)]

    def fixed_longs(self, n: int) -> list[int]:
        if self.remaining() < n * 8:
            raise ProtocolError("fixed long array past the end")
        return [self.i64() for _ in range(n)]


# Псевдоним из задания: ByteReader.
ByteReader = Reader


# ── Сетевой NBT (buf.rs:140, nbt.rs read_network/write_network) ──────

class _NbtError(Exception):
    """Ошибка разбора/записи NBT внутри buf.py."""


class _NbtCursor:
    """Читатель сетивого NBT: id тега + payload, без имени корня."""

    def __init__(self, data: bytes, start: int, max_bytes: int, max_nodes: int):
        self.data = data
        self.start = start
        self.pos = start
        self.max_bytes = max_bytes
        self.max_nodes = max_nodes
        self.nodes = 0

    # -- низкий уровень --

    def _take(self, n: int) -> bytes:
        if n < 0:
            raise _NbtError("negative length")
        end = self.pos + n
        if end > len(self.data):
            raise _NbtError("truncated input")
        if end - self.start > self.max_bytes:
            raise _NbtError("byte limit exceeded")
        out = self.data[self.pos:end]
        self.pos = end
        return out

    def _u8(self) -> int:
        return self._take(1)[0]

    def _i16(self) -> int:
        return struct.unpack(">h", self._take(2))[0]

    def _u16(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def _i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def _i64(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def _string(self) -> str:
        length = self._u16()
        raw = self._take(length)
        units = _modified_utf8_decode_units(raw)
        return JavaString(units).to_python_str()

    def _count(self) -> int:
        length = self._i32()
        if length < 0:
            raise _NbtError("negative count")
        return length

    # -- теги --

    def root(self) -> Tag:
        return self.payload(self._u8(), 0)

    def payload(self, tag_id: int, depth: int) -> Tag:
        if self.nodes >= self.max_nodes:
            raise _NbtError("node limit exceeded")
        self.nodes += 1
        if tag_id in (TagType.List, TagType.Compound) and depth >= 512:
            raise _NbtError("depth limit exceeded")

        if tag_id == TagType.End:
            return Tag(TagType.End, is_end=True)
        if tag_id == TagType.Byte:
            b = self._u8()
            return Tag(TagType.Byte, byte_val=b - 256 if b >= 128 else b)
        if tag_id == TagType.Short:
            return Tag(TagType.Short, short_val=self._i16())
        if tag_id == TagType.Int:
            return Tag(TagType.Int, int_val=self._i32())
        if tag_id == TagType.Long:
            return Tag(TagType.Long, long_val=self._i64())
        if tag_id == TagType.Float:
            value = struct.unpack(">f", self._take(4))[0]
            # buf.rs читает через nbt.rs: -0.0 нормализуется в +0.0.
            return Tag(TagType.Float, float_val=0.0 if value == 0.0 else value)
        if tag_id == TagType.Double:
            value = struct.unpack(">d", self._take(8))[0]
            return Tag(TagType.Double, double_val=0.0 if value == 0.0 else value)
        if tag_id == TagType.ByteArray:
            length = self._count()
            return Tag(TagType.ByteArray, bytes_val=self._take(length))
        if tag_id == TagType.String:
            return Tag(TagType.String, str_val=self._string())
        if tag_id == TagType.List:
            element_id = self._u8()
            length = self._count()
            if length > 0 and (element_id == 0 or element_id > 12):
                raise _NbtError("invalid list element type")
            values: list[Tag] = []
            for _ in range(length):
                value = self.payload(element_id, depth + 1)
                # Синтетический compound с пустым именем разворачивается
                # обратно в элемент (nbt.rs:277).
                if value.is_compound and value.compound_val is not None:
                    if len(value.compound_val) == 1 and "" in value.compound_val:
                        value = value.compound_val[""]
                values.append(value)
            return Tag(TagType.List, list_val=values)
        if tag_id == TagType.Compound:
            compound: dict[str, Tag] = {}
            while True:
                child_id = self._u8()
                if child_id == 0:
                    break
                name = self._string()
                compound[name] = self.payload(child_id, depth + 1)
            return Tag(TagType.Compound, compound_val=compound)
        if tag_id == TagType.IntArray:
            length = self._count()
            return Tag(
                TagType.IntArray,
                intarray_val=[self._i32() for _ in range(length)],
            )
        if tag_id == TagType.LongArray:
            length = self._count()
            return Tag(
                TagType.LongArray,
                longarray_val=[self._i64() for _ in range(length)],
            )
        raise _NbtError("unknown tag type")


def _nbt_write_string(out: bytearray, s: str) -> None:
    units = JavaString.from_python_str(s).units
    byte_len = _modified_utf8_encode_byte_count(units)
    if byte_len > 0xFFFF:
        raise _NbtError("modified UTF-8 exceeds 65535 bytes")
    out += struct.pack(">H", byte_len)
    out += _modified_utf8_encode_units(units)


def _nbt_tag_id(tag: Tag) -> int:
    return int(tag.tag_type)


def _nbt_write_payload(out: bytearray, tag: Tag, depth: int) -> None:
    tag_id = _nbt_tag_id(tag)
    if tag_id == TagType.List and depth >= 512:
        raise _NbtError("depth limit exceeded")
    if tag_id == TagType.Compound and depth >= 512:
        raise _NbtError("depth limit exceeded")

    if tag_id == TagType.End:
        return
    if tag_id == TagType.Byte:
        out.append((tag.byte_val or 0) & 0xFF)
    elif tag_id == TagType.Short:
        out += struct.pack(">h", tag.short_val or 0)
    elif tag_id == TagType.Int:
        out += struct.pack(">i", tag.int_val or 0)
    elif tag_id == TagType.Long:
        out += struct.pack(">q", tag.long_val or 0)
    elif tag_id == TagType.Float:
        value = tag.float_val
        if isinstance(value, int):
            out += struct.pack(">I", value & _U32)
        else:
            out += struct.pack(">f", _f32(value or 0.0))
    elif tag_id == TagType.Double:
        value = tag.double_val
        if isinstance(value, int):
            out += struct.pack(">Q", value & _U64)
        else:
            out += struct.pack(">d", float(value or 0.0))
    elif tag_id == TagType.ByteArray:
        raw = bytes(tag.bytes_val or b"")
        out += struct.pack(">i", len(raw))
        out += raw
    elif tag_id == TagType.String:
        _nbt_write_string(out, tag.str_val or "")
    elif tag_id == TagType.List:
        values = list(tag.list_val or [])
        if any(_nbt_tag_id(v) == TagType.End for v in values):
            raise _NbtError("End cannot be a list element")
        first = _nbt_tag_id(values[0]) if values else 0
        element_id = first
        if any(_nbt_tag_id(v) != first for v in values):
            element_id = TagType.Compound
        out.append(element_id)
        out += struct.pack(">i", len(values))
        for value in values:
            compound = value.compound_val if value.is_compound else None
            wrapped = (
                compound is not None
                and len(compound) == 1
                and "" in compound
            )
            # Смешанный список пишется compound-обёрткой с пустым именем.
            if element_id == TagType.Compound and (
                _nbt_tag_id(value) != TagType.Compound or wrapped
            ):
                out.append(_nbt_tag_id(value))
                _nbt_write_string(out, "")
                _nbt_write_payload(out, value, depth + 2)
                out.append(0)
            else:
                _nbt_write_payload(out, value, depth + 1)
    elif tag_id == TagType.Compound:
        compound = tag.compound_val or {}
        for name in sorted(compound):
            value = compound[name]
            if _nbt_tag_id(value) == TagType.End:
                raise _NbtError("End cannot be a named value")
            out.append(_nbt_tag_id(value))
            _nbt_write_string(out, name)
            _nbt_write_payload(out, value, depth + 1)
        out.append(0)
    elif tag_id == TagType.IntArray:
        values = list(tag.intarray_val or [])
        out += struct.pack(">i", len(values))
        for value in values:
            out += struct.pack(">i", value)
    elif tag_id == TagType.LongArray:
        values = list(tag.longarray_val or [])
        out += struct.pack(">i", len(values))
        for value in values:
            out += struct.pack(">q", value)
    else:
        raise _NbtError("unknown tag type")


def _nbt_write_network(tag: Tag) -> bytes:
    out = bytearray()
    out.append(_nbt_tag_id(tag))
    _nbt_write_payload(out, tag, 0)
    return bytes(out)


# ── Java UTF-8 replacement decoder (buf.rs:166) ───────────────────────

def packet_utf8(data: bytes) -> str:
    """Декодер UTF-8 с заменами как в Java (Utf8String.read).

    Почти как Rust: некорректный префикс заменяется U+FFFD, а
    закодированный суррогат (вместе с усечённым двухбайтным префиксом)
    съедается целиком — этого не делает `errors="replace"`.
    """
    out: list[str] = []
    pos = 0
    n = len(data)
    while pos < n:
        try:
            out.append(data[pos:].decode("utf-8"))
            break
        except UnicodeDecodeError as err:
            valid = data[pos:pos + err.start]
            if valid:
                out.append(valid.decode("utf-8"))
            rest = data[pos + err.start:]
            surrogate = (
                rest[0] == 0xED
                and len(rest) > 1
                and 0xA0 <= rest[1] <= 0xBF
            )
            if surrogate:
                if len(rest) > 2 and rest[2] & 0xC0 == 0x80:
                    consumed = 3
                else:
                    consumed = 2
            else:
                consumed = err.end - err.start
                if consumed <= 0:
                    consumed = len(rest)
            out.append("\ufffd")
            pos += err.start + consumed
    return "".join(out)


# ── Writer / ByteWriter (buf.rs:199) ─────────────────────────────────

class Writer:
    """Тело исходящего пакета (buf.rs:199)."""

    __slots__ = ("data",)

    def __init__(self):
        self.data = bytearray()

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def u8(self, v: int) -> None:
        self.data.append(_to_u8(v))

    def i8(self, v: int) -> None:
        self.data.append(_to_i8(v) & 0xFF)

    def bool(self, v: bool) -> None:
        self.data.append(1 if v else 0)

    def i16(self, v: int) -> None:
        self.data += struct.pack(">h", _to_i16(v))

    def u16(self, v: int) -> None:
        self.data += struct.pack(">H", _to_u16(v))

    def i32(self, v: int) -> None:
        self.data += struct.pack(">i", _to_i32(v))

    def u32(self, v: int) -> None:
        self.data += struct.pack(">I", _to_u32(v))

    def i64(self, v: int) -> None:
        self.data += struct.pack(">q", _to_i64(v))

    def f32(self, v: float) -> None:
        self.data += struct.pack(">f", _f32(v))

    def f64(self, v: float) -> None:
        self.data += struct.pack(">d", float(v))

    def varint(self, v: int) -> None:
        write_varint(self.data, v)

    def varlong(self, v: int) -> None:
        write_varlong(self.data, v)

    def string(self, s: str) -> None:
        encoded = s.encode("utf-8")
        self.varint(len(encoded))
        self.data += encoded

    def byte_array(self, b: bytes | bytearray | memoryview) -> None:
        raw = bytes(b)
        self.varint(len(raw))
        self.data += raw

    def bytes(self, b: bytes | bytearray | memoryview) -> None:
        self.data += bytes(b)

    def uuid(self, v: int) -> None:
        self.data += int(v).to_bytes(16, "big", signed=False)

    def nbt(self, tag: Any) -> None:
        try:
            encoded = _nbt_write_network(tag)
        except (_NbtError, struct.error, ValueError):
            # Непредставимый тег уходит как «нет тега» (buf.rs:268).
            self.data.append(0)
            return
        self.data += encoded

    def long_array(self, values: Iterable[int]) -> None:
        seq = list(values)
        self.varint(len(seq))
        for value in seq:
            self.i64(value)


# Псевдоним из задания: ByteWriter.
ByteWriter = Writer


# ── VarInt / VarLong (buf.rs:279) ────────────────────────────────────

def write_varint(out: bytearray, v: int) -> None:
    """Записать VarInt в буфер (buf.rs:279)."""
    value = _to_u32(v)
    while True:
        if value & ~0x7F & _U32 == 0:
            out.append(value)
            return
        out.append((value & 0x7F) | 0x80)
        value >>= 7


def write_varlong(out: bytearray, v: int) -> None:
    """Записать VarLong в буфер (buf.rs:240)."""
    value = _to_u64(v)
    while True:
        if value & ~0x7F & _U64 == 0:
            out.append(value)
            return
        out.append((value & 0x7F) | 0x80)
        value >>= 7


def varint_size(v: int) -> int:
    """Длина VarInt в байтах (buf.rs:290)."""
    value = _to_u32(v)
    for i in range(1, 5):
        if value >> (7 * i) == 0:
            return i
    return 5


def pack_varint(v: int) -> bytes:
    out = bytearray()
    write_varint(out, v)
    return bytes(out)


def pack_varlong(v: int) -> bytes:
    out = bytearray()
    write_varlong(out, v)
    return bytes(out)


def read_varint(r: Reader) -> int:
    return r.varint()


# ── Позиции и углы (buf.rs:474, 602) ─────────────────────────────────

def pack_block_pos(p: Any) -> int:
    """BlockPos.asLong: x (26 бит), z (26 бит), y (12 бит) (buf.rs:474)."""
    x, y, z = _xyz(p)
    return (
        ((int(x) & 0x3FF_FFFF) << 38)
        | ((int(z) & 0x3FF_FFFF) << 12)
        | (int(y) & 0xFFF)
    )


def unpack_block_pos(v: int) -> Tuple[int, int, int]:
    """Обратное к pack_block_pos с арифметическими сдвигами i64 (buf.rs:479)."""
    value = _to_i64(v)
    x = _to_i32(value >> 38)
    # v << 52 >> 52 — знаковое расширение 12-битного y.
    y = _to_i32(_to_i64((value << 52) & _U64) >> 52)
    # v << 26 >> 38 — знаковое расширение 26-битного z.
    z = _to_i32(_to_i64((value << 26) & _U64) >> 38)
    return x, y, z


def write_position(w: Writer, pos: Any) -> None:
    w.i64(pack_block_pos(pos))


def read_position(r: Reader) -> Tuple[int, int, int]:
    return unpack_block_pos(r.i64())


def pack_degrees(degrees: float) -> int:
    """Mth.packDegrees: градусы в знаковый байт (buf.rs:602)."""
    scaled = _f32(_f32(float(degrees) * 256.0) / 360.0)
    return _to_i8(int(math.floor(scaled)))


def unpack_degrees(b: int) -> float:
    """Mth.unpackDegrees: знаковый байт в градусы (buf.rs:605)."""
    return _f32(_f32(float(_to_i8(b)) * 360.0) / 256.0)


def write_angle(w: Writer, degrees: float) -> None:
    w.i8(pack_degrees(degrees))


def read_angle(r: Reader) -> float:
    return unpack_degrees(r.i8())


# ── StreamCodec-кодеки (buf.rs:295) ──────────────────────────────────
#
# Кодеки — классы (или экземпляры с параметрами) с методами
# read(reader) / write(value, writer), как Codec<T> в Rust.

class _Primitive:
    """Обёртка над парой методов Reader/Writer."""

    reader_attr = ""
    writer_attr = ""

    @classmethod
    def read(cls, r: Reader):
        return getattr(r, cls.reader_attr)()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        getattr(w, cls.writer_attr)(v)


def _primitive(name: str, reader_attr: str, writer_attr: str) -> type:
    return type(
        name,
        (_Primitive,),
        {"reader_attr": reader_attr, "writer_attr": writer_attr},
    )


Bool = _primitive("Bool", "bool", "bool")
Byte = _primitive("Byte", "i8", "i8")
UByte = _primitive("UByte", "u8", "u8")
Short = _primitive("Short", "i16", "i16")
UShort = _primitive("UShort", "u16", "u16")
Int = _primitive("Int", "i32", "i32")
Long = _primitive("Long", "i64", "i64")
Float = _primitive("Float", "f32", "f32")
Double = _primitive("Double", "f64", "f64")
VarInt = _primitive("VarInt", "varint", "varint")
VarLong = _primitive("VarLong", "varlong", "varlong")
Uuid = _primitive("Uuid", "uuid", "uuid")


class Str:
    """ByteBufCodecs.STRING_UTF8 — 32767 символов (buf.rs:327)."""

    MAX_CHARS = 32767  # buf.rs:331

    @classmethod
    def read(cls, r: Reader) -> str:
        return r.string(cls.MAX_CHARS)

    @classmethod
    def write(cls, v: str, w: Writer) -> None:
        w.string(v)


class StrN:
    """Строка с меньшим лимитом vanilla, например имя игрока (16)."""

    def __init__(self, max_chars: int):
        self.max_chars = int(max_chars)

    def read(self, r: Reader) -> str:
        return r.string(self.max_chars)

    def write(self, v: str, w: Writer) -> None:
        w.string(v)


# Identifier.STREAM_CODEC (buf.rs:347).
Ident = StrN(32767)


class Bytes:
    """VarInt-префикс + байты (buf.rs:349)."""

    @classmethod
    def read(cls, r: Reader) -> bytes:
        return r.byte_array(r.remaining())

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.byte_array(v)


class BytesN:
    """VarInt-префикс + байты, не больше N (buf.rs:359)."""

    def __init__(self, max_len: int):
        self.max_len = int(max_len)

    def read(self, r: Reader) -> bytes:
        return r.byte_array(self.max_len)

    def write(self, v, w: Writer) -> None:
        w.byte_array(v)


class Rest:
    """Всё оставшееся в пакете (buf.rs:369)."""

    @classmethod
    def read(cls, r: Reader) -> bytes:
        return r.rest()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.bytes(v)


class Nbt:
    @classmethod
    def read(cls, r: Reader):
        return r.nbt()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.nbt(v)


class Longs:
    """ByteBufCodecs.LONG_ARRAY (buf.rs:389)."""

    @classmethod
    def read(cls, r: Reader) -> list[int]:
        return r.long_array()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.long_array(v)


class List:
    """ByteBufCodecs.list: VarInt-счётчик и элементы (buf.rs:399)."""

    def __init__(self, element_codec):
        self.element_codec = element_codec

    def read(self, r: Reader) -> list:
        n = r.count(r.remaining())
        return [self.element_codec.read(r) for _ in range(n)]

    def write(self, v, w: Writer) -> None:
        w.varint(len(v))
        for element in v:
            self.element_codec.write(element, w)


class Opt:
    """ByteBufCodecs.optional: boolean-флаг присутствия (buf.rs:413)."""

    def __init__(self, codec):
        self.codec = codec

    def read(self, r: Reader):
        if r.bool():
            return self.codec.read(r)
        return None

    def write(self, v, w: Writer) -> None:
        w.bool(v is not None)
        if v is not None:
            self.codec.write(v, w)


class OptVarInt:
    """OPTIONAL_VAR_INT: 0 — пусто, иначе значение + 1 (buf.rs:430)."""

    @classmethod
    def read(cls, r: Reader) -> Optional[int]:
        v = r.varint()
        return None if v == 0 else v - 1

    @classmethod
    def write(cls, v: Optional[int], w: Writer) -> None:
        w.varint(0 if v is None else v + 1)


class VarVec3i:
    """Vec3i.STREAM_CODEC: три VarInt (buf.rs:441)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, int, int]:
        return r.varint(), r.varint(), r.varint()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        x, y, z = _xyz(v)
        w.varint(x)
        w.varint(y)
        w.varint(z)


class Vec3d:
    """Vec3.STREAM_CODEC: три double (buf.rs:453)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[float, float, float]:
        return r.f64(), r.f64(), r.f64()

    @classmethod
    def write(cls, v, w: Writer) -> None:
        x, y, z = _xyz(v)
        w.f64(x)
        w.f64(y)
        w.f64(z)


class Pos:
    """BlockPos.STREAM_CODEC (buf.rs:465)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, int, int]:
        return unpack_block_pos(r.i64())

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.i64(pack_block_pos(v))


class ChunkPos:
    """ChunkPos: x в младших 32 битах, z в старших (buf.rs:487)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, int]:
        v = r.i64()
        return _to_i32(v), _to_i32(v >> 32)

    @classmethod
    def write(cls, v, w: Writer) -> None:
        w.i64(_to_i64((int(v[0]) & 0xFFFF_FFFF) | (int(v[1]) << 32)))


class SectionPos:
    """SectionPos: x (22), z (22), y (20) бит (buf.rs:498)."""

    @classmethod
    def read(cls, r: Reader) -> Tuple[int, int, int]:
        v = r.i64()
        return (
            _to_i32(v >> 42),
            _to_i32(_to_i64((v << 44) & _U64) >> 44),
            _to_i32(_to_i64((v << 22) & _U64) >> 42),
        )

    @classmethod
    def write(cls, v, w: Writer) -> None:
        x, y, z = _xyz(v)
        packed = (
            ((int(x) & 0x3F_FFFF) << 42)
            | ((int(z) & 0x3F_FFFF) << 20)
            | (int(y) & 0xF_FFFF)
        )
        w.i64(_to_i64(packed))


class BitSet:
    """java.util.BitSet как VarInt + байты (buf.rs:517)."""

    @classmethod
    def read(cls, r: Reader) -> bytearray:
        return bytearray(r.byte_array(r.remaining()))

    @classmethod
    def write(cls, v, w: Writer) -> None:
        raw = bytes(v)
        length = 0
        for i in range(len(raw) - 1, -1, -1):
            if raw[i] != 0:
                length = i + 1
                break
        w.byte_array(raw[:length])


def bit(bitset: Sequence[int], i: int) -> bool:
    index = i // 8
    if index < 0 or index >= len(bitset):
        return False
    return (bitset[index] >> (i % 8)) & 1 != 0


def set_bit(bitset: bytearray, i: int) -> None:
    index = i // 8
    while len(bitset) <= index:
        bitset.append(0)
    bitset[index] |= 1 << (i % 8)


class LpVec3:
    """Низкоточная скорость Vec3.LP_STREAM_CODEC (buf.rs:538)."""

    @staticmethod
    def _unpack(v: int) -> float:
        return min(float(v & 32767), 32766.0) * 2.0 / 32766.0 - 1.0

    @staticmethod
    def _pack(v: float) -> int:
        return _to_u64(_round_away((v * 0.5 + 0.5) * 32766.0))

    @staticmethod
    def _sanitize(v: float) -> float:
        if math.isnan(v):
            return 0.0
        return min(max(v, -1.717_986_918_3e10), 1.717_986_918_3e10)

    @classmethod
    def quantize(cls, v) -> Tuple[float, float, float]:
        w = Writer()
        cls.write(v, w)
        return cls.read(Reader(w.data))

    @classmethod
    def read(cls, r: Reader) -> Tuple[float, float, float]:
        lowest = r.u8()
        if lowest == 0:
            return 0.0, 0.0, 0.0
        middle = r.u8()
        highest = r.u32()
        buffer = (highest << 16) | (middle << 8) | lowest
        scale = lowest & 3
        if lowest & 4 == 4:
            scale |= (r.varint() & _U32) << 2
        s = float(scale)
        return (
            cls._unpack(buffer >> 3) * s,
            cls._unpack(buffer >> 18) * s,
            cls._unpack(buffer >> 33) * s,
        )

    @classmethod
    def write(cls, v, w: Writer) -> None:
        x, y, z = (_xyz(v))
        x = cls._sanitize(float(x))
        y = cls._sanitize(float(y))
        z = cls._sanitize(float(z))
        length = max(abs(x), abs(y), abs(z))
        if length < 3.051_944_088_384_301e-5:
            w.u8(0)
            return
        scale = int(math.ceil(length))
        partial = (scale & 3) != scale
        markers = (scale & 3) | 4 if partial else scale
        s = float(scale)
        buffer = (
            markers
            | (cls._pack(x / s) << 3)
            | (cls._pack(y / s) << 18)
            | (cls._pack(z / s) << 33)
        ) & _U64
        w.u8(buffer & 0xFF)
        w.u8((buffer >> 8) & 0xFF)
        w.i32(_to_i32(buffer >> 16))
        if partial:
            w.varint(_to_i32(scale >> 2))


# ── PacketFrame / кадрирование (frame.rs) ────────────────────────────
#
# Портируется только несжатый путь: length-prefix (VarInt, ≤ 3 байта)
# + тело пакета (id VarInt + payload). Сжатие живёт в compression.rs.

@dataclass(frozen=True)
class PacketFrame:
    """Один кадр: id пакета и его payload (без длины)."""

    id: int
    payload: bytes

    def to_bytes(self) -> bytes:
        return write_packet_frame(self.id, self.payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PacketFrame":
        packet_id, payload = read_packet_frame(data)
        return cls(packet_id, payload)


def frame_header(data: bytes) -> Optional[Tuple[int, int]]:
    """Длина префикса и длина кадра, если префикс уже пришёл (frame.rs:60).

    Возвращает None, если байтов префикса пока не хватает.
    """
    length = 0
    for i in range(3):  # frame.rs:63 — VarInt21: не больше трёх байт
        if i >= len(data):
            return None
        b = data[i]
        length |= (b & 0x7F) << (7 * i)
        if b & 0x80 == 0:
            if length == 0:
                # frame.rs:71 — пустой кадр это ошибка, а не пустой пакет.
                raise ProtocolError("Frame length cannot be zero")
            return i + 1, length
    raise ProtocolError("length wider than 21 bits")


def write_packet_frame(
    packet_id: int,
    payload: bytes | bytearray | memoryview = b"",
) -> bytes:
    """Собрать кадр: length VarInt + id VarInt + payload (frame.rs:51)."""
    body = bytearray()
    write_varint(body, packet_id)
    body += bytes(payload)
    if len(body) > MAX_FRAME:
        raise ProtocolError(f"packet too large: {len(body)} bytes")
    out = bytearray()
    write_varint(out, len(body))
    out += body
    return bytes(out)


def read_packet_frame(data: bytes | bytearray) -> Tuple[int, bytes]:
    """Разобрать один кадр в (id, payload) (frame.rs:60 + buf.rs Reader)."""
    raw = bytes(data)
    header = frame_header(raw)
    if header is None:
        raise ProtocolError("incomplete frame header")
    start, length = header
    if len(raw) < start + length:
        raise ProtocolError(
            f"incomplete frame: need {start + length} bytes, {len(raw)} left"
        )
    body = raw[start:start + length]
    r = Reader(body)
    packet_id = r.varint()
    return packet_id, r.rest()
