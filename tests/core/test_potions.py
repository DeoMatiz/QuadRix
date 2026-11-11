# Тесты порта horizon-client-core/src/potions.rs → quadrix/core/potions.py.
#
# Проверяем таблицы `MobEffects` (EFFECTS) и `Potions` (POTIONS), поиск по id,
# description_id/sprite/namespaced, цвет смеси эффектов и регистрацию эффектов
# модов. Ожидаемые цвета/длительности/амплификаторы взяты из Rust-таблиц, а не
# выводятся из кода под тестом.

from __future__ import annotations

import pytest

from quadrix.core.potions import (
    BASE_POTION_COLOR,
    EFFECTS,
    POTIONS,
    Category,
    EffectDef,
    all_effects,
    description_id,
    effect,
    effects_color,
    is_mod_effect,
    mod_effects,
    namespaced,
    potion,
    potion_color,
    register_mod_effects,
    sprite,
)


def test_swiftness_has_speed():
    p = potion("swiftness")
    assert p is not None
    assert p.name == "swiftness"
    assert p.effects == (("speed", 3600, 0),)


def test_healing_is_instant_health():
    p = potion("healing")
    assert p is not None
    assert p.effects == (("instant_health", 1, 0),)
    fx = effect("instant_health")
    assert fx is not None and fx.instant is True
    assert effect("minecraft:instant_health") is fx


def test_unknown_potion_is_none():
    assert potion("not_a_potion") is None
    assert potion("") is None
    assert potion_color(None) == BASE_POTION_COLOR
    assert potion_color("not_a_potion") == BASE_POTION_COLOR


def test_registry_holds_all_vanilla_potions_and_namespaced_lookup():
    assert len(EFFECTS) == 40
    assert len(POTIONS) == 46
    assert POTIONS[0].id == "water" and POTIONS[0].effects == ()
    # Поиск снимает namespace `minecraft:`.
    assert potion("minecraft:swiftness") is potion("swiftness")
    ids = {p.id for p in POTIONS}
    assert {"water", "awkward", "swiftness", "strong_healing", "turtle_master"} <= ids


def test_description_id_and_sprite_keep_the_namespace():
    # Rust-тест: description_ids_and_sprites_keep_the_namespace.
    assert description_id("speed") == "effect.minecraft.speed"
    assert description_id("minecraft:speed") == "effect.minecraft.speed"
    assert description_id("ruby:curse/dark") == "effect.ruby.curse.dark"
    assert sprite("speed") == "mob_effect/speed"
    assert sprite("minecraft:speed") == "mob_effect/speed"
    assert sprite("ruby:curse/dark") == "ruby:mob_effect/curse/dark"


def test_effect_color_mix_is_amplifier_weighted():
    # Rust-тест: effects_mix_their_colours_by_amplifier.
    def c(id: str) -> int:
        e = effect(id)
        assert e is not None
        return e.color

    assert effects_color([("poison", 0)]) == c("poison")
    p, s = c("poison"), c("speed")

    def mix(shift: int) -> int:
        return (((p >> shift) & 255) + 3 * ((s >> shift) & 255)) // 4 << shift

    assert effects_color([("poison", 0), ("speed", 2)]) == mix(16) | mix(8) | mix(0)
    assert effects_color([]) == BASE_POTION_COLOR


def test_effect_category_and_instant_flags():
    e = effect("slowness")
    assert e is not None
    assert e.category is Category.Harmful
    assert e.instant is False
    assert effect("glowing").category is Category.Neutral
    assert effect("nope") is None
    assert is_mod_effect("ruby:glow") and not is_mod_effect("speed")
    assert namespaced("speed") == "minecraft:speed"
    assert namespaced("minecraft:speed") == "minecraft:speed"
    assert namespaced("ruby:glow") == "ruby:glow"


def test_mod_effects_register_once():
    # Rust-тест: mod_effects_follow_vanilla_once_registered (единственный,
    # регистрирующий: реестр одноразовый за процесс).
    assert register_mod_effects([("ruby:glow", 0xFF0000, Category.Neutral)]) is True
    assert register_mod_effects([("ruby:late", 1, Category.Harmful)]) is False
    glow = effect("ruby:glow")
    assert glow is not None
    assert (glow.color, glow.category, glow.instant) == (0xFF0000, Category.Neutral, False)
    assert effect("glow") is None and effect("ruby:late") is None
    assert namespaced("ruby:glow") == "ruby:glow"
    ids = [e.id for e in all_effects()]
    assert ids[-1] == "ruby:glow"
    assert len(ids) == len(EFFECTS) + 1
    assert mod_effects() and mod_effects()[0].id == "ruby:glow"


def test_potion_color_of_poison_is_poison_colour():
    poison = effect("poison")
    assert poison is not None
    assert potion_color("poison") == poison.color
