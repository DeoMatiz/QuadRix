#!/usr/bin/env python3
"""Тесты quadrix.world.chunk: палитры, битовые хранилища, чанки, heightmaps."""

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.protocol.buf import Reader, Writer
from quadrix.world.chunk import (
    BIOMES,
    BLOCKS,
    MIN_Y,
    SECTIONS,
    BitStorage,
    BlockEntity,
    BlockSection,
    Chunk,
    ChunkData,
    ChunkSection,
    Heightmap,
    HeightmapType,
    LightData,
    NbtPalettedContainer,
    PalettedContainer,
    Strategy,
    bits_for_palette,
    storage_len,
)
from quadrix.world.nbt import Tag, TagType
from quadrix.world.registry import BlockStateId, load_registry

REGISTRY_PATH = Path(".local/horizon-client-motion/block-registry.nbt")


@pytest.fixture(scope="module")
def registry():
    return load_registry(REGISTRY_PATH)


def _roundtrip(container: PalettedContainer) -> PalettedContainer:
    w = Writer()
    container.write(w)
    return PalettedContainer.read(
        Reader(w.to_bytes()), container.strategy, container.global_bits
    )


# ---- BitStorage ------------------------------------------------------------


def test_bit_storage_pack_unpack_every_width():
    """bits 1, 2, 4, 8, 15: запись, чтение и перечитывание из long'ов."""
    for bits in (1, 2, 4, 8, 15):
        mask = (1 << bits) - 1
        storage = BitStorage.new(bits, BLOCKS)
        expected = [(i * 7 + 3) & mask for i in range(BLOCKS)]
        for i, value in enumerate(expected):
            assert storage.set(i, value) == 0
        assert storage.unpack() == expected
        assert storage.words() and len(storage.words()) == storage_len(bits, BLOCKS)

        reread = BitStorage.from_words(bits, BLOCKS, storage.words())
        assert reread.bits() == bits
        for i in (0, 1, 15, 16, 4095):
            assert reread.get(i) == expected[i]


def test_bit_storage_never_splits_an_entry_across_words():
    """PackedStorage::padded_words_never_split_entries: 5 бит, 13 ячеек."""
    storage = BitStorage.new(5, 13)
    storage.set(11, 31)
    storage.set(12, 7)
    assert storage.words() == [31 << 55, 7]


# ---- PalettedContainer (проводной формат) ---------------------------------


def test_paletted_single_value_roundtrip():
    """bits_per_entry = 0: палитра из одного значения, данных нет."""
    container = PalettedContainer.from_values([7] * BLOCKS, Strategy.Blocks, 16)
    assert container.bits == 0
    assert container.palette == [7]
    assert container.data == []

    back = _roundtrip(container)
    assert back.bits == 0
    assert back.palette == [7]
    assert back.data == []
    assert back.get(0) == 7
    assert back.get(BLOCKS - 1) == 7


def test_paletted_indirect_palette_roundtrip():
    """bits_per_entry = 4, палитра из 16 значений."""
    values = [i % 16 for i in range(BLOCKS)]
    container = PalettedContainer.from_values(values, Strategy.Blocks, 16)
    assert container.bits == 4
    assert container.palette == list(range(16))
    assert len(container.data) == storage_len(4, BLOCKS)

    back = _roundtrip(container)
    assert (back.bits, back.palette, back.data) == (
        container.bits,
        container.palette,
        container.data,
    )
    assert [back.get(i) for i in (0, 1, 15, 16, 255, 4095)] == [0, 1, 15, 0, 15, 15]


def test_paletted_direct_global_palette_roundtrip():
    """bits_per_entry >= 15: глобальная палитра, значения — registry id."""
    values = list(range(BLOCKS))
    container = PalettedContainer.from_values(values, Strategy.Blocks, 15)
    assert container.bits == 15
    assert container.palette == []
    assert len(container.data) == storage_len(15, BLOCKS)

    back = _roundtrip(container)
    assert back.bits == 15
    assert back.palette == []
    assert back.data == container.data
    assert [back.get(i) for i in (0, 1, 100, 4095)] == [0, 1, 100, 4095]


