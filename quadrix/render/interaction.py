#!/usr/bin/env python3
"""[QuadRix] Клиентское взаимодействие: raytrace клика по блокам (Gameplay PART 2).

Связывает уже портированные части в один путь «клик → попадание»:

    * ``quadrix/world/world_ray.py``          — ``clip``/``ClipContext``
      (порт ``horizon-world/src/world_ray.rs``);
    * ``quadrix/world/collision/block_collision.py`` — форма столкновения
      (порт ``block_collision.rs``, ``shape.rs``).

Rust-эталон пути (``horizon-client/src/game.rs``):

    * ``Game::reach`` / ``Player.blockInteractionRange`` — дальность 4.5
      (survival) / 5.0 (creative);
    * ``Game::aim`` — луч из глаз игрока по направлению взгляда
      (``GameRenderer.pick``/``Minecraft.hitResult``);
    * ``Game::pick`` — ``clip`` по блоку вдоль луча.

Здесь нет самого ``Game``: адаптер :class:`BlockRayWorld` реализует трейт
``RayWorld`` поверх плоского мира-заглушки QuadRix (``FlatWorld``) и реестра
блоков из ``.local``. Жидкостей в плоском мире нет — ``fluid_*`` отвечают
«пусто» (как и ``RayFluidMode::NONE`` в клипе клика).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quadrix.core.geometry import BlockPos, Vec3
from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    VoxelShape,
    collision_shape,
    default_collision_registry,
)
from quadrix.world.registry import BlockRegistry
from quadrix.world.world_ray import (
    ClipContext,
    BlockHitResult,
    RayBlockMode,
    clip,
)

__all__ = [
    "REACH_SURVIVAL",
    "REACH_CREATIVE",
    "reach_for",
    "BlockRayWorld",
    "pick_block",
    "clip_result",
]

#: ``Entity.getBlockInteractionRange`` в survival (4.5 блока).
REACH_SURVIVAL: float = 4.5
#: То же в creative (5.0 блока).
REACH_CREATIVE: float = 5.0


def reach_for(creative: bool) -> float:
    """Дальность клика по блоку: creative 5.0, survival 4.5.

    ``Player.blockInteractionRange`` (game.rs): creative-игрок дотягивается
    на полблока дальше.
    """
    return REACH_CREATIVE if creative else REACH_SURVIVAL


@dataclass
class BlockRayWorld:
    """``RayWorld`` поверх мира с именами блоков (``FlatWorld`` и т.п.).

    ``world`` должен уметь ``block(x, y, z) -> str`` (имя блока).
    ``registry``/``collision`` берутся из ``.local`` (block-registry.nbt,
    cached-collision.nbt) как в остальном клиенте.
    """

    world: Any
    registry: BlockRegistry
    collision: CachedCollisionRegistry

    def _name(self, p: BlockPos) -> str:
        return str(self.world.block(p.x, p.y, p.z))

    # -- RayWorld (world_ray.py) -----------------------------------------

    def block_state(self, p: BlockPos) -> Any:
        """Состояние блока в ``p`` (здесь — имя; реестр решает сам)."""
        return self._name(p)

    def fluid_state(self, p: BlockPos) -> str:
        """В плоском мире жидкостей нет."""
        return "empty"

    def block_shape(
        self, state: Any, p: BlockPos, mode: RayBlockMode
    ) -> VoxelShape:
        """Форма столкновения состояния (``collision_shape``)."""
        name = state if isinstance(state, str) else str(state)
        state_id = self.registry.default_state(name)
        if state_id is None:
            return VoxelShape.empty()
        return collision_shape(self.registry, state_id, self.collision)

    def interaction_shape(self, state: Any, p: BlockPos) -> VoxelShape:
        """Interaction-формы (кнопок и т.п.) в PART 2 не портированы."""
        return VoxelShape.empty()

    def fluid_is_source(self, state: Any) -> bool:
        return False

    def fluid_is_empty(self, state: Any) -> bool:
        return True

    def fluid_is_water(self, state: Any) -> bool:
        return False

    def fluid_shape(self, state: Any, p: BlockPos) -> VoxelShape:
        return VoxelShape.empty()


def clip_result(
    world: BlockRayWorld,
    start: Vec3,
    look: Vec3,
    reach: float,
) -> Optional[BlockHitResult]:
    """``clip`` по блоку вдоль луча ``start + look*t`` при ``t`` в ``0..reach``.

    ``look`` не обязан быть единичным: конец луча — ``start + look * reach``.
    """
    end = start.add_vector(look.scale(float(reach)))
    return clip(world, ClipContext(from_=start, to_=end))


def pick_block(
    world: Any,
    start: Vec3,
    look: Vec3,
    reach: float,
    *,
    registry: Optional[BlockRegistry] = None,
    collision: Optional[CachedCollisionRegistry] = None,
) -> Optional[BlockHitResult]:
    """Попадание по блоку от ``start`` вдоль ``look`` в пределах ``reach``.

    ``None`` — промах (``clip`` вернул ``None``). Реестр/кэш столкновений по
    умолчанию берутся из ``.local`` (как везде в клиенте).
    """
    if registry is None:
        from quadrix.world.block_placement import default_registry

        registry = default_registry()
    if collision is None:
        collision = default_collision_registry(registry)
    ray_world = BlockRayWorld(world=world, registry=registry, collision=collision)
    return clip_result(ray_world, start, look, reach)
