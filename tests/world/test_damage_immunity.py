#!/usr/bin/env python3
"""[QuadRix] Tests for quadrix/world/damage_immunity.py.

Port of horizon-world/src/damage_immunity.rs.
"""

from __future__ import annotations

from pathlib import Path

from quadrix.health import HealthResources
from quadrix.world.damage_immunity import (
    DamageRule,
    ImmunityTag,
    base_immunity,
    entity_invulnerable,
    living_immunity,
    player_immunity,
    server_player_immunity,
)


class _World:
    def __init__(self, **overrides) -> None:
        self._removed = False
        self._permanently_invulnerable = False
        self._temporarily_invulnerable = False
        self._invulnerable = False
        self._tags: set[ImmunityTag] = set()
        self._creative_source = False
        self._fire_immune = False
        self._fall_immune = False
        self._enchantment_immunity = False
        self._rules: set[DamageRule] = set()
        self._changing_dimension = False
        self._ender_pearl = False
        self._client_loaded = True
        for key, value in overrides.items():
            setattr(self, "_" + key, value)

    def removed(self) -> bool:
        return self._removed

    def permanently_invulnerable(self) -> bool:
        return self._permanently_invulnerable

    def temporarily_invulnerable(self) -> bool:
        return self._temporarily_invulnerable

    def invulnerable(self) -> bool:
        return self._invulnerable

    def tag(self, tag: ImmunityTag) -> bool:
        return tag in self._tags

    def creative_source(self) -> bool:
        return self._creative_source

    def fire_immune(self) -> bool:
        return self._fire_immune

    def fall_immune(self) -> bool:
        return self._fall_immune

    def enchantment_immunity(self) -> bool:
        return self._enchantment_immunity

    def damage_rule(self, rule: DamageRule) -> bool:
        return rule in self._rules

    def changing_dimension(self) -> bool:
        return self._changing_dimension

    def ender_pearl(self) -> bool:
        return self._ender_pearl

    def client_loaded(self) -> bool:
        return self._client_loaded


def test_entity_invulnerable_is_permanent_or_temporary():
    assert not entity_invulnerable(_World())
    assert entity_invulnerable(_World(permanently_invulnerable=True))
    assert entity_invulnerable(_World(temporarily_invulnerable=True))


def test_base_immunity_removed_and_invulnerable_order():
    assert base_immunity(_World(removed=True))
    # Plain invulnerability blocks damage.
    assert base_immunity(_World(invulnerable=True))
    # A bypassing tag lets damage through.
    assert not base_immunity(
        _World(invulnerable=True, tags={ImmunityTag.BypassesInvulnerability})
    )
    # A creative source is allowed through even while invulnerable.
    assert not base_immunity(
        _World(
            invulnerable=True,
            tags={ImmunityTag.BypassesInvulnerability},
            creative_source=True,
        )
    )


def test_base_immunity_fire_and_fall_need_tag_and_immunity():
    assert base_immunity(_World(tags={ImmunityTag.Fire}, fire_immune=True))
    assert not base_immunity(_World(fire_immune=True))
    assert not base_immunity(_World(tags={ImmunityTag.Fire}))
    assert base_immunity(_World(tags={ImmunityTag.Fall}, fall_immune=True))
    assert not base_immunity(_World(tags={ImmunityTag.Fall}))


def test_living_immunity_adds_enchantment_immunity():
    assert not living_immunity(_World())
    assert living_immunity(_World(enchantment_immunity=True))


def test_player_immunity_checks_ordered_tags_against_damage_rules():
    # Tag present but rule disabled => immune.
    assert player_immunity(_World(tags={ImmunityTag.Drowning}, rules=set()))
    # Tag present and rule enabled => not immune by that rule.
    assert not player_immunity(
        _World(tags={ImmunityTag.Drowning}, rules={DamageRule.Drowning})
    )
    # Freezing maps to the Freeze rule.
    assert player_immunity(_World(tags={ImmunityTag.Freezing}, rules=set()))
    assert not player_immunity(
        _World(tags={ImmunityTag.Freezing}, rules={DamageRule.Freeze})
    )
    # Living immunity wins before the tag table.
    assert player_immunity(_World(enchantment_immunity=True))


def test_server_player_immunity_dimension_and_client_state():
    assert server_player_immunity(_World(changing_dimension=True))
    # Ender pearl teleports are not immune while changing dimension.
    assert not server_player_immunity(
        _World(changing_dimension=True, ender_pearl=True)
    )
    assert server_player_immunity(_World(client_loaded=False))
    assert not server_player_immunity(_World())


def test_real_health_data_exposes_immunity_tag_families():
    resources = HealthResources.load(Path(".local/horizon-client-health"))
    catalog = resources.damage
    assert catalog.has_tag("minecraft:fall", "minecraft:is_fall")
    assert catalog.has_tag("minecraft:in_fire", "minecraft:is_fire")
    fire_members = {damage.id for damage in catalog.by_tag("minecraft:is_fire")}
    assert "minecraft:on_fire" in fire_members
    assert "minecraft:lava" in fire_members
    # The four immunity-relevant tag families all exist in the real data.
    for tag in (
        "minecraft:is_drowning",
        "minecraft:is_fall",
        "minecraft:is_fire",
        "minecraft:is_freezing",
    ):
        assert tag in catalog.tags