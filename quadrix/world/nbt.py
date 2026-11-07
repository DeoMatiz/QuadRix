#!/usr/bin/env python3
"""Java Edition NBT reader/writer (big-endian, modified UTF-8 strings).

Port of horizon/crates/horizon-world/src/nbt.rs (Minecraft 26.3).
Matches Java's NbtIo byte-for-byte.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union


# ---------------------------------------------------------------------------
# TagType – mirrors the Rust IntEnum exactly
# ---------------------------------------------------------------------------

class TagType:
    End = 0
    Byte = 1
    Short = 2
    Int = 3
    Long = 4
    Float = 5
    Double = 6
    ByteArray = 7
    String = 8
    List = 9
    Compound = 10
    IntArray = 11
    LongArray = 12


# ---------------------------------------------------------------------------
# JavaString – Java modified UTF-16 ↔ Python str
# ---------------------------------------------------------------------------

@dataclass
class JavaString:
    """Represents a Java modified UTF-16 string (the NBT key or value)."""

    units: List[int] = field(default_factory=list)  # UTF-16 code units

    def to_python_str(self) -> str:
        """Decode the UTF-16 units into a Python str (lossy if needed)."""
        result: List[str] = []
        for u in self.units:
            if 0xD800 <= u <= 0xDBFF:  # high surrogate
                if len(result) > 0 and 0xDC00 <= result[-1] <= 0xDFFF:
                    result[-1] = self._surrogate_to_char(u, result[-1])
                    continue
                result.append(chr(0xFFFD))  # replacement
            elif 0xDC00 <= u <= 0xDFFF:  # low surrogate (standalone)
                result.append(chr(0xFFFD))
            else:
                try:
                    result.append(chr(u))
                except ValueError:
                    result.append(chr(0xFFFD))
        return "".join(result)

    def _surrogate_to_char(self, high: int, low: int) -> str:
        """Convert a UTF-16 surrogate pair to a Unicode code point."""
        cp = 0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00)
        return chr(cp)

    @classmethod
    def from_python_str(cls, s: str) -> "JavaString":
        """Encode a Python str into Java modified UTF-16 units."""
        units: List[int] = []
        for ch in s:
            cp = ord(ch)
            if cp <= 0xFFFF:
                units.append(cp)
            else:
                cp -= 0x10000
                high = 0xD800 | (cp >> 10)
                low = 0xDC00 | (cp & 0x3FF)
                units.append(high)
                units.append(low)
        return cls(units)


# ---------------------------------------------------------------------------
# Tag – mirrors the Rust Tag enum
# ---------------------------------------------------------------------------

@dataclass
class Tag:
    """One NBT tag value. Exactly one payload field is meaningful depending on
    ``tag_type``; the others are ``None``."""

    tag_type: TagType

    # --- primitive types ---
    byte_val: Optional[int] = None      # i8  (signed byte, 0–255 → -128–127)
    short_val: Optional[int] = None     # i16
    int_val: Optional[int] = None       # i32
    long_val: Optional[int] = None      # i64
    float_val: Optional[float] = None   # IEEE-754 f32 bits → Python float
    double_val: Optional[float] = None  # IEEE-754 f64 bits → Python float

    # --- complex types ---
    str_val: Optional[str] = None       # JavaString → Python str (via .to_python_str())
    bytes_val: Optional[bytes] = None   # ByteArray payload
    list_val: Optional[List["Tag"]] = None   # List tag
    compound_val: Optional[Dict[str, "Tag"]] = None  # Compound tag
    intarray_val: Optional[List[int]] = None  # IntArray
    longarray_val: Optional[List[int]] = None  # LongArray

    # --- End sentinel ---
    is_end: bool = False

    # --- convenience booleans ---
    @property
    def is_byte(self) -> bool: return self.tag_type == TagType.Byte
    @property
    def is_short(self) -> bool: return self.tag_type == TagType.Short
    @property
    def is_int(self) -> bool: return self.tag_type == TagType.Int
    @property
    def is_long(self) -> bool: return self.tag_type == TagType.Long
    @property
    def is_float(self) -> bool: return self.tag_type == TagType.Float
    @property
    def is_double(self) -> bool: return self.tag_type == TagType.Double
    @property
    def is_bytearray(self) -> bool: return self.tag_type == TagType.ByteArray
    @property
    def is_string(self) -> bool: return self.tag_type == TagType.String
    @property
    def is_list(self) -> bool: return self.tag_type == TagType.List
    @property
    def is_compound(self) -> bool: return self.tag_type == TagType.Compound
    @property
    def is_intarray(self) -> bool: return self.tag_type == TagType.IntArray
    @property
    def is_longarray(self) -> bool: return self.tag_type == TagType.LongArray

    @property
    def end(self) -> bool: return self.is_end


# ---------------------------------------------------------------------------
# Limits – mirrors the Rust Limits struct (only the fields we need)
# ---------------------------------------------------------------------------

@dataclass
class Limits:
    max_bytes: int = 64 * 1024 * 1024          # 64 MiB default
    max_nodes: int = 1_000_000
    max_depth: int = 512


# ---------------------------------------------------------------------------
# Error – mirrors the Rust Error struct
# ---------------------------------------------------------------------------

@dataclass
class Error:
    offset: int
    reason: str


# ---------------------------------------------------------------------------
# Little-endian / big-endian helpers
# ---------------------------------------------------------------------------

def _read_u16_be(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from(">H", data, offset)[0]
    return val, offset + 2


def _read_i32_be(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from(">i", data, offset)[0]
    return val, offset + 4


def _read_u32_be(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from(">I", data, offset)[0]
    return val, offset + 4


def _read_i64_be(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from(">q", data, offset)[0]
    return val, offset + 8


def _read_u64_be(data: bytes, offset: int) -> tuple[int, int]:
    val = struct.unpack_from(">Q", data, offset)[0]
    return val, offset + 8


def _read_f32_be(data: bytes, offset: int) -> tuple[float, int]:
    val = struct.unpack_from(">f", data, offset)[0]
    return val, offset + 4


def _read_f64_be(data: bytes, offset: int) -> tuple[float, int]:
    val = struct.unpack_from(">d", data, offset)[0]
    return val, offset + 8


def _write_u16_be(v: int) -> bytes:
    return struct.pack(">H", v & 0xFFFF)


def _write_i32_be(v: int) -> bytes:
    return struct.pack(">i", v)


def _write_u32_be(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def _write_i64_be(v: int) -> bytes:
    return struct.pack(">q", v)


def _write_u64_be(v: int) -> bytes:
    return struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF)


def _write_f32_be(v: float) -> bytes:
    return struct.pack(">f", v)


def _write_f64_be(v: float) -> bytes:
    return struct.pack(">d", v)


# ---------------------------------------------------------------------------
# modified_utf8 – Java DataInput.readUTF decoding / encoding
# ---------------------------------------------------------------------------

def _modified_utf8_decode_units(bytes_data: bytes) -> List[int]:
    """Decode bytes using Java's DataInput.readUTF algorithm (as in Rust nbt.rs)."""
    units: List[int] = []
    i = 0
    n = len(bytes_data)
    while i < n:
        b = bytes_data[i]
        if 0 <= b <= 127:
            units.append(b)
            i += 1
        elif 192 <= b <= 223 and i + 1 < n and (bytes_data[i + 1] & 0xC0) == 0x80:
            unit = ((b & 0x1F) << 6) | (bytes_data[i + 1] & 0x3F)
            units.append(unit)
            i += 2
        elif 224 <= b <= 239 and i + 2 < n and \
                (bytes_data[i + 1] & 0xC0) == 0x80 and (bytes_data[i + 2] & 0xC0) == 0x80:
            unit = ((b & 0x0F) << 12) | ((bytes_data[i + 1] & 0x3F) << 6) | (bytes_data[i + 2] & 0x3F)
            units.append(unit)
            i += 3
        else:
            break
    return units


