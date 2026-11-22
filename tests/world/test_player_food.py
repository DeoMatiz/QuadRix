#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/player_food.py."""

from __future__ import annotations

from quadrix.world.food import FoodData
from quadrix.world.player_food import (
    StoredPlayerFood,
    can_eat,
    cause_exhaustion,
    enough_food_for_manoeuvres,
)


def test_cause_exhaustion_skips_invulnerable_and_client():
    food = FoodData()
    cause_exhaustion(StoredPlayerFood(food, invulnerable=False, client_side=False, may_fly=False), 2.0)
    assert food.exhaustion == 2.0

    food2 = FoodData()
    cause_exhaustion(StoredPlayerFood(food2, invulnerable=True, client_side=False, may_fly=False), 2.0)
    assert food2.exhaustion == 0.0

    food3 = FoodData()
    cause_exhaustion(StoredPlayerFood(food3, invulnerable=False, client_side=True, may_fly=False), 2.0)
    assert food3.exhaustion == 0.0


def test_can_eat_invulnerable_or_edible_or_hungry():
    full = FoodData(food=20)
    assert not can_eat(StoredPlayerFood(full, False, False, False), always_edible=False)
    assert can_eat(StoredPlayerFood(full, False, False, False), always_edible=True)
    assert can_eat(StoredPlayerFood(full, True, False, False), always_edible=False)
    hungry = FoodData(food=19)
    assert can_eat(StoredPlayerFood(hungry, False, False, False), always_edible=False)


def test_enough_food_for_manoeuvres_uses_fly():
    full = FoodData(food=20)
    starved = FoodData(food=3)
    assert enough_food_for_manoeuvres(StoredPlayerFood(full, False, False, False))
    assert not enough_food_for_manoeuvres(StoredPlayerFood(starved, False, False, False))
    assert enough_food_for_manoeuvres(StoredPlayerFood(starved, False, False, True))
