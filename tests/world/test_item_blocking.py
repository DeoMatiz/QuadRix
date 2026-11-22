#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/item_blocking.py.

Port of horizon-world/src/item_blocking.rs.
"""

from __future__ import annotations

import math

import pytest

from quadrix.core.geometry import Vec3
from quadrix.world.item_blocking import apply
from quadrix.world.view_direction import BLOCKING_FALLBACK_ANGLE


class _Arrow:
    pass


class _Living:
    pass


class _World:
    def __init__(self, **overrides) -> None:
        self._blocking_item = "minecraft:shield"
        self._component = "shield_component"
        self._bypass = False
        self._direct_entity = None
        self._arrow = False
        self._pierce = 0
        self._source_position = Vec3(0.0, 0.0, 3.0)
        self._head_yaw = 0.0
        self._position = Vec3(0.0, 0.0, 0.0)
        self._blocked_amount = 4.0
        self._level = "overworld"
        self._used_hand = "MAIN_HAND"
        self._source_projectile = False
        self._living = True
        self.resolve_calls: list[tuple] = []
        self.hurt_calls: list[tuple] = []
        self.block_calls: list[tuple] = []
        for key, value in overrides.items():
            setattr(self, "_" + key, value)

    def blocking_item(self):
        return self._blocking_item

    def component(self, item):
        return self._component

    def bypasses_component(self, component) -> bool:
        return self._bypass

    def direct_entity(self):
        return self._direct_entity

    def is_arrow(self, entity) -> bool:
        return self._arrow

    def pierce_level(self, arrow) -> int:
        return self._pierce

    def source_position(self):
        return self._source_position

    def head_yaw(self) -> float:
        return self._head_yaw

    def position(self) -> Vec3:
        return self._position

    def resolve(self, component, damage: float, angle: float) -> float:
        self.resolve_calls.append((component, damage, angle))
        return self._blocked_amount

    def level(self):
        return self._level

    def used_hand(self):
        return self._used_hand

    def hurt_blocking_item(self, component, level, item, hand, blocked: float) -> None:
        self.hurt_calls.append((component, level, item, hand, blocked))

    def source_is_projectile(self) -> bool:
        return self._source_projectile

    def is_living(self, entity) -> bool:
        return self._living

    def block_using_item(self, attacker, damage: float, fully_blocked: bool) -> None:
        self.block_calls.append((attacker, damage, fully_blocked))


def test_zero_or_negative_damage_returns_zero():
    world = _World()
    assert apply(world, 0.0) == 0.0
    assert apply(world, -2.0) == 0.0
    assert world.resolve_calls == []


def test_missing_item_or_component_returns_zero():
    assert apply(_World(blocking_item=None), 5.0) == 0.0
    assert apply(_World(component=None), 5.0) == 0.0


def test_bypassed_component_returns_zero():
    world = _World(bypass=True)
    assert apply(world, 5.0) == 0.0
    assert world.resolve_calls == []


def test_piercing_arrow_ignores_shield():
    arrow = _Arrow()
    world = _World(direct_entity=arrow, arrow=True, pierce=1)
    assert apply(world, 5.0) == 0.0
    assert world.resolve_calls == []
    # A non-piercing arrow still resolves normally.
    plain = _World(direct_entity=arrow, arrow=True, pierce=0)
    assert apply(plain, 5.0) == 4.0


def test_resolve_receives_angle_and_blocked_amount_is_returned():
    world = _World(blocked_amount=4.0)
    assert apply(world, 10.0) == 4.0
    assert len(world.resolve_calls) == 1
    component, damage, angle = world.resolve_calls[0]
    assert component == "shield_component"
    assert damage == 10.0
    assert angle == pytest.approx(0.0)
    assert world.hurt_calls == [
        ("shield_component", "overworld", "minecraft:shield", "MAIN_HAND", 4.0)
    ]


def test_missing_source_uses_fallback_angle():
    world = _World(source_position=None)
    apply(world, 10.0)
    assert world.resolve_calls[0][2] == pytest.approx(BLOCKING_FALLBACK_ANGLE)


def test_living_attacker_triggers_block_using_item():
    attacker = _Living()
    world = _World(direct_entity=attacker, blocked_amount=10.0)
    assert apply(world, 10.0) == 10.0
    assert world.block_calls == [(attacker, 10.0, True)]


def test_projectile_source_and_partial_block_do_not_fully_block():
    attacker = _Living()
    world = _World(
        direct_entity=attacker, blocked_amount=4.0, source_projectile=True
    )
    apply(world, 10.0)
    assert world.block_calls == []

    melee = _World(direct_entity=attacker, blocked_amount=4.0)
    apply(melee, 10.0)
    assert melee.block_calls == [(attacker, 10.0, False)]


def test_non_living_or_absent_entity_never_blocks_item_use():
    living = _Living()
    non_living = _World(direct_entity=living, living=False)
    apply(non_living, 10.0)
    assert non_living.block_calls == []

    no_entity = _World(direct_entity=None)
    apply(no_entity, 10.0)
    assert no_entity.block_calls == []


def test_source_behind_uses_pi_angle():
    world = _World(source_position=Vec3(0.0, 0.0, -3.0), head_yaw=0.0)
    apply(world, 10.0)
    assert world.resolve_calls[0][2] == pytest.approx(math.pi)