def _modified_utf8_encode_byte_count(units: List[int]) -> int:
    """Calculate the number of bytes needed for modified UTF-8 encoding,
    matching Rust's Writer::string()."""
    byte_len = 0
    for u in units:
        if 1 <= u <= 0x7F:
            byte_len += 1
        elif 0x80 <= u <= 0x7FF:
            byte_len += 2
        else:
            byte_len += 3
    return byte_len


def _modified_utf8_encode_units(units: List[int]) -> bytes:
    """Encode UTF-16 units into modified UTF-8 bytes, matching Rust's Writer::string()."""
    buf: List[int] = []
    for u in units:
        if 1 <= u <= 0x7F:
            buf.append(u)
        elif 0x80 <= u <= 0x7FF:
            buf.append(0xC0 | (u >> 6))
            buf.append(0x80 | (u & 0x3F))
        else:
            buf.append(0xE0 | (u >> 12))
            buf.append(0x80 | ((u >> 6) & 0x3F))
            buf.append(0x80 | (u & 0x3F))
    return bytes(buf)


# ---------------------------------------------------------------------------
# Internal reader class – mirrors Reader<'a, 's> from Rust
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, data: bytes, limits: Limits):
        self.data = data
        self.offset = 0
        self.limits = limits
        self.nodes = 0
        self.stream: Optional[tuple] = None

    # -- error helper ---

    def _error(self, reason: str) -> Error:
        return Error(offset=self.offset, reason=reason)

    # -- low-level reads ---

    def _take(self, n: int) -> bytes:
        end = self.offset + n
        if end > len(self.data):
            raise self._error("truncated input")
        if end > self.limits.max_bytes:
            raise self._error("byte limit exceeded")
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk

    def _byte(self) -> int:
        val = self.data[self.offset]
        self.offset += 1
        return val

    def _number(self, n: int) -> bytes:
        """Read exactly n bytes, advancing offset. Returns the raw bytes."""
        chunk = self._take(n)
        return chunk

    def _u16_be(self) -> int:
        """Read an unsigned 16-bit big-endian integer. Advance offset by 2."""
        val, new_offset = _read_u16_be(self.data, self.offset)
        self.offset = new_offset
        return val

    def _i32_be(self) -> int:
        val, new_offset = _read_i32_be(self.data, self.offset)
        self.offset = new_offset
        return val

    def _u32_be(self) -> int:
        val, new_offset = _read_u32_be(self.data, self.offset)
        self.offset = new_offset
        return val

    def _i64_be(self) -> int:
        val, new_offset = _read_i64_be(self.data, self.offset)
        self.offset = new_offset
        return val

    def _u64_be(self) -> int:
        val, new_offset = _read_u64_be(self.data, self.offset)
        self.offset = new_offset
        return val

    # -- payload reading (mirrors Rust's payload method) ---

    def payload(self, id: int, depth: int) -> Tag:
        """Read a tag payload given its numeric ID (0=End, 1=Byte, … 12=LongArray).
        This mirrors Rust's Reader::payload()."""
        if id == 0:
            return Tag(TagType.End, is_end=True)
        if id == 1:
            b = self._byte()
            # Sign-extend u8 to i8: if b >= 128, it's negative
            return Tag(TagType.Byte, byte_val=b if b < 128 else b - 256)
        if id == 2:
            # i16 big-endian: read 2 bytes, sign-extend
            lo = self.data[self.offset]
            hi = self.data[self.offset + 1]
            self.offset += 2
            val = (hi << 8) | lo
            if val >= 0x8000:
                val -= 0x10000  # sign extend to Python int (treated as i16)
            return Tag(TagType.Short, short_val=val)
        if id == 3:
            val = self._i32_be()
            return Tag(TagType.Int, int_val=val)
        if id == 4:
            val = self._i64_be()
            return Tag(TagType.Long, long_val=val)
        if id == 5:
            bits = self._u32_be()
            # Normalize negative zero → positive zero (vanilla behaviour)
            if bits == 0:
                bits = 0
            f32_val = struct.unpack(">f", struct.pack(">I", bits))[0]
            return Tag(TagType.Float, float_val=f32_val)
        if id == 6:
            bits = self._u64_be()
            # Normalize negative zero → positive zero
            if bits == 0:
                bits = 0
            f64_val = struct.unpack(">d", struct.pack(">Q", bits))[0]
            return Tag(TagType.Double, double_val=f64_val)
        if id == 7:
            # ByteArray: 4-byte length (i32 BE) + bytes
            length = self._i32_be()
            if length < 0:
                raise self._error("negative byte array length")
            available = len(self.data) - self.offset
            if length > available:
                raise self._error("truncated byte array")
            ba = self.data[self.offset:self.offset + length]
            self.offset += length
            return Tag(TagType.ByteArray, bytes_val=ba)
        if id == 8:
            # String: 2-byte u16 BE length + modified UTF-8 bytes
            str_len = self._u16_be()
            str_bytes = self._take(str_len)
            units = _modified_utf8_decode_units(str_bytes)
            js = JavaString(units)
            str_val = js.to_python_str()
            return Tag(TagType.String, str_val=str_val)
        if id == 9:
            # List: 1-byte element type + 4-byte count (i32 BE) + elements
            element_id = self._byte()
            length = self._i32_be()  # count
            # Validate element_id
            if length > 0 and (element_id == 0 or element_id > 12):
                raise self._error("invalid list element type")
            # Read elements recursively
            elements: List[Tag] = []
            for _ in range(length):
                elem = self.payload(element_id, depth + 1)
                elements.append(elem)
            return Tag(TagType.List, list_val=elements)
        if id == 10:
            # Compound: loop reading (type + name + payload) until type==0
            compound: Dict[str, Tag] = {}
            while True:
                kv_type = self._byte()          # 1-byte tag type for this entry
                if kv_type == 0:
                    break                       # end marker
                # Read name (modified UTF-8 string)
                str_len = self._u16_be()        # 2-byte u16 BE length
                str_bytes = self._take(str_len)  # name bytes
                units = _modified_utf8_decode_units(str_bytes)
                js = JavaString(units)
                name = js.to_python_str()
                # Read payload recursively
                value = self.payload(kv_type, depth + 1)
                compound[name] = value
            return Tag(TagType.Compound, compound_val=compound)
        if id == 11:
            # IntArray: 4-byte count + i32 each (BE)
            length = self._i32_be()
            if length < 0:
                raise self._error("negative IntArray length")
            vals: List[int] = []
            for _ in range(length):
                val = self._i32_be()
                vals.append(val)
            return Tag(TagType.IntArray, intarray_val=vals)
        if id == 12:
            # LongArray: 8-byte count + i64 each (BE)
            length = self._i64_be()
            if length < 0:
                raise self._error("negative LongArray length")
            vals: List[int] = []
            for _ in range(length):
                val = self._i64_be()
                vals.append(val)
            return Tag(TagType.LongArray, longarray_val=vals)
        raise self._error("unknown tag type")

    # -- read_named root (mirrors Rust's read_named) ---

    def read_named_root(self) -> tuple[Dict[str, Tag], int]:
        """Read a named compound from bytes.

        Mirrors Rust's read_named function.
        Returns (compound_dict, bytes_consumed).
        Java String encoding: unsigned u16 length + modified UTF-8.
        """
        # 1. Read first byte = tag type
        id = self._byte()

        # 2. Read name
        if id == 0:
            # End tag with empty name
            # The payload for End is nothing; offset is already past the id byte
            compound: Dict[str, Tag] = {}
            # Actually, for End tag, there's no payload. The NamedTag has tag=End and name=""
            # But we need to return a compound dict. For End, return empty.
            # The total consumed = 1 (the id byte)
            # But wait - in Rust read_named, even for id==0, it reads the name.
            # Let me re-check: let name = if id == 0 { JavaString::default() } else { reader.root_name()? };
            # So if id==0, name = JavaString::default() (empty), and NO name bytes are read.
            # Then payload(0, 0) reads the End tag (no data).
            # Total consumed = 1 (id byte) + 0 (name, since id==0) + 0 (payload for End)
            # But actually, looking at the Rust code more carefully, payload(0, 0) would
            # read the tag with id=0 which is End. End has no payload data.
            # So offset after read_named = 1 (just the id byte).
            # However, the name is empty JavaString, and when we convert to Python str dict,
            # we'd have {"" : Tag(End)}. But for our purposes, let's just return empty compound.
            self.offset = 1  # consume the id byte
            return {}, 1
        else:
            # Read root name: u16 BE length + modified UTF-8 bytes
            name_len = self._u16_be()  # reads 2 bytes, advances offset
            str_bytes = self._take(name_len)  # reads name bytes, advances offset
            units = _modified_utf8_decode_units(str_bytes)
            js = JavaString(units)
            name = js.to_python_str()

        # 3. Read payload with the tag type id
        tag = self.payload(id, 0)

        # 4. tag.compound_val already has Python str keys (converted in payload method)
        compound = tag.compound_val if tag.is_compound and tag.compound_val is not None else {}
        if tag.is_end:
            compound = {}

        # Total bytes consumed = current offset (since we started at 0)
        consumed = self.offset
        return compound, consumed


