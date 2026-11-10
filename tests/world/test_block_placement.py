#!/usr/bin/env python3
"""[QuadRix] Тесты для quadrix.world.block_placement.

Порт правил player-facing установки блоков:
``level/place.rs``, ``level/mod.rs``, ``block_survival.rs`` и примитивов
``worldgen/block_placement.rs``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.core.geometry import BlockPos, Direction, Vec3
from quadrix.items.items import ItemStack
from quadrix.world.collision.block_collision import default_collision_registry
from quadrix.world.block_placement import (
    HORIZONTAL,
    BlockPlacement,
    Moss,
    PlacementContext,
    can_place_block,
    from_y_rot,
    get_placement_state,
    is_replaceable,
    is_solid,
    relative,
    rotation_segment,
)
from quadrix.world.registry import BlockRegistry

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / ".local"
    / "horizon-client-motion"
    / "block-registry.nbt"
)


# ---------------------------------------------------------------------------
# FakeWorld и фикстуры
# ---------------------------------------------------------------------------

class FakeWorld:
    """Мир с одним блоком-воздухом по умолчанию (порт ``FeatureWorld``)."""

    def __init__(self, air, blocks=None):
        self.air = air
        self.blocks = dict(blocks or {})
        self.writes = []

    def get_block(self, position):
        return self.blocks.get(tuple(position), self.air)

    def set_block(self, position, state, flags=0):
        self.blocks[tuple(position)] = state
        self.writes.append((tuple(position), state, flags))
        return True


@pytest.fixture(scope="module")
def registry() -> BlockRegistry:
    return BlockRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def placement(registry) -> BlockPlacement:
    return BlockPlacement(registry, collision=default_collision_registry(registry))


def _ctx(face: Direction = Direction.UP, yaw: float = 0.0, **overrides) -> PlacementContext:
    base = dict(
        pos=BlockPos(0, 64, 0),
        hit_pos=BlockPos(0, 63, 0),
        face=face,
        hit=Vec3(0.5, 64.0, 0.5),
        inside=False,
        yaw=yaw,
        pitch=0.0,
        sneaking=False,
        item="minecraft:stone",
        replace_clicked=False,
    )
    base.update(overrides)
    return PlacementContext(**base)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

def test_place_on_solid_support_returns_true(registry, placement):
    """Воздух в (0,64,0), камень под ним → ставить можно."""
    air = registry.default_state("minecraft:air")
    stone = registry.default_state("minecraft:stone")
    world = FakeWorld(air, {(0, 63, 0): stone})

    assert can_place_block(world, stone, (0, 64, 0), _ctx(), placement=placement) is True


def test_occupied_target_returns_false(registry, placement):
    """Камень уже в (0,64,0) → позиция занята, ставить нельзя."""
    air = registry.default_state("minecraft:air")
    stone = registry.default_state("minecraft:stone")
    world = FakeWorld(air, {(0, 64, 0): stone, (0, 63, 0): stone})

    assert can_place_block(world, stone, (0, 64, 0), _ctx(), placement=placement) is False


def test_is_replaceable_air_grass_stone(registry):
    """is_replaceable: воздух/трава/вода — да, камень — нет."""
    air = registry.state(registry.default_state("minecraft:air"))
    tall_grass = registry.state(registry.default_state("minecraft:tall_grass"))
    stone = registry.state(registry.default_state("minecraft:stone"))

    assert is_replaceable(air) is True
    assert is_replaceable(tall_grass) is True
    assert is_replaceable("minecraft:water") is True
    assert is_replaceable(stone) is False
    assert is_replaceable("minecraft:stone") is False


def test_cannot_place_with_air_below(registry, placement):
    """Под целью воздух → блок не выживет, ставить нельзя.

    Проверяем на факеле (``CenterBelow``): у камня правило ``Always``,
    он выживает в любом месте (block_survival.rs).
    """
    air = registry.default_state("minecraft:air")
    torch = registry.default_state("minecraft:torch")
    world = FakeWorld(air)  # (0,63,0) тоже воздух

    assert placement.can_survive(world, torch, (0, 64, 0)) is False
    assert can_place_block(world, torch, (0, 64, 0), _ctx(), placement=placement) is False


def test_place_on_solid_surface_far_away(registry, placement):
    """Твёрдая поверхность в (5,69,5) → ставить в (5,70,5) можно."""
    air = registry.default_state("minecraft:air")
    stone = registry.default_state("minecraft:stone")
    world = FakeWorld(air, {(5, 69, 5): stone})

    assert can_place_block(world, stone, (5, 70, 5), placement=placement) is True


def test_get_placement_state_oak_log_axis(registry):
    """Настоящие данные: oak_log получает axis по грани клика."""
    log = ItemStack("minecraft:oak_log", 1)

    up = get_placement_state(log, _ctx(face=Direction.UP), registry=registry)
    assert up is not None
    up_state = registry.state(up)
    assert up_state.name == "minecraft:oak_log"
    assert up_state.properties.get("axis") == "y"

    east = get_placement_state(log, _ctx(face=Direction.EAST), registry=registry)
    assert east is not None
    assert registry.state(east).properties.get("axis") == "x"

    # Не блоковый предмет → состояния нет.
    assert get_placement_state(ItemStack("minecraft:stick", 1), _ctx(), registry=registry) is None


def test_is_solid_real_collision(registry, placement):
    """Настоящая collision-форма: камень солиден, воздух — нет."""
    air = registry.default_state("minecraft:air")
    stone = registry.default_state("minecraft:stone")

    assert placement.is_solid(stone) is True
    assert placement.is_solid(air) is False
    assert is_solid(stone, registry=registry) is True


def test_relative_and_horizontal_and_moss(registry):
    """Примитивы worldgen/block_placement.rs: relative/HORIZONTAL/Moss."""
    assert relative((1, 2, 3), Direction.UP) == (1, 3, 3)
    assert relative((0, 0, 0), Direction.WEST) == (-1, 0, 0)
    assert HORIZONTAL == (
        Direction.NORTH,
        Direction.EAST,
        Direction.SOUTH,
        Direction.WEST,
    )

    moss = Moss(bottom=True, sides=(1, 0, 2, 0))
    assert moss.has_faces() is True
    assert Moss(bottom=False, sides=(0, 0, 0, 0)).has_faces() is False
    # base-3 код: bottom=1, sides 1,0,2,0 → 1*3^4 + 1*3^3 + 0 + 2*3 + 0 = 114
    assert moss.code() == 114

    assert from_y_rot(0.0) == Direction.SOUTH
    assert from_y_rot(90.0) == Direction.WEST
    assert rotation_segment(0.0) == 0
