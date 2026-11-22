#!/usr/bin/env python3
"""[QuadRix] Living item-blocking dispatch around direction/component reductions.

Port of horizon/crates/horizon-world/src/item_blocking.rs (Minecraft 26.3).
"""

from __future__ import annotations

from typing import Optional, Protocol

from quadrix.core.geometry import Vec3
from quadrix.world.view_direction import BLOCKING_FALLBACK_ANGLE, blocking_angle

__all__ = ["ItemBlockingWorld", "apply"]


class ItemBlockingWorld(Protocol):
    """``ItemBlockingWorld`` (item_blocking.rs:4)."""

    def blocking_item(self):
        ...

    def component(self, item):
        ...

    def bypasses_component(self, component) -> bool:
        ...

    def direct_entity(self):
        ...

    def is_arrow(self, entity) -> bool:
        ...

    def pierce_level(self, arrow) -> int:
        ...

    def source_position(self) -> Optional[Vec3]:
        ...

    def head_yaw(self) -> float:
        ...

    def position(self) -> Vec3:
        ...

    def resolve(self, component, damage: float, angle: float) -> float:
        ...

    def level(self):
        ...

    def used_hand(self):
        ...

    def hurt_blocking_item(self, component, level, item, hand, blocked: float) -> None:
        ...

    def source_is_projectile(self) -> bool:
        ...

    def is_living(self, entity) -> bool:
        ...

    def block_using_item(self, attacker, damage: float, fully_blocked: bool) -> None:
        ...


def apply(world: ItemBlockingWorld, damage: float) -> float:
    """``apply`` (item_blocking.rs:46)."""
    if damage <= 0.0:
        return 0.0
    item = world.blocking_item()
    if item is None:
        return 0.0
    component = world.component(item)
    if component is None:
        return 0.0
    if world.bypasses_component(component):
        return 0.0
    entity = world.direct_entity()
    if entity is not None:
        if world.is_arrow(entity) and world.pierce_level(entity) > 0:
            return 0.0
    source = world.source_position()
    if source is not None:
        yaw = world.head_yaw()
        position = world.position()
        angle = blocking_angle(source, position, yaw)
    else:
        angle = BLOCKING_FALLBACK_ANGLE
    blocked = world.resolve(component, damage, angle)
    level = world.level()
    hand = world.used_hand()
    world.hurt_blocking_item(component, level, item, hand, blocked)
    if blocked > 0.0 and not world.source_is_projectile():
        entity = world.direct_entity()
        if entity is not None and world.is_living(entity):
            world.block_using_item(entity, damage, blocked >= damage)
    return blocked