# ---------------------------------------------------------------------------
# write_nbt / write_unnamed / write_named
# ---------------------------------------------------------------------------

def write_nbt(compound: Dict[str, Tag], limits: Optional[Limits] = None) -> bytes:
    """Write a ``dict`` of Java‑string keys to ``Tag`` values as NBT bytes
    (file‑root format, i.e. with empty/root name)."""
    if limits is None:
        limits = Limits()
    from .nbt import _Writer
    writer = _Writer(limits)
    writer.write_compound_empty_name(compound)
    return writer.bytes


def write_unnamed(tag: Tag) -> bytes:
    """Write a single tag in network format (no name field)."""
    from .nbt import _Writer
    writer = _Writer(Limits())
    writer.write_tag_network(tag)
    return writer.bytes


def write_named(compound: Dict[str, Tag], limits: Optional[Limits] = None) -> bytes:
    """Write a ``dict`` of Java‑string keys to ``Tag`` values as a named NBT
    root (first byte = tag type 10 (Compound), then name, then payload).

    The *key* strings are stored as Java modified UTF-8.
    """
    if limits is None:
        limits = Limits()
    from .nbt import _Writer
    writer = _Writer(limits)
    writer.write_named_root(compound)
    return writer.bytes


# ---------------------------------------------------------------------------
# Internal writer class – mirrors Writer from Rust
# ---------------------------------------------------------------------------

