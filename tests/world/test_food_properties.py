#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/food_properties.py."""

from __future__ import annotations

import pytest

from quadrix.core.geometry import Vec3
from quadrix.world.food import FoodData
from quadrix.world.food_properties import (
    ConsumptionSound,
    FoodProperties,
    SoundCategory,
)


class _Random:
    def triangle_float(self, center: float, radius: float) -> float:
        return 0.4

    def next_float(self) -> float:
        return 0.5


class _World:
    def __init__(self, is_player: bool) -> None:
        self._is_player = is_player
        self.food = FoodData(food=10, saturation=0.0)
        self.sounds: list[ConsumptionSound] = []

    def get_random(self):
        return "rng"

    def random_source(self, random):
        return _Random()

    def position(self) -> Vec3:
        return Vec3(0.0, 64.0, 0.0)

    def is_player(self) -> bool:
        return self._is_player

    def food_data(self) -> FoodData:
        return self.food

    def play_sound(self, sound: ConsumptionSound) -> None:
        self.sounds.append(sound)


def test_properties_equality_nan_canonicalised():
    a = FoodProperties(nutrition=4, saturation=float("nan"), can_always_eat=False)
    b = FoodProperties(nutrition=4, saturation=float("nan"), can_always_eat=False)
    assert a == b
    assert a != FoodProperties(nutrition=5, saturation=float("nan"), can_always_eat=False)


def test_player_consume_eats_and_burps():
    world = _World(is_player=True)
    props = FoodProperties(nutrition=6, saturation=7.2, can_always_eat=False)
    props.on_consume(world, "overworld", "consume", "burp")
    assert len(world.sounds) == 2
    assert world.sounds[0].category is SoundCategory.Neutral
    assert world.sounds[0].volume == 1.0
    assert world.sounds[1].category is SoundCategory.Players
    assert world.sounds[1].volume == 0.5
    assert world.food.food == 16
    assert world.food.saturation == pytest.approx(7.2)


def test_non_player_only_consumes_sound():
    world = _World(is_player=False)
    props = FoodProperties(nutrition=6, saturation=7.2, can_always_eat=False)
    props.on_consume(world, "overworld", "consume", "burp")
    assert len(world.sounds) == 1
    assert world.food.food == 10  # unchanged
