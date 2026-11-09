"""Столкновения блоков: кэш форм из cached-collision.nbt.

Порт quadrix.world.collision.block_collision
(horizon-world/src/block_collision.rs + collision.rs).
"""

from quadrix.world.collision.block_collision import (
    CachedCollisionRegistry,
    ShulkerCollisionState,
    VoxelShape,
    block_collision_boxes,
    collision_shape,
    default_collision_registry,
    full_cube,
    load_cached_collision,
    read_collision_nbt,
)

__all__ = [
    "CachedCollisionRegistry",
    "ShulkerCollisionState",
    "VoxelShape",
    "block_collision_boxes",
    "collision_shape",
    "default_collision_registry",
    "full_cube",
    "load_cached_collision",
    "read_collision_nbt",
]
