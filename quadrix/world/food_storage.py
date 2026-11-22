#!/usr/bin/env python3
"""[QuadRix] FoodData fields in a vanilla player NBT compound.

Port of horizon/crates/horizon-world/src/food_storage.rs (Minecraft 26.3).
"""

from __future__ import annotations

import math

from quadrix.world.food import FoodData, f32
from quadrix.world.nbt import Tag, TagType

__all__ = ["read_int_tag", "read_float_tag", "food_read_nbt", "food_write_nbt"]

_I32_MIN = -2_147_483_648
_I32_MAX = 2_147_483_647


def _saturate_i32(value: float) -> int:
    if math.isnan(value):
        return 0
    if value >= _I32_MAX:
        return _I32_MAX
    if value <= _I32_MIN:
        return _I32_MIN
    return int(value)


def _truncate_i32(value: int) -> int:
    """Rust ``as i32`` for an i64: keep the low 32 bits, signed."""
    return ((int(value) + 2**31) % 2**32) - 2**31


def read_int_tag(tag: "Tag | None", default: int) -> int:
    """``food_storage::int`` (food_storage.rs:6)."""
    if tag is None:
        return default
    if tag.is_byte:
        return int(tag.byte_val)
    if tag.is_short:
        return int(tag.short_val)
    if tag.is_int:
        return int(tag.int_val)
    if tag.is_long:
        return _truncate_i32(int(tag.long_val))
    if tag.is_float:
        return _saturate_i32(math.floor(float(tag.float_val)))
    if tag.is_double:
        return _saturate_i32(math.floor(float(tag.double_val)))
    return default


def read_float_tag(tag: "Tag | None", default: float) -> float:
    """``food_storage::float`` (food_storage.rs:17)."""
    if tag is None:
        return float(default)
    if tag.is_byte:
        return f32(tag.byte_val)
    if tag.is_short:
        return f32(tag.short_val)
    if tag.is_int:
        return f32(tag.int_val)
    if tag.is_long:
        return f32(tag.long_val)
    if tag.is_float:
        return float(tag.float_val)
    if tag.is_double:
        return f32(tag.double_val)
    return float(default)


def food_read_nbt(food: FoodData, compound: dict) -> None:
    """``FoodData::read_nbt`` (food_storage.rs:31).

    Missing or nonnumeric values reset each field to its native default.
    """
    food.food = read_int_tag(compound.get("foodLevel"), 20)
    food.timer = read_int_tag(compound.get("foodTickTimer"), 0)
    food.saturation = read_float_tag(compound.get("foodSaturationLevel"), 5.0)
    food.exhaustion = read_float_tag(compound.get("foodExhaustionLevel"), 0.0)


def food_write_nbt(food: FoodData, compound: dict) -> None:
    """``FoodData::write_nbt`` (food_storage.rs:40).

    Java float tag factories normalise both signed zeros to positive zero.
    """
    def float_tag(value: float) -> Tag:
        normalised = 0.0 if value == 0.0 else float(value)
        return Tag(TagType.Float, float_val=normalised)

    compound["foodLevel"] = Tag(TagType.Int, int_val=int(food.food))
    compound["foodTickTimer"] = Tag(TagType.Int, int_val=int(food.timer))
    compound["foodSaturationLevel"] = float_tag(food.saturation)
    compound["foodExhaustionLevel"] = float_tag(food.exhaustion)


# Extend FoodData with the storage helpers as methods (matches Rust impl block).
FoodData.read_nbt = lambda self, compound: food_read_nbt(self, compound)  # type: ignore[attr-defined]
FoodData.write_nbt = lambda self, compound: food_write_nbt(self, compound)  # type: ignore[attr-defined]
