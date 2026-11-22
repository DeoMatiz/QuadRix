#!/usr/bin/env python3
"""[QuadRix] Food component listener: consumption sounds, stored hunger, burp.

Port of horizon/crates/horizon-world/src/food_properties.rs (Minecraft 26.3).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from quadrix.core.geometry import Vec3
from quadrix.world.food import FoodData, f32

__all__ = [
    "FoodProperties",
    "SoundCategory",
    "ConsumptionSound",
    "FoodConsumptionWorld",
]


class SoundCategory(Enum):
    """``SoundCategory`` (food_properties.rs:18)."""

    Neutral = "neutral"
    Players = "players"


@dataclass
class FoodProperties:
    """``FoodProperties`` (food_properties.rs:5)."""

    nutrition: int
    saturation: float
    can_always_eat: bool

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FoodProperties):
            return NotImplemented
        # f32 bit comparison with NaN canonicalised (food_properties.rs:10).
        def bits(value: float) -> int:
            if value != value:
                return 0x7FC00000
            return struct.unpack("<I", struct.pack("<f", value))[0]

        return (
            self.nutrition == other.nutrition
            and bits(self.saturation) == bits(other.saturation)
            and self.can_always_eat == other.can_always_eat
        )

    def __hash__(self) -> int:
        return hash((self.nutrition, self.saturation, self.can_always_eat))

    def on_consume(
        self,
        world: "FoodConsumptionWorld",
        level,
        consume_sound,
        burp_sound,
    ) -> None:
        """``FoodProperties::on_consume`` (food_properties.rs:51)."""
        random = world.get_random()
        position = world.position()
        pitch = world.random_source(random).triangle_float(1.0, 0.4)
        world.play_sound(
            ConsumptionSound(
                level=level,
                position=position,
                sound=consume_sound,
                category=SoundCategory.Neutral,
                volume=1.0,
                pitch=pitch,
            )
        )
        if world.is_player():
            world.food_data().eat_properties(self.nutrition, self.saturation)
            position = world.position()
            pitch = f32(0.9 + f32(world.random_source(random).next_float() * f32(1.0 - 0.9)))
            world.play_sound(
                ConsumptionSound(
                    level=level,
                    position=position,
                    sound=burp_sound,
                    category=SoundCategory.Players,
                    volume=0.5,
                    pitch=pitch,
                )
            )


L = TypeVar("L")
S = TypeVar("S")


@dataclass
class ConsumptionSound:
    """``ConsumptionSound<L, S>`` (food_properties.rs:23)."""

    level: object
    position: Vec3
    sound: object
    category: SoundCategory
    volume: float
    pitch: float


class FoodConsumptionWorld(Protocol):
    """``FoodConsumptionWorld`` (food_properties.rs:31)."""

    def get_random(self):
        ...

    def random_source(self, random):
        ...

    def position(self) -> Vec3:
        ...

    def is_player(self) -> bool:
        ...

    def food_data(self) -> FoodData:
        ...

    def play_sound(self, sound: ConsumptionSound) -> None:
        ...
