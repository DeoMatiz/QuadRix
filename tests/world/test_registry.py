#!/usr/bin/env python3
"""Tests for the BlockRegistry port – block-registry.nbt loading and lookup."""

from quadrix.world.registry import BlockRegistry, BlockStateId


def test_import_ok():
    """Verify the module imports cleanly."""
    import quadrix.world.registry  # noqa: F41


def test_load_real_nbt():
    """Load the real block-registry.nbt and verify basic shape."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    # Must have a reasonable number of states (vanilla 1.21 has ~35k)
    assert r.len() > 0, "Registry must have at least one state"
    assert r.len() < 1_000_000, "Registry has unrealistically many states"


def test_state_id_zero_is_air():
    """State ID 0 must be minecraft:air (vanilla guarantee)."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    s0 = r.state(BlockStateId(0))
    assert s0 is not None, "State ID 0 must exist"
    assert s0.name == "minecraft:air", (
        f"State ID 0 should be 'minecraft:air', got '{s0.name}'"
    )


def test_at_least_one_state_has_non_empty_name():
    """At least one state must have a non-empty name."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    named = [s for s in r.states if s.name]
    assert len(named) >= 1, "At least one state must have a non-empty name"


def test_default_state_lookup():
    """The default state lookup should find minecraft:air by name."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    air_id = r.default_state("minecraft:air")
    assert air_id is not None, "minecraft:air should be a default state"
    assert air_id.id == 0, (
        f"minecraft:air default ID should be 0, got {air_id.id}"
    )


def test_property_values():
    """property_values should return values for a known block."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    # grass_block has 'snowy' property (vanilla: true/false)
    vals = r.property_values("minecraft:grass_block", "snowy")
    assert len(vals) > 0, "grass_block should have snowy property values"


def test_id_lookup():
    """The id() method should find a state by its properties."""
    r = BlockRegistry.load(
        "H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt"
    )
    # stone has no properties, but we can look up by name via default_state
    stone_id = r.default_state("minecraft:stone")
    assert stone_id is not None, "stone should be a default state"
    # Look up via the id() method using the state
    state = r.state(stone_id)
    assert state is not None, "stone state should exist"
    found_id = r.id(state)
    assert found_id is not None, "id() should find the state again"
    assert found_id.id == stone_id.id, (
        f"id() returned {found_id.id}, expected {stone_id.id}"
    )