def test_paletted_biome_strategy_uses_own_widths():
    """Биомы: 1..3 бита — палитра; больше — глобальная палитра."""
    two = PalettedContainer.from_values([2] * 32 + [3] * 32, Strategy.Biomes, 7)
    assert (two.bits, two.palette) == (1, [2, 3])

    many = PalettedContainer.from_values(list(range(16)) * 4, Strategy.Biomes, 7)
    assert many.bits == 7
    assert many.palette == []
    assert many.entries == BIOMES


def test_section_reads_and_writes_both_containers():
    section = ChunkSection.uniform(state=1, biome=4)
    w = Writer()
    section.write(w)
    back = ChunkSection.read(Reader(w.to_bytes()))
    assert back.non_empty == 0
    assert back.states.get(0) == 1
    assert back.biomes.get(0) == 4


# ---- Heightmap -------------------------------------------------------------


def test_heightmap_roundtrip_nine_bits():
    """9 бит на 256 колонн: запись высот и обратное чтение."""
    heights = [(x * 3 + z * 5) % 384 for z in range(16) for x in range(16)]
    source = BitStorage.new(9, 256)
    for z in range(16):
        for x in range(16):
            source.set(x + z * 16, heights[x + z * 16])

    heightmap = Heightmap.from_longs(
        HeightmapType.MotionBlocking, source.words(), MIN_Y
    )
    assert heightmap.bits() == 9
    assert len(heightmap.raw_data()) == 37
    assert heightmap.get(3, 4) == heights[3 + 4 * 16] + MIN_Y

    back = Heightmap.from_longs(
        heightmap.kind, heightmap.to_longs(), MIN_Y
    )
    assert back.kind is HeightmapType.MotionBlocking
    assert back.get(15, 15) == heights[15 + 15 * 16] + MIN_Y
    assert back.raw_data() == heightmap.raw_data()


# ---- BlockEntity -----------------------------------------------------------


def test_block_entity_nbt_roundtrip():
    tag = Tag(
        tag_type=TagType.Compound,
        compound_val={
            "id": Tag(TagType.String, str_val="minecraft:chest"),
            "x": Tag(TagType.Int, int_val=3),
        },
    )
    entity = BlockEntity.at(3, 70, 5, 1, tag)
    assert entity.position() == (3, 70, 5)

    w = Writer()
    entity.write(w)
    back = BlockEntity.read(Reader(w.to_bytes()))
    assert (back.packed_xz, back.y, back.kind) == (entity.packed_xz, 70, 1)
    assert back.position() == (3, 70, 5)
    assert back.tag.compound_val["id"].str_val == "minecraft:chest"


def test_chunk_data_wire_roundtrip_with_heightmap_and_block_entity():
    chunk = Chunk.empty(3, -2)
    data = chunk.to_chunk_data()

    source = BitStorage.new(9, 256)
    source.set(1 + 2 * 16, 63)
    data.heightmaps = [(int(HeightmapType.WorldSurface), Heightmap.from_longs(
        HeightmapType.WorldSurface, source.words(), MIN_Y
    ).to_longs())]
    data.block_entities = [
        BlockEntity.at(1, 64, 2, 1, Tag(TagType.Compound, compound_val={}))
    ]

    w = Writer()
    data.write(w)
    back = ChunkData.read(Reader(w.to_bytes()))
    assert back.heightmaps[0][0] == int(HeightmapType.WorldSurface)
    assert back.block_entities[0].position() == (1, 64, 2)
    assert back.sections(SECTIONS)[0].states.get(0) == 0


# ---- Chunk -----------------------------------------------------------------


def test_chunk_empty_roundtrip():
    chunk = Chunk.empty(3, -2)
    assert len(chunk.sections) == SECTIONS
    assert chunk.min_y == MIN_Y
    assert chunk.max_y() == MIN_Y + 384

    data = chunk.to_chunk_data()
    assert data.heightmaps == []
    assert data.block_entities == []

    back = Chunk.from_chunk_data(3, -2, data)
    assert (back.x, back.z) == (3, -2)
    assert len(back.sections) == SECTIONS
    assert back.get(0, MIN_Y, 0) == 0
    assert back.get(15, MIN_Y + 383, 15) == 0
    assert all(section.states.bits == 0 for section in back.sections)
    assert all(section.states.palette == [0] for section in back.sections)


