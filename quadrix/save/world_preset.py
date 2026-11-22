"""Пресеты мира Create World (порт ``save.rs::WorldPreset``).

Источник: ``horizon/crates/horizon-client/src/save.rs`` (L3384-3472).
``WorldPreset`` — один из шести пресетов ``worldgen/world_preset`` 26.3,
которые предлагает экран создания мира, в порядке ``WorldPresetTags.NORMAL``.

Читаем только нужное для меню создания мира (WC0); ``WorldGen`` и чтение
``world_gen_settings`` откладываются до PART сохранения мира.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from quadrix.world.nbt import Tag, TagType

# save.rs L3400: порядок цикла кнопки типа мира.
ALL: tuple["WorldPreset", ...] = ()  # заполняется ниже


class WorldPreset(Enum):
    """``save.rs::WorldPreset`` — пресеты мира."""

    NORMAL = "minecraft:normal"
    FLAT = "minecraft:flat"
    LARGE_BIOMES = "minecraft:large_biomes"
    AMPLIFIED = "minecraft:amplified"
    SINGLE_BIOME_SURFACE = "minecraft:single_biome_surface"
    #: ``minecraft:debug_all_block_states`` — сетка всех блоков; экран
    #: создания её не предлагает, но её может назвать data pack или мир.
    DEBUG = "minecraft:debug_all_block_states"

    # --- save.rs::WorldPreset::id ---
    @property
    def id(self) -> str:
        """Registry-id пресета (``minecraft:normal``)."""
        return self.value

    @staticmethod
    def of_id(preset_id: str) -> Optional["WorldPreset"]:
        """Пресет, который называет id, если это один из них."""
        for preset in (*ALL, WorldPreset.DEBUG):
            if preset.id == preset_id:
                return preset
        return None

    # --- save.rs::WorldPreset::label ---
    @property
    def label(self) -> str:
        """Ключ языка кнопки типа мира (``Identifier.toLanguageKey("generator")``)."""
        return _LABELS[self]

    # --- save.rs::WorldPreset::next / prev ---
    def next(self) -> "WorldPreset":
        """Пресет, к которому кнопка типа мира переключается вперёд."""
        index = ALL.index(self) if self in ALL else 0
        return ALL[(index + 1) % len(ALL)]

    def prev(self) -> "WorldPreset":
        """Пресет, к которому кнопка типа мира переключается назад."""
        index = ALL.index(self) if self in ALL else 0
        return ALL[(index + len(ALL) - 1) % len(ALL)]

    @staticmethod
    def of_generator(generator: Tag) -> "WorldPreset":
        """Пресет сохранённого overworld-генератора.

        Имя noise-settings называет пресет; пресет одного биома делит
        noise-settings overworld, поэтому его fixed biome-source отличает
        два (``WorldPreset::of_generator``).
        """
        if _text(_compound_get(generator, "type")) == "minecraft:flat":
            return WorldPreset.FLAT
        if _text(_compound_get(generator, "type")) == "minecraft:debug":
            return WorldPreset.DEBUG
        source = _compound_get(generator, "biome_source")
        fixed = _text(_compound_get(source, "type")) == "minecraft:fixed"
        settings = _text(_compound_get(generator, "settings"))
        if settings == "minecraft:large_biomes":
            return WorldPreset.LARGE_BIOMES
        if settings == "minecraft:amplified":
            return WorldPreset.AMPLIFIED
        if settings == "minecraft:overworld" and fixed:
            return WorldPreset.SINGLE_BIOME_SURFACE
        return WorldPreset.NORMAL


# save.rs L3427: ``Identifier.toLanguageKey("generator")`` каждого пресета.
_LABELS: dict[WorldPreset, str] = {
    WorldPreset.NORMAL: "generator.minecraft.normal",
    WorldPreset.FLAT: "generator.minecraft.flat",
    WorldPreset.LARGE_BIOMES: "generator.minecraft.large_biomes",
    WorldPreset.AMPLIFIED: "generator.minecraft.amplified",
    WorldPreset.SINGLE_BIOME_SURFACE: "generator.minecraft.single_biome_surface",
    WorldPreset.DEBUG: "generator.minecraft.debug_all_block_states",
}

# save.rs L3400: ``WorldPreset::ALL`` — пресеты в порядке цикла.
ALL = (
    WorldPreset.NORMAL,
    WorldPreset.FLAT,
    WorldPreset.LARGE_BIOMES,
    WorldPreset.AMPLIFIED,
    WorldPreset.SINGLE_BIOME_SURFACE,
)


# ---------------------------------------------------------------------------
# nbt_value.rs (``text`` / ``compound get``) — только для of_generator
# ---------------------------------------------------------------------------

def _compound_get(tag: Optional[Tag], key: str) -> Optional[Tag]:
    """``generator.get(key)`` — значение compound-тега (None, если не compound)."""
    if tag is None or tag.tag_type != TagType.Compound or tag.compound_val is None:
        return None
    return tag.compound_val.get(key)


def _text(tag: Optional[Tag]) -> Optional[str]:
    """``nbt_value.rs::text`` — String-тег как Python str, иначе None."""
    if tag is None or tag.tag_type != TagType.String:
        return None
    if tag.str_val is None:
        return None
    if isinstance(tag.str_val, str):
        return tag.str_val
    # JavaString → str
    to_python = getattr(tag.str_val, "to_python_str", None)
    if callable(to_python):
        return to_python()
    return str(tag.str_val)
