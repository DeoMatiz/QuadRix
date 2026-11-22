#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/item_durability.py.

Port of horizon-world/src/item_durability.rs.
"""

from __future__ import annotations

from quadrix.world.item_durability import (
    DurabilityStack,
    apply_damage,
    hurt_and_break,
    hurt_without_breaking,
    process_change,
    unenchanted_change,
)


class _World:
    def __init__(self, *, infinite: bool = False, enchant_change=None) -> None:
        self._infinite = infinite
        self._enchant_change = enchant_change
        self.durability_events: list[int] = []
        self.broken_events: list[tuple[int, int]] = []

    def infinite_materials(self, stack) -> bool:
        return self._infinite

    def process_enchantments(self, stack, amount: int) -> int:
        if self._enchant_change is not None:
            return self._enchant_change
        return amount

    def durability_changed(self, stack, damage: int) -> None:
        self.durability_events.append(damage)

    def broken(self, stack, copy) -> None:
        self.broken_events.append((copy.damage_(), stack.count_()))


def _stack(damage: int = 0, max_damage: int = 250, count: int = 1, **kwargs):
    return DurabilityStack(
        count=count,
        air=kwargs.pop("air", False),
        max_damage=max_damage,
        damage=damage,
        unbreakable=kwargs.pop("unbreakable", False),
    )


def test_damageable_predicates():
    stack = _stack()
    assert stack.is_damageable()
    assert not stack.is_damaged()
    assert not stack.is_broken()
    assert stack.next_damage_will_break() is False

    assert not _stack(unbreakable=True).is_damageable()
    assert not _stack(max_damage=None).is_damageable()
    assert not _stack(air=True).is_damageable()
    assert not _stack(count=0).is_damageable()


def test_damage_is_clamped_and_broken_detection():
    stack = _stack(damage=300)
    assert stack.damage_() == 250
    assert stack.is_broken()
    near = _stack(damage=249)
    assert near.next_damage_will_break()
    near.set_damage(-10)
    assert near.damage_() == 0


def test_grow_and_shrink_wrap_like_i32():
    stack = _stack()
    stack.grow(5)
    assert stack.count_() == 6
    stack.shrink(100)
    # The raw count wraps/truncates, but an empty stack reports zero.
    assert stack.count == -94
    assert stack.count_() == 0


def test_process_change_respects_infinite_materials_and_enchantments():
    stack = _stack()
    assert process_change(stack, _World(infinite=True), 3, True) == 0
    # Creative-only infinite materials do not apply to non-server players.
    assert process_change(stack, _World(infinite=True), 3, False) == 3
    assert process_change(stack, _World(enchant_change=1), 3, True) == 1
    # Non-positive amounts are returned untouched.
    assert process_change(stack, _World(), -2, True) == -2
    # Non-damageable stacks never change.
    assert process_change(_stack(unbreakable=True), _World(), 5, True) == 0


def test_unenchanted_change_truncates_toward_zero():
    assert unenchanted_change(3) == 3
    assert unenchanted_change(-3.9) == -3
    assert unenchanted_change(0) == 0


def test_hurt_and_break_breaks_at_max_damage():
    stack = _stack(damage=249, count=2)
    world = _World()
    hurt_and_break(stack, world, 1, True)
    assert stack.count == 1
    assert world.durability_events == [250]
    assert world.broken_events == [(250, 1)]


def test_hurt_and_break_leaves_stack_intact_below_max():
    stack = _stack(damage=10)
    world = _World()
    hurt_and_break(stack, world, 5, True)
    assert stack.damage_() == 15
    assert stack.count == 1
    assert world.broken_events == []


def test_hurt_without_breaking_clamps_to_max_minus_one():
    stack = _stack(damage=249)
    world = _World()
    hurt_without_breaking(stack, world, 1)
    assert stack.damage_() == 249
    assert stack.count == 1
    assert world.broken_events == []
    assert world.durability_events == [249]


def test_apply_damage_notifies_before_shrink_and_breaks():
    stack = _stack(damage=0, count=1)
    world = _World()
    apply_damage(stack, world, 250, True)
    assert world.durability_events == [250]
    assert stack.count == 0
    assert world.broken_events == [(250, 0)]
    assert stack.is_empty()