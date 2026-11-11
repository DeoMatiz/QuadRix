#!/usr/bin/env python3
"""NBT reader/writer tests – port of horizon/crates/horizon-world/src/nbt.rs."""

from typing import Dict

from quadrix.world.nbt import (
    read_nbt,
    write_nbt,
    write_named,
    Error,
    NbtError,
    Tag,
    TagType,
    JavaString,
    Limits,
)


def test_read_nbt_real_file():
    """Test that read_nbt correctly parses the real movement-properties.nbt file."""
    data = read_nbt(
        open(
            "H:/Test/QuadRix/.local/horizon-client-motion/movement-properties.nbt",
            "rb",
        ).read()
    )
    # Must have at least 3 keys (blocks, DataVersion, states)
    assert len(data) >= 3, f"Expected at least 3 keys, got {len(data)}"
    # Assert on specific known keys from the real file
    assert "blocks" in data, "Expected 'blocks' key in movement properties"
    assert "DataVersion" in data, "Expected 'DataVersion' key in movement properties"
    assert "states" in data, "Expected 'states' key in movement properties"


def test_read_nbt_roundtrip():
    """Test that write_nbt + read_nbt produce consistent results."""
    root: Dict[str, Tag] = {
        "hello": Tag(TagType.Byte, byte_val=42),
        "answer": Tag(TagType.Int, int_val=42),
        "name": Tag(TagType.String, str_val="test"),
        "pi": Tag(TagType.Float, float_val=3.14159),
    }
    written = write_nbt(root)
    read_back = read_nbt(written)
    assert set(read_back.keys()) == {"hello", "answer", "name", "pi"}
    assert read_back["hello"].byte_val == 42
    assert read_back["answer"].int_val == 42
    assert read_back["name"].str_val == "test"
    assert abs(read_back["pi"].float_val - 3.14159) < 0.001


def test_tag_type_constants():
    """Test that TagType constants have the expected values."""
    assert TagType.End == 0
    assert TagType.Byte == 1
    assert TagType.Short == 2
    assert TagType.Int == 3
    assert TagType.Long == 4
    assert TagType.Float == 5
    assert TagType.Double == 6
    assert TagType.ByteArray == 7
    assert TagType.String == 8
    assert TagType.List == 9
    assert TagType.Compound == 10
    assert TagType.IntArray == 11
    assert TagType.LongArray == 12


def test_java_string_roundtrip():
    """Test that JavaString roundtrips correctly."""
    js = JavaString.from_python_str("hello")
    assert js.to_python_str() == "hello"

    js2 = JavaString.from_python_str("test med resor")
    assert js2.to_python_str() == "test med resor"

    # Empty string
    js3 = JavaString.from_python_str("")
    assert js3.to_python_str() == ""


def test_limits_defaults():
    """Test that Limits has the expected default values."""
    limits = Limits()
    assert limits.max_bytes == 64 * 1024 * 1024
    assert limits.max_nodes == 1_000_000
    assert limits.max_depth == 512


# ---------------------------------------------------------------------------
# Регрессии для write_named / read_nbt (формат NBT: type byte + name + payload)
# ---------------------------------------------------------------------------

def _roundtrip(root: Dict[str, Tag]) -> Dict[str, Tag]:
    """write_named → read_nbt; возвращает прочитанный compound."""
    written = write_named(root)
    assert isinstance(written, bytes), "write_named должен возвращать bytes"
    return read_nbt(written)


def test_write_named_returns_bytes_and_roundtrips_compound():
    """write_named → read_nbt для простого compound; результат идентичен."""
    root: Dict[str, Tag] = {"a": Tag(TagType.Int, int_val=1)}
    back = _roundtrip(root)
    assert back == root
    # Формат корня: [type=0x0a][name_len=0x0000][payload...].
    data = write_named(root)
    assert data[0] == 0x0A
    assert data[1:3] == b"\x00\x00"


