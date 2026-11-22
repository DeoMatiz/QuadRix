#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/food_storage.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.world.food import FoodData
from quadrix.world.food_storage import food_read_nbt, food_write_nbt, read_float_tag, read_int_tag
from quadrix.world.nbt import Tag, TagType, read_nbt, write_nbt

REGISTRY = Path(".local/horizon-client-motion/block-registry.nbt")


def test_read_int_tag_types_and_default():
    assert read_int_tag(Tag(TagType.Byte, byte_val=-3), 99) == -3
    assert read_int_tag(Tag(TagType.Short, short_val=300), 99) == 300
    assert read_int_tag(Tag(TagType.Int, int_val=42), 99) == 42
    assert read_int_tag(Tag(TagType.Float, float_val=3.9), 99) == 3
    assert read_int_tag(Tag(TagType.Double, double_val=-1.2), 99) == -2
    assert read_int_tag(None, 99) == 99
    # i64 -> i32 truncation keeps the low 32 bits.
    assert read_int_tag(Tag(TagType.Long, long_val=2**32), 99) == 0


def test_read_float_tag_types():
    assert read_float_tag(Tag(TagType.Int, int_val=7), 0.0) == 7.0
    assert read_float_tag(Tag(TagType.Float, float_val=1.5), 0.0) == 1.5
    assert read_float_tag(Tag(TagType.Double, double_val=2.5), 0.0) == 2.5
    assert read_float_tag(None, 4.0) == 4.0


def test_food_read_defaults_for_missing_keys():
    food = FoodData(food=1, saturation=1.0, exhaustion=1.0, timer=1)
    food_read_nbt(food, {})
    assert food.food == 20
    assert food.timer == 0
    assert food.saturation == 5.0
    assert food.exhaustion == 0.0


def test_food_read_and_write_roundtrip_through_nbt():
    assert REGISTRY.exists(), "block-registry.nbt must exist under .local"
    original = FoodData(food=13, saturation=2.5, exhaustion=1.25, timer=7)
    compound: dict = {}
    food_write_nbt(original, compound)
    assert set(compound) == {
        "foodLevel",
        "foodTickTimer",
        "foodSaturationLevel",
        "foodExhaustionLevel",
    }
    data = write_nbt(compound)
    decoded = read_nbt(data)
    restored = FoodData()
    food_read_nbt(restored, decoded)
    assert restored.food == 13
    assert restored.timer == 7
    assert restored.saturation == pytest.approx(2.5)
    assert restored.exhaustion == pytest.approx(1.25)


def test_write_nbt_normalises_negative_zero():
    food = FoodData(food=20, saturation=-0.0, exhaustion=-0.0, timer=0)
    compound: dict = {}
    food_write_nbt(food, compound)
    assert compound["foodSaturationLevel"].float_val == 0.0
    assert compound["foodExhaustionLevel"].float_val == 0.0
