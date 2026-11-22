#!/usr/bin/env python3
"""[QuadRix] Player-specific hunger guards and virtual/direct state access.

Port of horizon/crates/horizon-world/src/player_food.rs (Minecraft 26.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quadrix.world.food import FoodData

__all__ = [
    "PlayerFoodWorld",
    "cause_exhaustion",
    "can_eat",
    "enough_food_for_manoeuvres",
    "StoredPlayerFood",
]


class PlayerFoodWorld(Protocol):
    """``PlayerFoodWorld`` (player_food.rs:3)."""

    def invulnerable_direct(self) -> bool:
        ...

    def level_is_client(self) -> bool:
        ...

    def add_exhaustion_direct(self, value: float) -> None:
        ...

    def needs_food_direct(self) -> bool:
        ...

    def enough_food_virtual(self) -> bool:
        ...

    def may_fly_virtual(self) -> bool:
        ...


def cause_exhaustion(world: PlayerFoodWorld, value: float) -> None:
    """``cause_exhaustion`` (player_food.rs:13)."""
    if not world.invulnerable_direct() and not world.level_is_client():
        world.add_exhaustion_direct(value)


def can_eat(world: PlayerFoodWorld, always_edible: bool) -> bool:
    """``can_eat`` (player_food.rs:19)."""
    return world.invulnerable_direct() or always_edible or world.needs_food_direct()


def enough_food_for_manoeuvres(world: PlayerFoodWorld) -> bool:
    """``enough_food_for_manoeuvres`` (player_food.rs:22)."""
    return world.enough_food_virtual() or world.may_fly_virtual()


@dataclass
class StoredPlayerFood:
    """``StoredPlayerFood`` (player_food.rs:27)."""

    food: FoodData
    invulnerable: bool
    client_side: bool
    may_fly: bool

    def invulnerable_direct(self) -> bool:
        return self.invulnerable

    def level_is_client(self) -> bool:
        return self.client_side

    def add_exhaustion_direct(self, value: float) -> None:
        self.food.add_exhaustion(value)

    def needs_food_direct(self) -> bool:
        return self.food.needs_food()

    def enough_food_virtual(self) -> bool:
        return self.food.has_enough_food()

    def may_fly_virtual(self) -> bool:
        return self.may_fly
