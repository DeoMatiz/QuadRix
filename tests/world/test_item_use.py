#!/usr/bin/env python3
"""[QuadRix] Тесты quadrix.world.item_use (порт item_use.rs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from quadrix.world.item_use import (
    INT32_MAX,
    INT32_MIN,
    ItemUseWorld,
    blocking_item,
    is_blocking,
    ticks_using_item,
    ticks_using_item_partial,
    wrapping_sub_i32,
)


@dataclass
class FakeWorld(ItemUseWorld[object, str]):
    """Фейковый мир с теми же хуками, что требует Rust-трейт."""

    using: bool = True
    item: object = "minecraft:shield"
    delay: Optional[int] = 5
    duration: int = 72000
    remaining: int = 71995
    remaining_virtual: int = 71995
    using_calls: int = 0
    use_item_calls: int = 0

    def using_item(self) -> bool:
        self.using_calls += 1
        return self.using

    def use_item(self) -> object:
        self.use_item_calls += 1
        return self.item

    def blocking_delay(self, item: object) -> Optional[int]:
        return self.delay

    def item_type(self, item: object) -> str:
        return "shield"

    def use_duration(self, item_type: str, item: object) -> int:
        return self.duration

    def remaining_ticks(self) -> int:
        return self.remaining

    def remaining_ticks_virtual(self) -> int:
        return self.remaining_virtual


# ---------------------------------------------------------------------------
# blocking_item / is_blocking
# ---------------------------------------------------------------------------


def test_not_using_item_returns_none_false_and_zero() -> None:
    world = FakeWorld(using=False, item="minecraft:shield", delay=5)

    assert blocking_item(world) is None
    assert is_blocking(world) is False
    # Rust: ранний выход не трогает use_item и остальные хуки.
    assert world.use_item_calls == 0
    # both calls went through using_item only
    assert world.using_calls == 2


def test_missing_blocking_delay_means_not_blocking() -> None:
    world = FakeWorld(delay=None)

    assert blocking_item(world) is None
    assert is_blocking(world) is False


def test_blocking_starts_exactly_at_delay() -> None:
    # duration 72000, remaining 71995 => elapsed 5 == delay 5
    world = FakeWorld(duration=72000, remaining=71995, delay=5)

    assert blocking_item(world) == "minecraft:shield"
    assert is_blocking(world) is True


def test_blocking_not_yet_below_delay() -> None:
    # elapsed 4 < delay 5
    world = FakeWorld(duration=72000, remaining=71996, delay=5)

    assert blocking_item(world) is None
    assert is_blocking(world) is False


def test_blocking_after_delay() -> None:
    # elapsed 100 > delay 5
    world = FakeWorld(duration=72000, remaining=71900, delay=5)

    assert blocking_item(world) == "minecraft:shield"


def test_delay_zero_blocks_immediately() -> None:
    world = FakeWorld(duration=72000, remaining=72000, delay=0)

    assert blocking_item(world) == "minecraft:shield"


def test_large_remaining_ticks_use_wrapping_subtraction() -> None:
    # elapsed = 72000 - 80000 = -8000, меньше любой положительной задержки.
    world = FakeWorld(duration=72000, remaining=80000, delay=5)

    assert blocking_item(world) is None


# ---------------------------------------------------------------------------
# ticks_using_item / ticks_using_item_partial
# ---------------------------------------------------------------------------


def test_ticks_using_item_returns_zero_when_not_using() -> None:
    world = FakeWorld(using=False, duration=72000, remaining_virtual=70000)

    assert ticks_using_item(world) == 0
    assert ticks_using_item_partial(world, 0.5) == 0.0


def test_ticks_using_item_uses_virtual_remaining() -> None:
    # duration 72000, virtual remaining 70000 => 2000 тиков
    world = FakeWorld(duration=72000, remaining_virtual=70000)

    assert ticks_using_item(world) == 2000


def test_ticks_using_item_partial_adds_fraction() -> None:
    world = FakeWorld(duration=72000, remaining_virtual=70000)

    assert ticks_using_item_partial(world, 0.25) == 2000.25
    assert isinstance(ticks_using_item_partial(world, 0.25), float)


# ---------------------------------------------------------------------------
# wrapping_sub_i32 — точное переполнение Rust
# ---------------------------------------------------------------------------


def test_wrapping_sub_i32_plain_values() -> None:
    assert wrapping_sub_i32(5, 3) == 2
    assert wrapping_sub_i32(0, 1) == -1
    assert wrapping_sub_i32(INT32_MAX, INT32_MAX) == 0


def test_wrapping_sub_i32_overflows_like_rust() -> None:
    # 2147483647 - (-1) = 2147483648 -> переполнение -> -2147483648
    assert wrapping_sub_i32(INT32_MAX, -1) == INT32_MIN
    # -2147483648 - 1 = -2147483649 -> переполнение -> 2147483647
    assert wrapping_sub_i32(INT32_MIN, 1) == INT32_MAX


def test_blocking_uses_wrapping_duration() -> None:
    # elapsed = INT32_MIN - 1 wraps to INT32_MAX, поэтому блокировка срабатывает.
    world = FakeWorld(duration=INT32_MIN, remaining=1, delay=5)

    assert blocking_item(world) == "minecraft:shield"


# ---------------------------------------------------------------------------
# default-методы трейта (query_*)
# ---------------------------------------------------------------------------


def test_query_methods_delegate_to_free_functions() -> None:
    world = FakeWorld(duration=72000, remaining=71995, remaining_virtual=71000)

    assert world.query_blocking_item() == "minecraft:shield"
    assert world.query_ticks_using_item() == 1000
