#!/usr/bin/env python3
"""NBT reader/writer tests – port of horizon/crates/horizon-world/src/nbt.rs."""

from quadrix.world.nbt import read_nbt, write_nbt, Tag, TagType, JavaString, Limits


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