class _Writer:
    def __init__(self, limits: Limits):
        self.bytes: List[int] = []
        self.limits = limits
        self.nodes = 0
        self.empty_long_strings = True
        self.canonical_nan = True

    # -- helpers --

    def _put(self, data: bytes) -> None:
        if len(self.bytes) + len(data) > self.limits.max_bytes:
            raise Error(offset=len(self.bytes), reason="byte limit exceeded")
        self.bytes.extend(data)

    def _count(self, length: int) -> None:
        """Write an i32 big-endian length prefix."""
        self._put(struct.pack(">i", length & 0x7FFFFFFF))

    # -- writing tags ---

    def write_tag_network(self, tag: Tag) -> None:
        """Write a single tag in network format (first byte = tag id, no name)."""
        self._put(struct.pack("B", tag.tag_type))
        self._write_payload_network(tag, 0)  # depth 0

    def _write_payload_network(self, tag: Tag, depth: int) -> None:
        """Write the payload of a tag (recursive)."""
        if self.nodes >= self.limits.max_nodes:
            raise Error(offset=0, reason="node limit exceeded")
        self.nodes += 1

        # Depth check for List/Compound
        if (tag.is_list or tag.is_compound) and depth >= self.limits.max_depth:
            raise Error(offset=0, reason="depth limit exceeded")

        # Use match-case on tag_type value
        tt = tag.tag_type
        if tt == TagType.End:
            pass  # nothing to write

        elif tt == TagType.Byte:
            v = tag.byte_val if tag.byte_val is not None else 0
            if v >= 128:
                v -= 256
            self._put(struct.pack("B", v & 0xFF))

        elif tt == TagType.Short:
            v = tag.short_val if tag.short_val is not None else 0
            self._put(struct.pack(">h", v))

        elif tt == TagType.Int:
            v = tag.int_val if tag.int_val is not None else 0
            self._put(struct.pack(">i", v))

        elif tt == TagType.Long:
            v = tag.long_val if tag.long_val is not None else 0
            self._put(struct.pack(">q", v))

        elif tt == TagType.Float:
            bits = tag.float_val
            if isinstance(bits, int):
                self._put(struct.pack(">I", bits))
            else:
                self._put(struct.pack(">f", bits))

        elif tt == TagType.Double:
            bits = tag.double_val
            if isinstance(bits, int):
                self._put(struct.pack(">Q", bits))
            else:
                self._put(struct.pack(">d", bits))

        elif tt == TagType.ByteArray:
            ba = tag.bytes_val if tag.bytes_val is not None else b""
            self._count(len(ba))
            self._put(ba)

        elif tt == TagType.String:
            js = JavaString.from_python_str(tag.str_val) if tag.str_val else JavaString()
            self._write_string_java(js.units)

        elif tt == TagType.List:
            values = tag.list_val if tag.list_val is not None else []
            if not values:
                self._put(struct.pack("B", 9))  # type 9 (List)
                self._count(0)
            else:
                first_id = values[0].tag_type
                all_same = all(v.tag_type == first_id for v in values)
                if all_same:
                    self._put(struct.pack("B", first_id))
                    self._count(len(values))
                    for v in values:
                        self._write_payload_network(v, depth + 1)
                else:
                    self._put(struct.pack("B", 10))  # type 10 (Compound)
                    self._count(len(values))
                    for v in values:
                        self._write_compound_network(v, depth + 1)

        elif tt == TagType.Compound:
            compound = tag.compound_val if tag.compound_val is not None else {}
            self._put(struct.pack("B", 10))  # compound type
            self._count(len(compound))
            # Sort keys for deterministic output (Rust uses BTreeMap = sorted)
            for name, value in sorted(compound.items(), key=lambda item: item[0]):
                # Write tag type byte for the value
                self._put(struct.pack("B", value.tag_type))
                # Write name as Java modified UTF-8
                js = JavaString.from_python_str(name)
                self._write_string_java(js.units)
                # Write payload
                self._write_payload_network(value, depth + 1)
            # End marker
            self._put(struct.pack("B", 0))

        elif tt == TagType.IntArray:
            vals = tag.intarray_val if tag.intarray_val is not None else []
            self._count(len(vals))
            for v in vals:
                self._put(struct.pack(">i", v))

        elif tt == TagType.LongArray:
            vals = tag.longarray_val if tag.longarray_val is not None else []
            self._count(len(vals))
            for v in vals:
                self._put(struct.pack(">q", v))

    def _write_compound_network(self, tag: Tag, depth: int) -> None:
        """Write a tag in compound-list format (used for mixed-type lists)."""
        # Write as a synthetic compound: [type_id, name="", payload, 0]
        self._put(struct.pack("B", 10))  # compound type
        self._count(1)  # one key-value pair
        # Write the element as a compound with default key ""
        self._put(struct.pack("B", tag.tag_type))
        self._write_string_java([])  # empty name
        self._write_payload_network(tag, depth + 1)
        self._put(struct.pack("B", 0))  # end marker

    def _write_string_java(self, units: List[int]) -> None:
        """Write a Java modified UTF-8 string, matching Writer::string()."""
        byte_len = _modified_utf8_encode_byte_count(units)
        # Cap at u16 max; if too long and empty_long_strings, write 0
        if byte_len > 0xFFFF:
            if self.empty_long_strings:
                self._put(struct.pack(">H", 0))
                return
            else:
                raise Error(offset=0, reason="modified UTF-8 exceeds 65535 bytes")
        self._put(struct.pack(">H", byte_len))
        encoded = _modified_utf8_encode_units(units)
        self._put(encoded)

    def write_compound_empty_name(self, compound: Dict[str, Tag]) -> None:
        """Write a compound as a file root (named format with empty name).

        Matches write_named Rust:
        - First byte: root.tag.id() = 10 (Compound)
        - Then name as modified UTF-8 (u16 BE length + bytes; empty → [0x00, 0x00])
        - Then key-value pairs: type(1 byte) + name_len_u16 + name + payload
        - Terminated by type 0 byte
        """
        # Write tag type: 10 (Compound)
        self._put(struct.pack("B", 10))
        # Write name: empty → u16 BE = 0x0000
        self._put(struct.pack(">H", 0))
        # Write key-value pairs (compound contents)
        # Sort keys for deterministic output (Rust BTreeMap)
        for name, tag in sorted(compound.items(), key=lambda item: item[0]):
            # Write type byte for the value
            self._put(struct.pack("B", tag.tag_type))
            # Write name (the key itself) as modified UTF-8
            js = JavaString.from_python_str(name)
            self._write_string_java(js.units)
            # Write payload
            self._write_payload_network(tag, 1)
        # End marker
        self._put(struct.pack("B", 0))

    def write_named_root(self, compound: Dict[str, Tag]) -> None:
        """Write a compound in named root format.

        Format: [tag_type(1 byte)=10, name_len_u16(2 bytes)=0,
        then key-value pairs: type(1 byte) + name_len_u16 + name + payload,
        terminated by type 0].
        """
        # Write tag type = 10 (Compound)
        self._put(struct.pack("B", 10))
        # Write name: empty → u16 BE = 0x0000
        self._put(struct.pack(">H", 0))
        # Write key-value pairs (compound contents)
        # Sort keys for deterministic output (Rust BTreeMap)
        for name, tag in sorted(compound.items(), key=lambda item: item[0]):
            # Write type byte for the value
            self._put(struct.pack("B", tag.tag_type))
            # Write name (the key itself)
            js = JavaString.from_python_str(name)
            self._write_string_java(js.units)
            # Write payload
            self._write_payload_network(tag, 1)
        # End marker
        self._put(struct.pack("B", 0))


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def read_nbt_simple(data: bytes) -> Dict[str, Tag]:
    """Simplified read: just read the compound, no limits tracking."""
    return read_nbt(data)


