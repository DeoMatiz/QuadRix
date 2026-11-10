#!/usr/bin/env python3
"""[QuadRix] Тесты ``quadrix.world.world_ray`` (порт world_ray.rs).

Проверяются DDA-порядок вокселей, попадания block/fluid, режимы формы,
interaction-грань, ошибки бюджета и fall-reset формы. Один тест читает
реальные ``.local/horizon-client-collision`` (stone = полный куб).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from quadrix.core.geometry import BlockHit, BlockPos, Direction, Vec3
from quadrix.world import world_ray as wr
from quadrix.world.collision.block_collision import VoxelShape, collision_shape
from quadrix.world.registry import load_registry

STONE = "minecraft:stone"
AIR = "minecraft:air"
EMPTY_FLUID: Tuple[str, bool] = ("empty", False)


# ---------------------------------------------------------------------------
# Фейковый мир: словари позиция → состояние, состояние → форма
# ---------------------------------------------------------------------------


@dataclass
class FakeWorld:
    blocks: Dict[Tuple[int, int, int], Any] = field(default_factory=dict)
    fluids: Dict[Tuple[int, int, int], Tuple[str, bool]] = field(
        default_factory=dict
    )
    shapes: Dict[Any, VoxelShape] = field(default_factory=dict)
    outlines: Dict[Any, VoxelShape] = field(default_factory=dict)
    interactions: Dict[Any, VoxelShape] = field(default_factory=dict)
    queries: int = 0

    def block_state(self, p: BlockPos) -> Any:
        self.queries += 1
        return self.blocks.get((p.x, p.y, p.z), AIR)

    def fluid_state(self, p: BlockPos) -> Tuple[str, bool]:
        return self.fluids.get((p.x, p.y, p.z), EMPTY_FLUID)

    def block_shape(
        self, state: Any, p: BlockPos, mode: wr.RayBlockMode
    ) -> VoxelShape:
        if mode is wr.RayBlockMode.OUTLINE and state in self.outlines:
            return self.outlines[state]
        return self.shapes.get(state, VoxelShape.empty())

    def interaction_shape(self, state: Any, p: BlockPos) -> VoxelShape:
        return self.interactions.get(state, VoxelShape.empty())

    def fluid_is_source(self, state: Tuple[str, bool]) -> bool:
        return bool(state[1])

    def fluid_is_empty(self, state: Tuple[str, bool]) -> bool:
        return state[0] == "empty"

    def fluid_is_water(self, state: Tuple[str, bool]) -> bool:
        return state[0] == "water"

    def fluid_shape(self, state: Tuple[str, bool], p: BlockPos) -> VoxelShape:
        return VoxelShape.block() if state[0] != "empty" else VoxelShape.empty()


def slab_bottom() -> VoxelShape:
    """Плита [0,0,0]..[1,0.5,1] (нижняя половина)."""
    return VoxelShape.from_grid(
        [[0.0, 1.0], [0.0, 0.5, 1.0], [0.0, 1.0]], [True, False]
    )


def east_half() -> VoxelShape:
    """Восточная половина блока x ∈ [0.5, 1]."""
    return VoxelShape.from_grid(
        [[0.0, 0.5, 1.0], [0.0, 1.0], [0.0, 1.0]], [False, True]
    )


@pytest.fixture()
def stone_world() -> FakeWorld:
    return FakeWorld(
        blocks={(0, 64, 0): STONE},
        shapes={STONE: VoxelShape.block()},
    )


# ---------------------------------------------------------------------------
# clip_world: попадание вниз в камень
# ---------------------------------------------------------------------------


def test_clip_down_hits_stone_top_face(stone_world: FakeWorld) -> None:
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 63.5, 0.5)

    result = wr.clip_world(
        stone_world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 64
    )

    assert result.miss is False
    hit = result.hit
    # BlockHit: location / direction / block / inside.
    assert hit.block == BlockPos.new(0, 64, 0)
    assert hit.direction is Direction.UP
    assert hit.inside is False
    assert hit.location == Vec3.new(0.5, 65.0, 0.5)


def test_clip_empty_world_is_miss() -> None:
    world = FakeWorld()
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 63.5, 0.5)

    result = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 64
    )

    # Rust: промах — это RayResult { miss: true, hit: ... по end }, не None.
    assert result.miss is True
    assert result.hit.block == BlockPos.new(0, 63, 0)
    assert result.hit.location == end
    assert result.hit.direction is Direction.UP
    assert result.hit.inside is False


def test_clip_shorter_than_one_block_does_not_reach(stone_world: FakeWorld) -> None:
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 65.2, 0.5)

    result = wr.clip_world(
        stone_world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 64
    )

    # Блок y=64 посещён DDA, но отрезок заканчивается выше плоскости y=65.
    assert result.miss is True
    assert stone_world.queries > 0


# ---------------------------------------------------------------------------
# DDA
# ---------------------------------------------------------------------------


def test_diagonal_dda_visits_corner_voxel() -> None:
    world = FakeWorld(
        blocks={(1, 65, 1): STONE},
        shapes={STONE: VoxelShape.block()},
    )
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(2.5, 65.5, 2.5)

    result = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 16
    )

    assert result.miss is False
    assert result.hit.block == BlockPos.new(1, 65, 1)
    assert result.hit.direction is Direction.WEST


def test_diagonal_dda_returns_nearest_block() -> None:
    world = FakeWorld(
        blocks={(0, 65, 1): STONE, (1, 65, 1): STONE},
        shapes={STONE: VoxelShape.block()},
    )
    result = wr.clip_world(
        world,
        Vec3.new(0.5, 65.5, 0.5),
        Vec3.new(2.5, 65.5, 2.5),
        wr.RayBlockMode.COLLIDER,
        wr.RayFluidMode.NONE,
        16,
    )

    # При равенстве границ x/z строгие сравнения дают приоритет Z:
    # (0,65,0) → (0,65,1) → …, значит ближе блок (0,65,1).
    assert result.hit.block == BlockPos.new(0, 65, 1)


def test_traverse_blocks_corner_order() -> None:
    visited = []
    result = wr.traverse_blocks(
        Vec3.new(0.5, 0.5, 0.5),
        Vec3.new(1.5, 1.5, 1.5),
        10,
        lambda p: visited.append(p) or None,
    )

    assert result is None
    assert visited == [
        BlockPos.new(0, 0, 0),
        BlockPos.new(0, 0, 1),
        BlockPos.new(0, 1, 1),
        BlockPos.new(1, 1, 1),
    ]


def test_traverse_budget_and_non_finite() -> None:
    with pytest.raises(wr.TraversalError) as limit:
        wr.traverse_blocks(
            Vec3.ZERO, Vec3.new(1.0, 1.0, 1.0), 1, lambda p: None
        )
    assert limit.value.kind is wr.TraversalErrorKind.VISIT_LIMIT

    with pytest.raises(wr.TraversalError) as non_finite:
        wr.traverse_blocks(
            Vec3.ZERO, Vec3.new(float("nan"), 1.0, 1.0), 1, lambda p: None
        )
    assert non_finite.value.kind is wr.TraversalErrorKind.NON_FINITE


def test_clip_world_wraps_traversal_error() -> None:
    with pytest.raises(wr.RayError) as error:
        wr.clip_world(
            FakeWorld(),
            Vec3.ZERO,
            Vec3.new(1.0, 1.0, 1.0),
            wr.RayBlockMode.COLLIDER,
            wr.RayFluidMode.NONE,
            1,
        )

    assert error.value.kind == "traversal"
    assert isinstance(error.value.error, wr.TraversalError)
    assert error.value.error.kind is wr.TraversalErrorKind.VISIT_LIMIT


# ---------------------------------------------------------------------------
# Формы: частичный блок, COLLIDER vs OUTLINE, interaction
# ---------------------------------------------------------------------------


def test_partial_slab_hit_location() -> None:
    world = FakeWorld(
        blocks={(0, 64, 0): "minecraft:stone_slab"},
        shapes={"minecraft:stone_slab": slab_bottom()},
    )
    result = wr.clip_world(
        world,
        Vec3.new(0.5, 65.5, 0.5),
        Vec3.new(0.5, 64.2, 0.5),
        wr.RayBlockMode.COLLIDER,
        wr.RayFluidMode.NONE,
        64,
    )

    assert result.miss is False
    assert result.hit.block == BlockPos.new(0, 64, 0)
    assert result.hit.direction is Direction.UP
    assert result.hit.location == Vec3.new(0.5, 64.5, 0.5)


def test_collider_and_outline_modes_differ() -> None:
    world = FakeWorld(
        blocks={(0, 64, 0): "minecraft:short_grass"},
        shapes={"minecraft:short_grass": VoxelShape.empty()},
        outlines={"minecraft:short_grass": VoxelShape.block()},
    )
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 63.5, 0.5)

    collider = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 64
    )
    outline = wr.clip_world(
        world, start, end, wr.RayBlockMode.OUTLINE, wr.RayFluidMode.NONE, 64
    )

    assert collider.miss is True
    assert outline.miss is False
    assert outline.hit.block == BlockPos.new(0, 64, 0)


def test_interaction_shape_overrides_closer_face() -> None:
    # Solid — восточная половина; interaction — полный куб. Луч идёт с северо-
    # запада вниз: interaction-грань (UP, y=65) ближе solid-грани (WEST, x=0.5).
    world = FakeWorld(
        blocks={(0, 64, 0): "minecraft:lever"},
        shapes={"minecraft:lever": east_half()},
        interactions={"minecraft:lever": VoxelShape.block()},
    )
    result = wr.clip_world(
        world,
        Vec3.new(-0.1, 65.2, 0.5),
        Vec3.new(0.9, 64.8, 0.5),
        wr.RayBlockMode.COLLIDER,
        wr.RayFluidMode.NONE,
        16,
    )

    assert result.miss is False
    # Rust меняет только direction; location остаётся от solid-хита.
    assert result.hit.direction is Direction.UP
    assert abs(result.hit.location.x - 0.5) < 1e-12
    assert abs(result.hit.location.y - 64.96) < 1e-12


# ---------------------------------------------------------------------------
# Жидкости
# ---------------------------------------------------------------------------


def test_fluid_source_only_and_none() -> None:
    world = FakeWorld(fluids={(0, 64, 0): ("water", True)})
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 63.5, 0.5)

    source = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.SOURCE_ONLY, 64
    )
    ignored = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.NONE, 64
    )

    assert source.miss is False
    assert source.hit.block == BlockPos.new(0, 64, 0)
    assert source.hit.direction is Direction.UP
    assert ignored.miss is True


def test_fluid_any_accepts_flowing_source_only_rejects() -> None:
    world = FakeWorld(fluids={(0, 64, 0): ("water", False)})
    start = Vec3.new(0.5, 65.5, 0.5)
    end = Vec3.new(0.5, 63.5, 0.5)

    source = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.SOURCE_ONLY, 64
    )
    any_fluid = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.ANY, 64
    )
    water = wr.clip_world(
        world, start, end, wr.RayBlockMode.COLLIDER, wr.RayFluidMode.WATER, 64
    )

    assert source.miss is True
    assert any_fluid.miss is False
    assert water.miss is False
    assert any_fluid.hit.block == BlockPos.new(0, 64, 0)


# ---------------------------------------------------------------------------
# Fall-reset формы
# ---------------------------------------------------------------------------


@dataclass
class FakeFallWorld:
    reset: bool = False
    player: bool = True
    portals: Tuple[wr.ResetPortal, ...] = ()
    server_level: bool = True
    delay: int = 0

    def fall_reset_tag(self, state: str) -> bool:
        return self.reset

    def entity_is_player(self, entity: object) -> bool:
        return self.player

    def is_portal(self, state: str, portal: wr.ResetPortal) -> bool:
        return portal in self.portals

    def is_server_level(self) -> bool:
        return self.server_level

    def players_nether_portal_delay(self) -> int:
        return self.delay


def test_fall_reset_shape_tag_and_portals() -> None:
    entity = object()
    # Тег сброса — полный куб независимо от сущности.
    assert wr.fall_reset_shape(FakeFallWorld(reset=True), "s", None).is_block()
    # Без сущности порталы не дают формы.
    assert not wr.fall_reset_shape(
        FakeFallWorld(portals=(wr.ResetPortal.END_PORTAL,)), "s", None
    ).is_block()
    # Игрок в end_portal — куб.
    assert wr.fall_reset_shape(
        FakeFallWorld(portals=(wr.ResetPortal.END_PORTAL,)), "s", entity
    ).is_block()
    # nether_portal на сервере только при нулевой задержке.
    portal = (wr.ResetPortal.NETHER_PORTAL,)
    assert wr.fall_reset_shape(
        FakeFallWorld(portals=portal, delay=0), "s", entity
    ).is_block()
    assert not wr.fall_reset_shape(
        FakeFallWorld(portals=portal, delay=1), "s", entity
    ).is_block()
    # Не игрок — пусто.
    assert not wr.fall_reset_shape(
        FakeFallWorld(portals=(wr.ResetPortal.END_PORTAL,), player=False), "s", entity
    ).is_block()


# ---------------------------------------------------------------------------
# Реальные данные .local
# ---------------------------------------------------------------------------


def test_real_stone_shape_from_local_data() -> None:
    registry_path = Path(".local/horizon-client-collision/block-registry.nbt")
    if not registry_path.exists():
        pytest.skip("[QuadRix] нет .local/horizon-client-collision")
    registry = load_registry(registry_path)
    stone = registry.default_state(STONE)
    assert stone is not None
    shape = collision_shape(registry, stone)
    assert shape.is_block()

    world = FakeWorld(blocks={(0, 64, 0): stone}, shapes={stone: shape})
    result = wr.clip_world(
        world,
        Vec3.new(0.5, 65.5, 0.5),
        Vec3.new(0.5, 63.5, 0.5),
        wr.RayBlockMode.COLLIDER,
        wr.RayFluidMode.NONE,
        64,
    )

    assert result.miss is False
    assert result.hit.block == BlockPos.new(0, 64, 0)
    assert result.hit.direction is Direction.UP
    assert isinstance(result.hit, BlockHit)


def test_start_inside_full_block_is_inside_hit() -> None:
    world = FakeWorld(
        blocks={(0, 64, 0): STONE},
        shapes={STONE: VoxelShape.block()},
    )
    result = wr.clip_world(
        world,
        Vec3.new(0.5, 64.5, 0.5),
        Vec3.new(0.5, 63.5, 0.5),
        wr.RayBlockMode.COLLIDER,
        wr.RayFluidMode.NONE,
        16,
    )

    assert result.miss is False
    assert result.hit.inside is True
    assert result.hit.block == BlockPos.new(0, 64, 0)
    # direction = approximate_nearest(delta).opposite(); delta вниз → UP.
    assert result.hit.direction is Direction.UP


def test_unknown_fluid_mode_raises_value_error() -> None:
    class Weird:
        pass

    with pytest.raises(ValueError):
        wr.pick_fluid(FakeWorld(), EMPTY_FLUID, Weird())  # type: ignore[arg-type]
