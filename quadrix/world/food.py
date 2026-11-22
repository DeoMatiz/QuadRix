#!/usr/bin/env python3
"""[QuadRix] Hunger, saturation, exhaustion and server-side natural regeneration.

Port of horizon/crates/horizon-world/src/food.rs (Minecraft 26.3).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

__all__ = [
    "Difficulty",
    "FoodData",
    "FoodWorld",
    "f32",
    "f32_min",
    "f32_max",
    "f32_clamp",
    "wrap_i32",
]


# ---------------------------------------------------------------------------
# f32 helpers — Rust food math is single precision
# ---------------------------------------------------------------------------

def f32(value: float) -> float:
    """Round ``value`` to the nearest IEEE-754 single."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _from_bits(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def f32_min(a: float, b: float) -> float:
    """Rust ``food.rs`` ``min`` (line 26): NaN-propagating, -0.0 aware."""
    a = float(a)
    b = float(b)
    if a != a or b != b:
        return float("nan")
    if a == 0.0 and b == 0.0:
        return _from_bits(_bits(a) | _bits(b))
    return a if a < b else b


def f32_max(a: float, b: float) -> float:
    """Rust ``food.rs`` ``max`` (line 35)."""
    a = float(a)
    b = float(b)
    if a != a or b != b:
        return float("nan")
    if a == 0.0 and b == 0.0:
        return _from_bits(_bits(a) & _bits(b))
    return a if a > b else b


def f32_clamp(value: float, lo: float, hi: float) -> float:
    """Rust ``food.rs`` ``clamp`` (line 44)."""
    value = float(value)
    if value < lo:
        return float(lo)
    return f32_min(value, hi)


def wrap_i32(value: int) -> int:
    """Rust ``i32::wrapping_add`` result reinterpretation."""
    return ((int(value) + 2**31) % 2**32) - 2**31


# ---------------------------------------------------------------------------
# Difficulty — food.rs:3
# ---------------------------------------------------------------------------

class Difficulty(Enum):
    Peaceful = "peaceful"
    Easy = "easy"
    Normal = "normal"
    Hard = "hard"


# ---------------------------------------------------------------------------
# FoodData — food.rs:9
# ---------------------------------------------------------------------------

@dataclass
class FoodData:
    food: int = 20
    saturation: float = 5.0
    exhaustion: float = 0.0
    timer: int = 0

    def eat(self, nutrition: int, saturation_modifier: float) -> None:
        """``FoodData::eat`` (food.rs:48)."""
        saturation = f32(f32(f32(float(nutrition)) * float(saturation_modifier)) * 2.0)
        self.eat_properties(nutrition, saturation)

    def eat_properties(self, nutrition: int, saturation: float) -> None:
        """``FoodData::eat_properties`` (food.rs:51)."""
        self.food = max(0, min(20, wrap_i32(int(nutrition) + self.food)))
        self.saturation = f32_clamp(
            f32(float(saturation) + self.saturation), 0.0, float(self.food)
        )

    def add_exhaustion(self, value: float) -> None:
        """``FoodData::add_exhaustion`` (food.rs:55)."""
        self.exhaustion = f32_min(f32(self.exhaustion + float(value)), 40.0)

    def has_enough_food(self) -> bool:
        """``FoodData::has_enough_food`` (food.rs:58)."""
        return float(self.food) > 6.0

    def needs_food(self) -> bool:
        """``FoodData::needs_food`` (food.rs:61)."""
        return self.food < 20

    def tick(self, world: "FoodWorld") -> None:
        """``FoodData::tick`` (food.rs:64)."""
        level = world.level(self)
        difficulty = world.difficulty(level, self)
        if self.exhaustion > 4.0:
            self.exhaustion -= 4.0
            if self.saturation > 0.0:
                self.saturation = f32_max(f32(self.saturation - 1.0), 0.0)
            elif difficulty != Difficulty.Peaceful:
                self.food = max(0, wrap_i32(self.food - 1))
        regenerate = world.natural_regeneration(level, self)
        if regenerate and self.saturation > 0.0 and world.is_hurt(self) and self.food >= 20:
            self.timer = wrap_i32(self.timer + 1)
            if self.timer >= 10:
                amount = f32_min(self.saturation, 6.0)
                world.heal(self, f32(amount / 6.0))
                self.add_exhaustion(amount)
                self.timer = 0
        elif regenerate and self.food >= 18 and world.is_hurt(self):
            self.timer = wrap_i32(self.timer + 1)
            if self.timer >= 80:
                world.heal(self, 1.0)
                self.add_exhaustion(6.0)
                self.timer = 0
        elif self.food <= 0:
            self.timer = wrap_i32(self.timer + 1)
            if self.timer >= 80:
                if (
                    world.health(self) > 10.0
                    or difficulty == Difficulty.Hard
                    or (world.health(self) > 1.0 and difficulty == Difficulty.Normal)
                ):
                    world.hurt_starvation(level, self, 1.0)
                self.timer = 0
        else:
            self.timer = 0


# ---------------------------------------------------------------------------
# FoodWorld — food.rs:110
# ---------------------------------------------------------------------------

class FoodWorld(Protocol):
    def level(self, food: FoodData):
        ...

    def difficulty(self, level, food: FoodData) -> Difficulty:
        ...

    def natural_regeneration(self, level, food: FoodData) -> bool:
        ...

    def is_hurt(self, food: FoodData) -> bool:
        ...

    def heal(self, food: FoodData, amount: float) -> None:
        ...

    def health(self, food: FoodData) -> float:
        ...

    def hurt_starvation(self, level, food: FoodData, amount: float) -> None:
        ...
