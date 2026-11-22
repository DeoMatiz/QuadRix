#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/fluid.py (port of horizon-world/src/fluid.rs)."""

from __future__ import annotations

from pathlib import Path

from quadrix.world.fluid import (
    FluidBlockBindings,
    FluidKind,
    FluidState,
    FluidStateTable,
    java_integer,
)
from quadrix.world.registry import (
    BlockProperties,
    BlockRegistry,
    BlockState,
    BlockStateId,
)

REGISTRY = Path(".local/horizon-client-motion/block-registry.nbt")


class _HeightWorld:
    def __init__(self, above: FluidState) -> None:
        self.above = above

    def fluid(self, position):
        return self.above

    def sturdy_down(self, position) -> bool:
        return False


def test_fluid_kind_family_and_mask():
    assert FluidKind.Water.same_family(FluidKind.FlowingWater)
    assert FluidKind.Lava.same_family(FluidKind.FlowingLava)
    assert not FluidKind.Water.same_family(FluidKind.Lava)
    assert FluidKind.Empty.same_family(FluidKind.Empty)
    assert not FluidKind.Water.same_family(FluidKind.Empty)
    assert FluidKind.Water.mask() == 1 << 2
    assert FluidKind.from_name("minecraft:flowing_lava") is FluidKind.FlowingLava
    assert FluidKind.from_name("minecraft:nope") is None


def test_java_integer():
    assert java_integer("15") == 15
    assert java_integer("-3") == -3
    assert java_integer("+7") == 7
    assert java_integer("x") is None
    assert java_integer("") is None
    assert java_integer("1a") is None


def test_fluid_state_new_and_flags():
    assert FluidState.new(FluidKind.Empty, 9, True) == FluidState.EMPTY()
    water = FluidState.WATER()
    assert water.is_source() and water.is_full()
    assert not FluidState(kind=FluidKind.FlowingWater, amount=4).is_source()


def test_own_height_matches_f32_source():
    # Rust: f32::from(8) / 9.0 == 0.8888889
    assert abs(FluidState.WATER().own_height() - 8.0 / 9.0) < 1e-6
    assert FluidState.EMPTY().own_height() == 0.0
    assert FluidState.EMPTY().height_at(_HeightWorld(FluidState.EMPTY()), (0, 0, 0)) == 0.0


def test_height_at_same_family_above():
    world = _HeightWorld(FluidState(kind=FluidKind.FlowingWater, amount=2))
    assert FluidState.WATER().height_at(world, (0, 5, 0)) == 1.0
    dry_above = _HeightWorld(FluidState.EMPTY())
    assert FluidState.WATER().height_at(dry_above, (0, 5, 0)) == FluidState.WATER().own_height()


def test_from_block_water_levels():
    flowing = BlockState(
        name="minecraft:water",
        properties=BlockProperties({"level": "2"}),
    )
    state = FluidState.from_block(flowing)
    assert state.kind is FluidKind.FlowingWater
    assert state.amount == 6  # 8 - 2
    assert not state.falling

    falling = BlockState(
        name="minecraft:water",
        properties=BlockProperties({"level": "8"}),
    )
    state = FluidState.from_block(falling)
    assert state.falling and state.amount == 8

    source = BlockState(name="minecraft:lava", properties=BlockProperties({"level": "0"}))
    assert FluidState.from_block(source).kind is FluidKind.Lava


def test_from_block_waterlogged_and_plants():
    grate = BlockState(
        name="minecraft:copper_grate",
        properties=BlockProperties({"waterlogged": "true"}),
    )
    assert FluidState.from_block(grate).falling is True
    slab = BlockState(
        name="minecraft:oak_slab",
        properties=BlockProperties({"waterlogged": "true"}),
    )
    assert FluidState.from_block(slab).falling is False
    air = BlockState(name="minecraft:stone", properties=BlockProperties({"waterlogged": "false"}))
    assert FluidState.from_block(air) == FluidState.EMPTY()
    kelp = BlockState(name="minecraft:kelp")
    assert FluidState.from_block(kelp) == FluidState.WATER()


def test_json_round_trip():
    text = '{"id": "minecraft:flowing_water", "properties": {"falling": "true", "level": "3"}}'
    state = FluidState.from_json(text)
    assert state.kind is FluidKind.FlowingWater
    assert state.amount == 3
    assert state.falling is True
    # to_json omits level for sources.
    source = FluidState.WATER()
    assert '"level"' not in source.to_json()
    again = FluidState.from_json(source.to_json())
    assert again == source


def test_real_registry_table_and_bindings():
    assert REGISTRY.exists(), "block-registry.nbt must exist under .local"
    registry = BlockRegistry.load(REGISTRY)
    assert registry.len() > 35000

    table = FluidStateTable.new(registry)
    water = table.get(registry.default_state("minecraft:water"))
    assert water == FluidState.WATER()
    lava = table.get(registry.default_state("minecraft:lava"))
    assert lava.kind is FluidKind.Lava and lava.amount == 8
    air = table.get(registry.default_state("minecraft:air"))
    assert air == FluidState.EMPTY()

    bindings = FluidBlockBindings.new(registry)
    assert bindings.block(FluidState.EMPTY()) == registry.default_state("minecraft:air")
    assert bindings.block(FluidState.WATER()) == registry.default_state("minecraft:water")
    # A non-source water state maps to a non-zero legacy level.
    flowing = FluidState(kind=FluidKind.FlowingWater, amount=4, falling=False)
    assert bindings.block(flowing) != registry.default_state("minecraft:water")
