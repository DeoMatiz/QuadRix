"""Тесты ``quadrix/save/world_preset.py`` (порт ``save.rs::WorldPreset``).

Сверяем порядок ``ALL``, id/label, цикл next/prev и разбор сохранённого
генератора (``of_generator``) на синтетических NBT-компаундах.
"""

from __future__ import annotations

from quadrix.save.world_preset import ALL, WorldPreset
from quadrix.world.nbt import Tag, TagType


def _compound(**pairs: Tag) -> Tag:
    return Tag(TagType.Compound, compound_val=dict(pairs))


def _string(s: str) -> Tag:
    return Tag(TagType.String, str_val=s)


def test_all_order_and_ids() -> None:
    # save.rs L3400: порядок WorldPresetTags.NORMAL.
    assert ALL == (
        WorldPreset.NORMAL,
        WorldPreset.FLAT,
        WorldPreset.LARGE_BIOMES,
        WorldPreset.AMPLIFIED,
        WorldPreset.SINGLE_BIOME_SURFACE,
    )
    assert WorldPreset.DEBUG not in ALL
    assert WorldPreset.NORMAL.id == "minecraft:normal"
    assert WorldPreset.SINGLE_BIOME_SURFACE.id == "minecraft:single_biome_surface"
    assert WorldPreset.DEBUG.id == "minecraft:debug_all_block_states"


def test_of_id_roundtrip() -> None:
    for preset in (*ALL, WorldPreset.DEBUG):
        assert WorldPreset.of_id(preset.id) is preset
    assert WorldPreset.of_id("minecraft:does_not_exist") is None


def test_labels_are_language_keys() -> None:
    assert WorldPreset.NORMAL.label == "generator.minecraft.normal"
    assert WorldPreset.FLAT.label == "generator.minecraft.flat"
    assert WorldPreset.LARGE_BIOMES.label == "generator.minecraft.large_biomes"
    assert WorldPreset.AMPLIFIED.label == "generator.minecraft.amplified"
    assert WorldPreset.SINGLE_BIOME_SURFACE.label == "generator.minecraft.single_biome_surface"


def test_next_prev_wrap() -> None:
    assert WorldPreset.NORMAL.next() is WorldPreset.FLAT
    assert WorldPreset.NORMAL.prev() is WorldPreset.SINGLE_BIOME_SURFACE
    assert WorldPreset.SINGLE_BIOME_SURFACE.next() is WorldPreset.NORMAL
    assert WorldPreset.FLAT.prev() is WorldPreset.NORMAL


def test_of_generator_flat_and_debug() -> None:
    flat = _compound(type=_string("minecraft:flat"))
    assert WorldPreset.of_generator(flat) is WorldPreset.FLAT
    debug = _compound(type=_string("minecraft:debug"))
    assert WorldPreset.of_generator(debug) is WorldPreset.DEBUG


def test_of_generator_settings_select_preset() -> None:
    large = _compound(type=_string("minecraft:noise"), settings=_string("minecraft:large_biomes"))
    assert WorldPreset.of_generator(large) is WorldPreset.LARGE_BIOMES
    amp = _compound(type=_string("minecraft:noise"), settings=_string("minecraft:amplified"))
    assert WorldPreset.of_generator(amp) is WorldPreset.AMPLIFIED


def test_of_generator_single_biome_needs_fixed_source() -> None:
    fixed = _compound(
        type=_string("minecraft:noise"),
        settings=_string("minecraft:overworld"),
        biome_source=_compound(type=_string("minecraft:fixed")),
    )
    assert WorldPreset.of_generator(fixed) is WorldPreset.SINGLE_BIOME_SURFACE
    # Тот же settings без fixed biome_source — обычный мир.
    plain = _compound(
        type=_string("minecraft:noise"),
        settings=_string("minecraft:overworld"),
        biome_source=_compound(type=_string("minecraft:multi_noise")),
    )
    assert WorldPreset.of_generator(plain) is WorldPreset.NORMAL