def test_roundtrip_nested_compound_has_no_extra_count():
    """Вложенный Compound пишется БЕЗ лишнего type byte + count prefix.

    Ожидаемые байты (эталон NBT):
      0a 0000          root type=10, name=""
        0a 0001 61     entry type=10, name="a"
          03 0001 62   entry type=3, name="b"
            00000002   Int(2)
          00           end вложенного compound
        00             end корневого compound
    """
    root: Dict[str, Tag] = {
        "a": Tag(TagType.Compound, compound_val={"b": Tag(TagType.Int, int_val=2)})
    }
    data = write_named(root)
    assert data.hex() == "0a00000a00016103000162000000020000"
    # Round-trip возвращает ту же структуру.
    assert _roundtrip(root) == root


def test_roundtrip_list_of_int():
    """List([Int(1), Int(2)]) переживает round-trip."""
    root: Dict[str, Tag] = {
        "l": Tag(
            TagType.List,
            list_val=[Tag(TagType.Int, int_val=1), Tag(TagType.Int, int_val=2)],
        )
    }
    back = _roundtrip(root)
    assert back == root
    assert [t.int_val for t in back["l"].list_val] == [1, 2]


def test_roundtrip_empty_list_element_type_is_zero():
    """Пустой List пишет тип элемента 0 (Rust: values.first().map_or(0, Tag::id))."""
    root: Dict[str, Tag] = {"l": Tag(TagType.List, list_val=[])}
    data = write_named(root)
    # root header = 3 байта, entry type = 0x09, name_len = 2 байта, name = 1 байт,
    # значит payload начинается с индекса 7: [element_type][count(4)].
    assert data[3] == TagType.List
    assert data[7] == 0
    assert read_nbt(data)["l"].list_val == []


def test_roundtrip_arrays():
    """ByteArray / IntArray / LongArray круговая запись-чтение."""
    root: Dict[str, Tag] = {
        "ba": Tag(TagType.ByteArray, bytes_val=b"\x01\x02\xfe\xff"),
        "ia": Tag(TagType.IntArray, intarray_val=[0, 1, -2, 70000]),
        "la": Tag(TagType.LongArray, longarray_val=[0, -1, 2 ** 40]),
    }
    assert _roundtrip(root) == root


def test_roundtrip_primitives():
    """Byte/Short/Long/String round-trip; Float/Double — с допуском."""
    root: Dict[str, Tag] = {
        "b": Tag(TagType.Byte, byte_val=-5),
        "s": Tag(TagType.Short, short_val=-300),
        "i": Tag(TagType.Int, int_val=-70000),
        "l": Tag(TagType.Long, long_val=2 ** 40),
        "str": Tag(TagType.String, str_val="привет мир"),
        "f": Tag(TagType.Float, float_val=1.5),
        "d": Tag(TagType.Double, double_val=2.5),
    }
    back = _roundtrip(root)
    for key in ("b", "s", "i", "l", "str"):
        assert back[key] == root[key], key
    assert abs(back["f"].float_val - 1.5) < 1e-6
    assert abs(back["d"].double_val - 2.5) < 1e-12


def test_read_nbt_empty_bytes_raises_nbt_error():
    """read_nbt(b"") поднимает NbtError, а не IndexError/TypeError."""
    try:
        read_nbt(b"")
    except NbtError as exc:
        assert isinstance(exc, Error)
    else:
        raise AssertionError("read_nbt(b'') должен поднимать NbtError")


def test_read_nbt_unknown_tag_type_raises_nbt_error():
    """Неизвестный тип тега — NbtError, не TypeError."""
    # id=13 (не существует), пустое имя, затем payload → unknown tag type.
    try:
        read_nbt(b"\x0d\x00\x00")
    except NbtError:
        pass
    else:
        raise AssertionError("read_nbt не поднял NbtError на неизвестном типе")


def test_read_nbt_truncated_input_raises_nbt_error():
    """Обрезанный ввод поднимает NbtError (наследник Exception)."""
    good = write_named({"a": Tag(TagType.Int, int_val=1)})
    for end in range(len(good)):
        try:
            read_nbt(good[:end])
        except NbtError:
            continue
        raise AssertionError(f"префикс длиной {end} должен поднимать NbtError")


def test_error_is_a_real_exception():
    """Error/NbtError — настоящее исключение (Rust: реализует std::error::Error)."""
    assert issubclass(Error, Exception)
    assert NbtError is Error
    exc = Error(offset=3, reason="truncated input")
    assert str(exc) == "NBT at byte 3: truncated input"