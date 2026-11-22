#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/food.py (horizon-world/src/food.rs)."""

from __future__ import annotations

import pytest

from quadrix.world.food import Difficulty, FoodData, f32_max, f32_min


class _World:
    def __init__(
        self,
        *,
        difficulty: Difficulty = Difficulty.Normal,
        natural_regeneration: bool = True,
        is_hurt: bool = True,
        health: float = 20.0,
    ) -> None:
        self._difficulty = difficulty
        self._natural_regeneration = natural_regeneration
        self._is_hurt = is_hurt
        self._health = health
        self.heals: list[float] = []
        self.starvations: list[float] = []

    def level(self, food):
        return "overworld"

    def difficulty(self, level, food):
        return self._difficulty

    def natural_regeneration(self, level, food):
        return self._natural_regeneration

    def is_hurt(self, food):
        return self._is_hurt

    def heal(self, food, amount):
        self.heals.append(amount)

    def health(self, food):
        return self._health

    def hurt_starvation(self, level, food, amount):
        self.starvations.append(amount)


def test_defaults_match_vanilla():
    food = FoodData()
    assert food.food == 20
    assert food.saturation == 5.0
    assert food.exhaustion == 0.0
    assert food.timer == 0


def test_eat_adds_nutrition_and_saturation():
    food = FoodData(food=10, saturation=0.0)
    food.eat(6, 1.2)  # saturation = 6 * 1.2 * 2 = 14.4
    assert food.food == 16
    assert food.saturation == pytest.approx(14.4)
    # saturation clamps to food level.
    food.eat_properties(20, 100.0)
    assert food.food == 20
    assert food.saturation == pytest.approx(20.0)


def test_exhaustion_clamps_at_40():
    food = FoodData()
    food.add_exhaustion(45.0)
    assert food.exhaustion == 40.0
    food.exhaustion = 39.0
    food.add_exhaustion(5.0)
    assert food.exhaustion == 40.0


def test_food_predicates():
    assert FoodData().has_enough_food()
    assert not FoodData().needs_food()
    assert not FoodData(food=6).has_enough_food()
    assert FoodData(food=19).needs_food()


def test_exhaustion_consumes_saturation_then_food():
    world = _World(difficulty=Difficulty.Normal)
    food = FoodData(food=20, saturation=10.0, exhaustion=5.0)
    food.tick(world)
    assert food.exhaustion == pytest.approx(1.0)
    assert food.saturation == pytest.approx(9.0)

    starving = FoodData(food=20, saturation=0.0, exhaustion=5.0)
    starving.tick(world)
    assert starving.food == 19

    # Peaceful never drains food.
    peaceful = FoodData(food=20, saturation=0.0, exhaustion=5.0)
    peaceful.tick(_World(difficulty=Difficulty.Peaceful))
    assert peaceful.food == 20


def test_natural_regeneration_heals_after_ten_ticks():
    world = _World(natural_regeneration=True, is_hurt=True)
    food = FoodData(food=20, saturation=5.0, exhaustion=0.0)
    for _ in range(10):
        food.tick(world)
    assert world.heals, "regeneration should heal at least once"
    assert world.heals[0] == pytest.approx(5.0 / 6.0)
    assert food.timer == 0


def test_starvation_after_eighty_ticks():
    world = _World(
        difficulty=Difficulty.Hard,
        natural_regeneration=False,
        is_hurt=False,
        health=20.0,
    )
    food = FoodData(food=0, saturation=0.0, exhaustion=0.0)
    for _ in range(80):
        food.tick(world)
    assert world.starvations == [1.0]


def test_f32_helpers_are_nan_propagating():
    nan = float("nan")
    assert f32_min(nan, 1.0) != f32_min(nan, 1.0)
    assert f32_max(1.0, nan) != f32_max(1.0, nan)
    assert f32_min(-0.0, 0.0) == -0.0