def test_chunk_with_stone_in_one_section(registry):
    air = registry.default_state("minecraft:air").id
    stone = registry.default_state("minecraft:stone").id
    assert (air, stone) == (0, 1)

    chunk = Chunk.empty(0, 0)
    chunk.set(0, MIN_Y, 0, stone)
    data = chunk.to_chunk_data()
    back = Chunk.from_chunk_data(0, 0, data)

    assert back.get(0, MIN_Y, 0) == stone
    assert back.get(1, MIN_Y, 0) == air
    assert back.get(2, MIN_Y, 0) == air
    # Одна не-air ячейка + воздух: палитра из двух значений, 4 бита.
    bottom = back.sections[0]
    assert bottom.states.bits == 4
    assert bottom.states.palette == [stone, air]
    assert bottom.get(0) == stone
    assert all(section.states.bits == 0 for section in back.sections[1:])


def test_chunk_world_surface_counts_non_air(registry):
    stone = registry.default_state("minecraft:stone").id
    chunk = Chunk.empty(0, 0)
    chunk.set(4, MIN_Y + 10, 7, stone)
    assert chunk.world_surface(4, 7) == MIN_Y + 11
    assert chunk.world_surface(5, 7) == MIN_Y


# ---- Сохранённый NBT-формат ------------------------------------------------


def test_nbt_paletted_container_roundtrip_and_compact():
    container = NbtPalettedContainer.uniform(Tag(TagType.Int, int_val=0), BLOCKS, 4)
    for i in range(BLOCKS):
        container.set(i, Tag(TagType.Int, int_val=i % 3))
    assert container.bits() == 4
    assert container.palette_len() == 3

    tag = container.to_nbt()
    back = NbtPalettedContainer.from_nbt(tag, BLOCKS, 4)
    assert back.palette_len() == 3
    for i in (0, 1, 2, 4095):
        assert back.get(i) == Tag(TagType.Int, int_val=i % 3)

    for i in range(BLOCKS):
        back.set(i, Tag(TagType.Int, int_val=7))
    back.compact()
    assert back.bits() == 0
    assert back.palette_len() == 1
    assert back.get(4095) == Tag(TagType.Int, int_val=7)
    assert "data" not in back.to_nbt().compound_val


def test_block_section_from_nbt_preserves_states(registry):
    air = registry.default_state("minecraft:air")
    stone = registry.default_state("minecraft:stone")
    section = BlockSection.uniform(air, registry)
    assert section.bits() == 0
    section.set(0, stone)
    assert section.get(0) == stone
    assert section.get(1) == air

    back = BlockSection.from_nbt(section.to_nbt(), registry)
    assert back.get(0) == BlockStateId(stone.id)
    assert back.get(1) == BlockStateId(air.id)
    assert back.bits() == section.bits()
    # from_nbt начинает с состояния первой ячейки, поэтому порядок палитры
    # может отличаться; совпадать обязаны все 4096 состояний.
    assert set(back.palette) == set(section.palette)
    assert all(back.get(i) == section.get(i) for i in range(BLOCKS))


# ---- LightData -------------------------------------------------------------


def test_light_data_layers_masks():
    layer = bytes([0x11]) * 2048
    light = LightData(
        sky_mask=bytearray([0b01]),
        empty_block_mask=bytearray([0b01]),
        sky=[layer],
    )
    layers = light.layers(2)
    assert layers[0][0] == layer
    assert layers[0][1] == bytes(2048)
    assert layers[1] == (None, None)


def test_bits_for_palette_matches_rust():
    assert bits_for_palette(0, 4) == 0
    assert bits_for_palette(1, 4) == 0
    assert bits_for_palette(2, 4) == 4
    assert bits_for_palette(16, 4) == 4
    assert bits_for_palette(17, 4) == 5
    assert bits_for_palette(256, 4) == 8