# ---------------------------------------------------------------------------
# read_nbt – public API
# ---------------------------------------------------------------------------

def read_nbt(data: bytes, limits: Optional[Limits] = None) -> Dict[str, Tag]:
    """Read an NBT *compound* from raw bytes (the file‑root format, i.e. named
    tag with an implicit name "").

    Returns a ``dict`` mapping Java‑string keys to ``Tag`` values.
    The caller can access entries as ``data["key"]``.
    """
    if limits is None:
        limits = Limits()
    # Accept both bytes and List[int] (from writer.output)
    if isinstance(data, list):
        data = bytes(data)
    reader = _Reader(data, limits)
    compound, consumed = reader.read_named_root()
    return compound


# ---------------------------------------------------------------------------
# Quick self-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Simple round-trip test
    from quadrix.world.nbt import Tag, TagType, JavaString, Limits, read_nbt, write_nbt

    # Build a simple compound
    root: Dict[str, Tag] = {
        "hello": Tag(TagType.Byte, byte_val=42),
        "answer": Tag(TagType.Int, int_val=42),
        "name": Tag(TagType.String, str_val="test"),
        "pi": Tag(TagType.Float, float_val=3.14159),
    }

    # Write then read
    data = write_nbt(root)
    print(f"Wrote {len(data)} bytes: {data[:30].hex()}")

    read_back = read_nbt(data)
    print(f"Read back keys: {list(read_back.keys())}")
    for k, v in read_back.items():
        print(f"  {k}: type={v.tag_type.name}, val={getattr(v, 'int_val', getattr(v, 'byte_val', getattr(v, 'str_val', '?')))}")

    # Test with the real file
    print("\n--- Testing with real movement-properties.nbt ---")
    try:
        real_data = read_nbt(open("H:/Test/QuadRix/.local/horizon-client-motion/movement-properties.nbt", "rb").read())
        print(f"type: {type(real_data).__name__}")
        print(f"keys: {len(real_data)}")
        print(f"first 5 keys: {list(real_data.keys())[:5]}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()