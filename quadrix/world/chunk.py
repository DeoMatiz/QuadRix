#!/usr/bin/env python3
"""Чанки: секции, палитры, битовые хранилища, heightmaps и block entities.

Порт:
  * ``horizon/crates/horizon-world/src/chunk.rs`` — сохранённый формат
    (``NbtPalettedContainer``, ``BlockSection``, ``NbtChunkData``);
  * ``horizon/crates/horizon-protocol/src/chunk.rs`` — проводной формат
    (``PalettedContainer``, ``ChunkSection``, ``Heightmaps``, ``ChunkData``,
    ``LightData``);
  * ``horizon/crates/horizon-client-render/src/chunk.rs`` — резидентный
    ``Chunk`` (``ColumnLayout``, ``Section``, heightmaps мира).

Проводной формат (1.20.5+), точно как ``Paletted.read``:
    u8 bits_per_entry
    если bits_per_entry == 0        -> VarInt единственного значения
    иначе если есть палитра         -> VarInt len + len * VarInt
    иначе                           -> глобальная палитра (значения = registry id)
    long[] data                     -> ``storage_len(bits, entries)``

``ChunkData`` из ``quadrix.protocol.packets.play`` хранит сырые байты секций;
``Chunk.from_chunk_data`` превращает их в ``ChunkSection``/``Heightmap``/
``BlockEntity``, а ``Chunk.to_chunk_data`` кодирует обратно.  Ничего не
додумывается: все константы и раскладки взяты из Rust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Sequence, Tuple

from quadrix.protocol.buf import Reader, Writer, bit
from quadrix.world.nbt import Tag, TagType
from quadrix.world.registry import BlockRegistry, BlockState, BlockStateId

__all__ = [
    "BLOCKS",
    "BIOMES",
    "MIN_Y",
    "HEIGHT",
    "SECTIONS",
    "SECTION_HEIGHT",
    "BLOCK_BITS",
    "BIOME_BITS",
    "Strategy",
    "BitStorage",
    "storage_get",
    "storage_len",
    "PalettedContainer",
    "Paletted",
    "ChunkSection",
    "Section",
    "HeightmapType",
    "Heightmap",
    "BlockEntity",
    "LightData",
    "ChunkData",
    "ColumnLayout",
    "Chunk",
    "bits_for_palette",
    "NbtPalettedContainer",
    "BlockSection",
    "NbtChunkData",
    "block_state_from_nbt",
    "block_state_to_nbt",
]

# ---- константы из Rust -----------------------------------------------------

# horizon-protocol/src/chunk.rs: блокам — 16^3, биомам — 4^3 на секцию.
BLOCKS = 4096
BIOMES = 64

# horizon-client-render/src/chunk.rs: колонка ванильного Overworld.
MIN_Y = -64
HEIGHT = 384
SECTIONS = HEIGHT // 16
SECTION_HEIGHT = 16

# Реестр 26.3: 35 723 состояния -> 16 бит; биомы -> 7 бит.
BLOCK_BITS = 16
BIOME_BITS = 7

# horizon-world/src/registry.rs::DATA_VERSION.
DATA_VERSION = 5023

_U64 = (1 << 64) - 1
_I32_MAX = (1 << 31) - 1


def _invalid(reason: str) -> ValueError:
    """``compression::invalid`` — ошибка формата с префиксом QuadRix."""
    return ValueError(f"[QuadRix] {reason}")


def _as_u64(value: int) -> int:
    return value & _U64


def _as_i64(value: int) -> int:
    value &= _U64
    return value - (1 << 64) if value >= (1 << 63) else value


def bits_for_palette(length: int, min_bits: int) -> int:
    """``bits_for_palette`` (world/src/chunk.rs:21)."""
    if length <= 1:
        return 0
    return max((length - 1).bit_length(), min_bits)


# ---- Strategy (horizon-protocol/src/chunk.rs:17) --------------------------


class Strategy(Enum):
    """Какая стратегия палитры у контейнера."""

    Blocks = "blocks"
    Biomes = "biomes"

    def entries(self) -> int:
        """Число ячеек контейнера."""
        return BLOCKS if self is Strategy.Blocks else BIOMES

    def configuration(self, bits: int, global_bits: int) -> Tuple[bool, int]:
        """``getConfigurationForBitCount``: (есть палитра, бит на запись)."""
        if bits == 0:
            return True, 0
        if self is Strategy.Blocks and 1 <= bits <= 4:
            return True, 4
        if self is Strategy.Blocks and 5 <= bits <= 8:
            return True, bits
        if self is Strategy.Biomes and 1 <= bits <= 3:
            return True, bits
        return False, max(global_bits, bits)


# ---- SimpleBitStorage / PackedStorage -------------------------------------


class BitStorage:
    """``SimpleBitStorage``: 64 / bits значений в long, без разрыва long.

    Тот же расклад, что у ``horizon_core::storage::PackedStorage``: индекс
    ячейки ``i // per_word``, сдвиг ``(i % per_word) * bits``.
    """

    __slots__ = ("_bits", "_len", "_per_word", "_mask", "_words")

    def __init__(self, bits: int, length: int, words: Optional[Sequence[int]] = None) -> None:
        if not 1 <= bits <= 32:
            raise _invalid(f"invalid bits per entry {bits}")
        if length < 0:
            raise _invalid("negative storage length")
        per_word = 64 // bits
        expected = 0 if length == 0 else (length + per_word - 1) // per_word
        if words is None:
            words = [0] * expected
        elif len(words) != expected:
            raise _invalid(
                f"storage needs {expected} words, got {len(words)}"
            )
        self._bits = bits
        self._len = length
        self._per_word = per_word
        self._mask = (1 << bits) - 1
        self._words = [_as_u64(w) for w in words]

    @classmethod
    def new(cls, bits: int, length: int) -> "BitStorage":
        return cls(bits, length)

    @classmethod
    def from_words(cls, bits: int, length: int, words: Sequence[int]) -> "BitStorage":
        return cls(bits, length, words)

    # -- доступ --
    def bits(self) -> int:
        return self._bits

    def len(self) -> int:
        return self._len

    def __len__(self) -> int:
        return self._len

    def words(self) -> List[int]:
        """Сырые long'и как u64 (в Rust — ``&[u64]``)."""
        return list(self._words)

    def _slot(self, index: int) -> Tuple[int, int]:
        return index // self._per_word, (index % self._per_word) * self._bits

    def get(self, index: int) -> int:
        if not 0 <= index < self._len:
            raise _invalid("storage index out of bounds")
        return self.read(index)

    def read(self, index: int) -> int:
        word, shift = self._slot(index)
        return (self._words[word] >> shift) & self._mask

    def write(self, index: int, value: int) -> int:
        if not 0 <= index < self._len:
            raise _invalid("storage index out of bounds")
        value = int(value)
        if value < 0 or value > self._mask:
            raise _invalid(f"value {value} does not fit {self._bits} bits")
        word, shift = self._slot(index)
        old = (self._words[word] >> shift) & self._mask
        self._words[word] = (
            self._words[word] & ~(self._mask << shift)
        ) | (value << shift)
        return old

    def set(self, index: int, value: int) -> int:
        """``PackedStorage::set``: проверяет value и пишет."""
        value = int(value)
        if value > _I32_MAX:
            raise _invalid(f"value {value} is not a nonnegative Java int")
        return self.write(index, value)

    def unpack_into(self, out: List[int]) -> None:
        i = 0
        for word in self._words:
            for slot in range(min(self._per_word, self._len - i)):
                out[i] = (word >> (slot * self._bits)) & self._mask
                i += 1

    def unpack(self) -> List[int]:
        values = [0] * self._len
        self.unpack_into(values)
        return values


def storage_get(data: Sequence[int], bits: int, i: int) -> int:
    """``storage_get`` (horizon-protocol/src/chunk.rs:43)."""
    if bits == 0:
        return 0
    per = 64 // bits
    cell, offset = i // per, (i % per) * bits
    if cell >= len(data):
        return 0
    return (int(data[cell]) & _U64) >> offset & ((1 << bits) - 1)


def storage_len(bits: int, entries: int) -> int:
    """``storage_len``: сколько long'ов займёт контейнер."""
    if bits == 0:
        return 0
    return (entries + (64 // bits) - 1) // (64 // bits)


def _pack(values: Sequence[int], bits: int, ident) -> List[int]:
    """``pack``: значения по long'ам, как ``SimpleBitStorage``."""
    per = 64 // bits
    out: List[int] = []
    for start in range(0, len(values), per):
        word = 0
        for k, value in enumerate(values[start:start + per]):
            word |= int(ident(value)) << (k * bits)
        out.append(_as_i64(word))
    return out


# ---- PalettedContainer (проводной формат) ---------------------------------


@dataclass
class PalettedContainer:
    """``horizon_protocol::chunk::Paletted`` — один контейнер как в пакете.

    ``palette`` пуста у глобальной палитры; ``data`` — упакованные long'и.
    ``entries``/``strategy``/``global_bits`` нужны только для правок на
    клиенте (провод их не передаёт).
    """

    bits: int
    palette: List[int]
    data: List[int]
    entries: int = field(default=BLOCKS, compare=False)
    strategy: Strategy = field(default=Strategy.Blocks, compare=False)
    global_bits: int = field(default=BLOCK_BITS, compare=False)

    # -- чтение / запись --
    @classmethod
    def read(
        cls,
        r: Reader,
        strategy: Strategy = Strategy.Blocks,
        global_bits: int = BLOCK_BITS,
    ) -> "PalettedContainer":
        wire = r.u8()
        has_palette, bits = strategy.configuration(wire, global_bits)
        if bits > 32:
            raise _invalid(f"{bits} bits per entry, more than 32")
        if not has_palette:
            palette: List[int] = []
        elif bits == 0:
            palette = [r.varint()]
        else:
            n = r.count(1 << bits)
            palette = [r.varint() for _ in range(n)]
        data = r.fixed_longs(storage_len(bits, strategy.entries()))
        return cls(
            bits=bits,
            palette=palette,
            data=data,
            entries=strategy.entries(),
            strategy=strategy,
            global_bits=global_bits,
        )

    def write(self, w: Writer) -> None:
        w.u8(self.bits)
        if self.palette:
            if self.bits != 0:
                w.varint(len(self.palette))
            for entry in self.palette:
                w.varint(entry)
        for word in self.data:
            w.i64(word)

    # -- доступ --
    def get(self, i: int) -> int:
        """Registry id в ячейке ``i`` (``(y*16 + z)*16 + x`` для блоков)."""
        if self.bits == 0:
            return self.palette[0] if self.palette else 0
        value = storage_get(self.data, self.bits, i)
        if not self.palette:
            return value
        return self.palette[value] if value < len(self.palette) else 0

    def uniform(self) -> Optional[int]:
        """Значение секции без словаря, иначе ``None``."""
        if self.bits == 0:
            return self.palette[0] if self.palette else 0
        return None

    def storage(self) -> Optional[BitStorage]:
        if self.bits == 0:
            return None
        return BitStorage.from_words(self.bits, self.entries, self.data)

    def unpack(self) -> List[int]:
        """Все ``entries`` значений registry id (для правок/сравнений)."""
        if self.bits == 0:
            value = self.palette[0] if self.palette else 0
            return [value] * self.entries
        values = [0] * self.entries
        per = 64 // self.bits
        for i in range(self.entries):
            raw = storage_get(self.data, self.bits, i)
            values[i] = self.palette[raw] if self.palette else raw
        return values

    def set(self, i: int, value: int) -> int:
        """Пишет registry id в ячейку; возвращает прежнее значение.

        Клиенту правки нужны редко, поэтому путь простой: пересобрать
        контейнер из значений (результат совпадает с ростом палитры сервера).
        """
        if not 0 <= i < self.entries:
            raise _invalid("section index out of bounds")
        old = self.get(i)
        if old == value:
            return old
        values = self.unpack()
        values[i] = int(value)
        rebuilt = type(self).from_values(values, self.strategy, self.global_bits)
        self.bits = rebuilt.bits
        self.palette = rebuilt.palette
        self.data = rebuilt.data
        return old

    # -- сборка --
    @classmethod
    def from_values(
        cls,
        values: Sequence[int],
        strategy: Strategy = Strategy.Blocks,
        global_bits: int = BLOCK_BITS,
    ) -> "PalettedContainer":
        """``from_values``: минимальная конфигурация по числу значений."""
        palette: List[int] = []
        ids: List[int] = []
        for value in values:
            value = int(value)
            if value not in palette:
                palette.append(value)
            ids.append(palette.index(value))
        return cls.from_palette(palette, ids, strategy, global_bits)

    @classmethod
    def from_palette(
        cls,
        palette: Sequence[int],
        ids: Sequence[int],
        strategy: Strategy = Strategy.Blocks,
        global_bits: int = BLOCK_BITS,
    ) -> "PalettedContainer":
        palette = [int(v) for v in palette]
        needed = bits_for_palette(len(palette), 0) if len(palette) > 1 else 0
        has_palette, bits = strategy.configuration(needed, global_bits)
        if bits == 0:
            return cls(
                bits=0,
                palette=[palette[0] if palette else 0],
                data=[],
                entries=strategy.entries(),
                strategy=strategy,
                global_bits=global_bits,
            )
        if has_palette:
            data = _pack(ids, bits, lambda v: v)
            out_palette = list(palette)
        else:
            data = _pack(ids, bits, lambda v: palette[v])
            out_palette = []
        return cls(
            bits=bits,
            palette=out_palette,
            data=data,
            entries=strategy.entries(),
            strategy=strategy,
            global_bits=global_bits,
        )


# Имя из Rust-протокола.
Paletted = PalettedContainer


# ---- ChunkSection (LevelChunkSection.write) --------------------------------


@dataclass
class ChunkSection:
    """``horizon_protocol::chunk::Section``: блоки + биомы секции."""

    non_empty: int
    fluids: int
    states: PalettedContainer
    biomes: PalettedContainer

    @classmethod
    def read(
        cls,
        r: Reader,
        block_bits: int = BLOCK_BITS,
        biome_bits: int = BIOME_BITS,
    ) -> "ChunkSection":
        return cls(
            non_empty=r.i16(),
            fluids=r.i16(),
            states=PalettedContainer.read(r, Strategy.Blocks, block_bits),
            biomes=PalettedContainer.read(r, Strategy.Biomes, biome_bits),
        )

    def write(self, w: Writer) -> None:
        w.i16(self.non_empty)
        w.i16(self.fluids)
        self.states.write(w)
        self.biomes.write(w)

    def get(self, i: int) -> int:
        return self.states.get(i)

    def set(self, i: int, value: int) -> int:
        return self.states.set(i, value)

    def unpack(self) -> List[int]:
        return self.states.unpack()

    @classmethod
    def uniform(cls, state: int = 0, biome: int = 0) -> "ChunkSection":
        return cls(
            non_empty=0,
            fluids=0,
            states=PalettedContainer(bits=0, palette=[state], data=[]),
            biomes=PalettedContainer(
                bits=0,
                palette=[biome],
                data=[],
                entries=BIOMES,
                strategy=Strategy.Biomes,
                global_bits=BIOME_BITS,
            ),
        )


Section = ChunkSection


# ---- Heightmap -------------------------------------------------------------


class HeightmapType(IntEnum):
    """``HeightmapType`` (horizon-world/src/heightmap.rs:9), порядок = id."""

    WorldSurfaceWg = 0
    WorldSurface = 1
    OceanFloorWg = 2
    OceanFloor = 3
    MotionBlocking = 4
    MotionBlockingNoLeaves = 5

    @property
    def nbt_name(self) -> str:
        return _HEIGHTMAP_NAMES[self]

    def send_to_client(self) -> bool:
        return self in (
            HeightmapType.WorldSurface,
            HeightmapType.MotionBlocking,
            HeightmapType.MotionBlockingNoLeaves,
        )


_HEIGHTMAP_NAMES = {
    HeightmapType.WorldSurfaceWg: "WORLD_SURFACE_WG",
    HeightmapType.WorldSurface: "WORLD_SURFACE",
    HeightmapType.OceanFloorWg: "OCEAN_FLOOR_WG",
    HeightmapType.OceanFloor: "OCEAN_FLOOR",
    HeightmapType.MotionBlocking: "MOTION_BLOCKING",
    HeightmapType.MotionBlockingNoLeaves: "MOTION_BLOCKING_NO_LEAVES",
}


@dataclass
class Heightmap:
    """``Heightmap``: 256 высот колонны в packed long'ах.

    ``Heightmap::new`` берёт ``bits = 32 - height.leading_zeros()``: для
    ванильных 384 блоков это 9 бит (тест ``9 bits, 256 entries``).
    """

    kind: HeightmapType
    data: BitStorage
    min_y: int = MIN_Y

    @classmethod
    def new(cls, kind: HeightmapType, min_y: int = MIN_Y, height: int = HEIGHT) -> "Heightmap":
        bits = max(1, int(height).bit_length())
        return cls(kind=HeightmapType(kind), data=BitStorage.new(bits, 256), min_y=min_y)

    @classmethod
    def from_longs(
        cls,
        kind: HeightmapType,
        words: Sequence[int],
        min_y: int = MIN_Y,
        height: int = HEIGHT,
    ) -> "Heightmap":
        bits = max(1, int(height).bit_length())
        return cls(
            kind=HeightmapType(kind),
            data=BitStorage.from_words(bits, 256, [_as_u64(w) for w in words]),
            min_y=min_y,
        )

    def bits(self) -> int:
        return self.data.bits()

    def raw_data(self) -> List[int]:
        return self.data.words()

    def to_longs(self) -> List[int]:
        return [_as_i64(word) for word in self.data.words()]

    @staticmethod
    def index(x: int, z: int) -> int:
        """``Heightmap::index``: x + z * 16."""
        return (x & 15) + (z & 15) * 16

    def get(self, x: int, z: int) -> int:
        """Абсолютная высота (``first_available``): min_y + сохранённое."""
        return self.data.get(self.index(x, z)) + self.min_y

    def set(self, x: int, z: int, y: int) -> None:
        self.data.set(self.index(x, z), y - self.min_y)


# ---- BlockEntity (BlockEntityInfo) ----------------------------------------


@dataclass
class BlockEntity:
    """``BlockEntityInfo``: упакованный xz, y, тип и NBT."""

    packed_xz: int
    y: int
    kind: int
    tag: object

    @classmethod
    def read(cls, r: Reader) -> "BlockEntity":
        return cls(
            packed_xz=r.i8(),
            y=r.i16(),
            kind=r.varint(),
            tag=r.nbt(),
        )

    def write(self, w: Writer) -> None:
        w.i8(self.packed_xz)
        w.i16(self.y)
        w.varint(self.kind)
        w.nbt(self.tag)

    @classmethod
    def at(cls, x: int, y: int, z: int, kind: int, tag: object) -> "BlockEntity":
        return cls(packed_xz=((x & 15) << 4) | (z & 15), y=y, kind=kind, tag=tag)

    def x(self) -> int:
        return self.packed_xz >> 4

    def z(self) -> int:
        return self.packed_xz & 15

    def position(self) -> Tuple[int, int, int]:
        return self.x(), self.y, self.z()


# ---- LightData (ClientboundLightUpdatePacketData) -------------------------


@dataclass
class LightData:
    """``LightData``: маски и слои по 2048 байт (sky/block)."""

    sky_mask: bytearray = field(default_factory=bytearray)
    block_mask: bytearray = field(default_factory=bytearray)
    empty_sky_mask: bytearray = field(default_factory=bytearray)
    empty_block_mask: bytearray = field(default_factory=bytearray)
    sky: List[bytes] = field(default_factory=list)
    block: List[bytes] = field(default_factory=list)

    @classmethod
    def read(cls, r: Reader) -> "LightData":
        from quadrix.protocol.buf import BitSet  # локально: без цикла импортов

        return cls(
            sky_mask=BitSet.read(r),
            block_mask=BitSet.read(r),
            empty_sky_mask=BitSet.read(r),
            empty_block_mask=BitSet.read(r),
            sky=_read_layers(r),
            block=_read_layers(r),
        )

    def write(self, w: Writer) -> None:
        from quadrix.protocol.buf import BitSet

        BitSet.write(self.sky_mask, w)
        BitSet.write(self.block_mask, w)
        BitSet.write(self.empty_sky_mask, w)
        BitSet.write(self.empty_block_mask, w)
        _write_layers(self.sky, w)
        _write_layers(self.block, w)

    def layers(self, light_sections: int) -> List[Tuple[Optional[bytes], Optional[bytes]]]:
        """``LightData::layers``: (sky, block) на световую секцию."""
        sky = iter(self.sky)
        block = iter(self.block)
        out: List[Tuple[Optional[bytes], Optional[bytes]]] = []
        for i in range(light_sections):
            if bit(self.sky_mask, i):
                s: Optional[bytes] = next(sky, None)
            elif bit(self.empty_sky_mask, i):
                s = bytes(2048)
            else:
                s = None
            if bit(self.block_mask, i):
                b: Optional[bytes] = next(block, None)
            elif bit(self.empty_block_mask, i):
                b = bytes(2048)
            else:
                b = None
            out.append((s, b))
        return out


def _read_layers(r: Reader) -> List[bytes]:
    n = r.count(r.remaining())
    layers: List[bytes] = []
    for _ in range(n):
        layer = bytes(r.byte_array(2048))
        if len(layer) != 2048:
            raise _invalid(f"DataLayer should be 2048 bytes not: {len(layer)}")
        layers.append(layer)
    return layers


def _write_layers(layers: Sequence[bytes], w: Writer) -> None:
    w.varint(len(layers))
    for layer in layers:
        w.byte_array(layer)


def nibble(layer: Sequence[int], i: int) -> int:
    """``DataLayer.get``: младший ниббл первым."""
    if i >> 1 >= len(layer):
        return 0
    return layer[i >> 1] & 15 if i & 1 == 0 else layer[i >> 1] >> 4


# ---- ChunkData (проводной пакет) ------------------------------------------


@dataclass
class ChunkData:
    """``ClientboundLevelChunkPacketData``: heightmaps, buffer, block entities."""

    heightmaps: List[Tuple[int, List[int]]]
    buffer: bytes
    block_entities: List[BlockEntity]

    @classmethod
    def read(cls, r: Reader) -> "ChunkData":
        n = r.count(16)
        heightmaps = [(r.varint(), r.long_array()) for _ in range(n)]
        buffer = bytes(r.byte_array(r.remaining()))
        entities = [BlockEntity.read(r) for _ in range(r.count(r.remaining()))]
        return cls(heightmaps=heightmaps, buffer=buffer, block_entities=entities)

    def write(self, w: Writer) -> None:
        w.varint(len(self.heightmaps))
        for kind, words in self.heightmaps:
            w.varint(kind)
            w.long_array(words)
        w.byte_array(self.buffer)
        w.varint(len(self.block_entities))
        for entity in self.block_entities:
            entity.write(w)

    def sections(
        self,
        count: int,
        block_bits: int = BLOCK_BITS,
        biome_bits: int = BIOME_BITS,
    ) -> List[ChunkSection]:
        """Декодирует ``count`` секций из ``buffer``."""
        r = Reader(self.buffer)
        sections = [ChunkSection.read(r, block_bits, biome_bits) for _ in range(count)]
        if r.remaining():
            raise _invalid(f"chunk buffer has {r.remaining()} trailing bytes")
        return sections

    @staticmethod
    def from_sections(sections: Sequence[ChunkSection]) -> bytes:
        """Кодирует секции в ``buffer`` (``ChunkData::from_sections``)."""
        w = Writer()
        for section in sections:
            section.write(w)
        return w.to_bytes()


# ---- ColumnLayout (render/src/chunk.rs:136) -------------------------------


@dataclass(frozen=True)
class ColumnLayout:
    """``ColumnLayout``: min_y и число секций колонны."""

    min_y: int = MIN_Y
    section_count: int = SECTIONS

    LOWEST_Y = -2032
    HIGHEST_Y = 2031

    @classmethod
    def of_level(cls, min_y: int, height: int) -> "ColumnLayout":
        low = min(min_y, MIN_Y)
        high = max(min_y + height, MIN_Y + HEIGHT)
        return cls(min_y=low, section_count=(high - low) // 16)

    @classmethod
    def new(cls, min_y: int, height: int) -> "ColumnLayout":
        if min_y % 16 or height % 16:
            raise _invalid(f"min_y {min_y} and height {height} must be multiples of 16")
        if height < 16:
            raise _invalid(f"height {height} is below 16")
        if min_y < cls.LOWEST_Y or min_y + height > cls.HIGHEST_Y + 1:
            raise _invalid(
                f"min_y {min_y} with height {height} leaves "
                f"{cls.LOWEST_Y}..={cls.HIGHEST_Y}"
            )
        return cls(min_y=min_y, section_count=height // 16)

    def max_y(self) -> int:
        return self.min_y + self.height()

    def height(self) -> int:
        return self.section_count * 16

    def sections(self) -> int:
        return self.section_count

    def section_index(self, y: int) -> Optional[int]:
        index = (y - self.min_y) >> 4
        if index < 0 or index >= self.section_count:
            return None
        return index

    def section_y(self, index: int) -> int:
        return self.min_y + index * 16


ColumnLayout.VANILLA = ColumnLayout(MIN_Y, SECTIONS)


# ---- Chunk (render/src/chunk.rs:556) + разбор пакета ----------------------


@dataclass
class Chunk:
    """Колонна клиента: секции, heightmaps, block entities и свет."""

    x: int
    z: int
    min_y: int
    sections: List[ChunkSection]
    heightmaps: Dict[HeightmapType, Heightmap] = field(default_factory=dict)
    block_entities: List[BlockEntity] = field(default_factory=list)
    light: Optional[LightData] = None
    lit: bool = False
    light_loaded: bool = False

    # -- создание --
    @classmethod
    def empty(cls, x: int, z: int) -> "Chunk":
        return cls.with_layout(x, z, ColumnLayout.VANILLA)

    @classmethod
    def with_layout(cls, x: int, z: int, layout: ColumnLayout) -> "Chunk":
        return cls(
            x=x,
            z=z,
            min_y=layout.min_y,
            sections=[ChunkSection.uniform() for _ in range(layout.sections())],
        )

    @classmethod
    def from_chunk_data(
        cls,
        x: int,
        z: int,
        data: ChunkData,
        layout: Optional[ColumnLayout] = None,
        block_bits: int = BLOCK_BITS,
        biome_bits: int = BIOME_BITS,
    ) -> "Chunk":
        """Сырой ``ChunkData`` (play.py) -> секции, heightmaps, block entities."""
        layout = layout or ColumnLayout.VANILLA
        decoded = data.sections(layout.sections(), block_bits, biome_bits)
        chunk = cls.with_layout(x, z, layout)
        chunk.sections = decoded
        for kind, words in data.heightmaps:
            try:
                height_kind = HeightmapType(kind)
            except ValueError as exc:
                raise _invalid(f"unknown heightmap type {kind}") from exc
            chunk.heightmaps[height_kind] = Heightmap.from_longs(
                height_kind, words, layout.min_y, layout.height()
            )
        chunk.block_entities = [
            BlockEntity(e.packed_xz, e.y, e.kind, e.tag) for e in data.block_entities
        ]
        return chunk

    @classmethod
    def from_packet(
        cls,
        packet: object,
        layout: Optional[ColumnLayout] = None,
        block_bits: int = BLOCK_BITS,
        biome_bits: int = BIOME_BITS,
    ) -> "Chunk":
        """``ClientboundLevelChunkWithLight`` -> колонна (chunk + light)."""
        chunk = cls.from_chunk_data(
            packet.x, packet.z, packet.chunk, layout, block_bits, biome_bits
        )
        light = getattr(packet, "light", None)
        if light is not None:
            chunk.light = light
        return chunk

    def to_chunk_data(
        self,
        block_bits: int = BLOCK_BITS,
        biome_bits: int = BIOME_BITS,
    ) -> ChunkData:
        """Обратное кодирование для тестов и сохранения."""
        heightmaps = [
            (int(kind), heightmap.to_longs())
            for kind, heightmap in sorted(self.heightmaps.items(), key=lambda kv: int(kv[0]))
        ]
        return ChunkData(
            heightmaps=heightmaps,
            buffer=ChunkData.from_sections(self.sections),
            block_entities=list(self.block_entities),
        )

    # -- геометрия --
    def layout(self) -> ColumnLayout:
        return ColumnLayout(self.min_y, len(self.sections))

    def max_y(self) -> int:
        return self.min_y + len(self.sections) * 16

    def section_index(self, y: int) -> Optional[int]:
        index = (y - self.min_y) >> 4
        if index < 0 or index >= len(self.sections):
            return None
        return index

    @staticmethod
    def index(x: int, y: int, z: int) -> int:
        """``index``: (y & 15) << 8 | (z & 15) << 4 | (x & 15)."""
        return ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)

    def get(self, x: int, y: int, z: int) -> int:
        section = self.section_index(y)
        if section is None:
            return 0
        return self.sections[section].get(self.index(x, y, z))

    def block(self, x: int, y: int, z: int) -> BlockStateId:
        return BlockStateId(self.get(x, y, z))

    def set(self, x: int, y: int, z: int, value: int) -> int:
        section = self.section_index(y)
        if section is None:
            return value
        return self.sections[section].set(self.index(x, y, z), value)

    # -- heightmaps мира --
    def heightmap(self, kind: HeightmapType) -> Optional[Heightmap]:
        return self.heightmaps.get(HeightmapType(kind))

    def _prime(self, counts) -> List[int]:
        """``Heightmap.primeHeightmaps``: сверху вниз по секциям."""
        surface = [self.min_y] * 256
        found = [False] * 256
        left = 256
        for s in range(len(self.sections) - 1, -1, -1):
            if left == 0:
                break
            values = self.sections[s].unpack()
            uniform = self.sections[s].states.uniform()
            if uniform is not None and not counts(uniform):
                continue
            base = self.min_y + s * 16
            for i in range(256):
                if found[i]:
                    continue
                for dy in range(15, -1, -1):
                    if counts(values[(dy << 8) | i]):
                        surface[i] = base + dy + 1
                        found[i] = True
                        left -= 1
                        break
        return surface

    def world_surface(self, x: int, z: int, air=lambda v: v == 0) -> int:
        """``getHeight(WORLD_SURFACE)``: на один выше последнего не-air."""
        return self._prime(lambda v: not air(v))[self.index(x, 0, z)]

    def motion_blocking(self, x: int, z: int, blocks) -> int:
        return self._prime(blocks)[self.index(x, 0, z)]

    # -- биомы --
    def biome(self, x: int, y: int, z: int) -> int:
        qy = max(0, min((y - self.min_y) >> 2, len(self.sections) * 4 - 1))
        return self.sections[qy >> 2].biomes.get(
            ((qy & 3) << 4) | (((z & 15) >> 2) << 2) | ((x & 15) >> 2)
        )


# ---- Сохранённый формат: NBT-палитра (world/src/chunk.rs) -----------------


def block_state_from_nbt(tag: Tag) -> BlockState:
    """``BlockState::from_nbt`` — строка или compound с id/properties."""
    return BlockState.from_nbt(tag)


def block_state_to_nbt(state: BlockState) -> Tag:
    """``BlockState::to_nbt``: {id: String, properties: Compound?}."""
    fields: Dict[str, Tag] = {"id": Tag(TagType.String, str_val=state.name)}
    if state.properties and len(state.properties) > 0:
        fields["properties"] = Tag(
            tag_type=TagType.Compound,
            compound_val={
                key: Tag(TagType.String, str_val=value)
                for key, value in state.properties.items()
            },
        )
    return Tag(tag_type=TagType.Compound, compound_val=fields)


@dataclass
class NbtPalettedContainer:
    """``PalettedContainer`` сохранения: палитра из NBT-тегов + словарь."""

    palette: List[Tag]
    storage: Optional[BitStorage]
    entries: int
    min_bits: int
    extra: Dict[str, Tag] = field(default_factory=dict)

    @classmethod
    def uniform(cls, value: Tag, entries: int, min_bits: int) -> "NbtPalettedContainer":
        if entries == 0 or not 1 <= min_bits <= 32:
            raise _invalid("invalid palette dimensions")
        if value.is_end:
            raise _invalid("End cannot be a palette entry")
        return cls(palette=[value], storage=None, entries=entries, min_bits=min_bits)

    @classmethod
    def from_nbt(cls, tag: Tag, entries: int, min_bits: int) -> "NbtPalettedContainer":
        if not tag.is_compound or tag.compound_val is None:
            raise _invalid("palette container is not a compound")
        mapping = tag.compound_val
        palette_tag = mapping.get("palette")
        if palette_tag is None or not palette_tag.is_list or palette_tag.list_val is None:
            raise _invalid("missing palette list")
        palette = list(palette_tag.list_val)
        if not palette:
            raise _invalid("empty palette")
        result = cls.uniform(palette[0], entries, min_bits)
        if len(palette) > _I32_MAX or any(t.is_end for t in palette):
            raise _invalid("invalid palette")
        result.palette = palette
        bits = bits_for_palette(len(palette), min_bits)
        if bits > 0:
            data_tag = mapping.get("data")
            if data_tag is None or not data_tag.is_longarray or data_tag.longarray_val is None:
                raise _invalid("nonuniform palette is missing data")
            storage = BitStorage.from_words(
                bits, entries, [_as_u64(w) for w in data_tag.longarray_val]
            )
            for index in range(entries):
                if storage.get(index) >= len(palette):
                    raise _invalid("palette index outside palette")
            result.storage = storage
        result.extra = {
            key: value for key, value in mapping.items() if key not in ("palette", "data")
        }
        return result

    def bits(self) -> int:
        return self.storage.bits() if self.storage is not None else 0

    def palette_len(self) -> int:
        return len(self.palette)

    def get(self, index: int) -> Tag:
        if not 0 <= index < self.entries:
            raise _invalid("section index out of bounds")
        palette_index = self.storage.get(index) if self.storage is not None else 0
        return self.palette[palette_index]

    def set(self, index: int, value: Tag) -> Tag:
        old = self.get(index)
        if value.is_end:
            raise _invalid("End cannot be a palette entry")
        if value in self.palette:
            entry = self.palette.index(value)
        else:
            if len(self.palette) >= _I32_MAX:
                raise _invalid("palette too large")
            next_bits = bits_for_palette(len(self.palette) + 1, self.min_bits)
            if next_bits != self.bits():
                next_storage = BitStorage.new(next_bits, self.entries)
                if self.storage is not None:
                    for i in range(self.entries):
                        next_storage.set(i, self.storage.get(i))
                self.storage = next_storage
            self.palette.append(value)
            entry = len(self.palette) - 1
        if self.storage is not None:
            self.storage.set(index, entry)
        return old

    def compact(self) -> None:
        """Пересобрать минимальную палитру в порядке первого использования."""
        values = [self.get(i) for i in range(self.entries)]
        if not values:
            return
        compact = type(self).uniform(values[0], self.entries, self.min_bits)
        for i, value in enumerate(values):
            compact.set(i, value)
        compact.extra = self.extra
        self.palette = compact.palette
        self.storage = compact.storage
        self.extra = compact.extra

    def to_nbt(self) -> Tag:
        mapping = dict(self.extra)
        mapping["palette"] = Tag(tag_type=TagType.List, list_val=list(self.palette))
        if self.storage is not None:
            mapping["data"] = Tag(
                tag_type=TagType.LongArray,
                longarray_val=[_as_i64(word) for word in self.storage.words()],
            )
        return Tag(tag_type=TagType.Compound, compound_val=mapping)


def _id_in(
    palette: Sequence[BlockStateId],
    counts: Sequence[int],
    state: BlockStateId,
) -> Optional[int]:
    """``id_in``: живой слот палитры для состояния."""
    for index, (value, count) in enumerate(zip(palette, counts)):
        if count != 0 and value == state:
            return index
    return None


@dataclass
class BlockSection:
    """``BlockSection``: резидентная секция с числовыми id реестра."""

    palette: List[BlockStateId]
    counts: List[int]
    free: List[int]
    storage: Optional[BitStorage]
    registry: BlockRegistry
    extra: Dict[str, Tag] = field(default_factory=dict)

    @classmethod
    def uniform(cls, state: BlockStateId, registry: BlockRegistry) -> "BlockSection":
        if registry.state(state) is None:
            raise _invalid("state ID outside registry")
        return cls(
            palette=[state],
            counts=[BLOCKS],
            free=[],
            storage=None,
            registry=registry,
        )

    @classmethod
    def from_nbt(cls, tag: Tag, registry: BlockRegistry) -> "BlockSection":
        container = NbtPalettedContainer.from_nbt(tag, BLOCKS, 4)
        resolved = [
            registry.resolve(block_state_from_nbt(entry)) for entry in container.palette
        ]
        first = container.storage.get(0) if container.storage is not None else 0
        section = cls.uniform(resolved[first], registry)
        for index in range(BLOCKS):
            entry = container.storage.get(index) if container.storage is not None else 0
            section.set(index, resolved[entry])
        section.extra = container.extra
        return section

    # -- доступ --
    def bits(self) -> int:
        return self.storage.bits() if self.storage is not None else 0

    def storage_bits(self) -> int:
        return self.bits()

    def registry_ref(self) -> BlockRegistry:
        return self.registry

    def any_state(self, predicate) -> bool:
        return any(
            count != 0 and predicate(state)
            for state, count in zip(self.palette, self.counts)
        )

    def state(self, index: int) -> BlockStateId:
        palette_index = self.storage.read(index) if self.storage is not None else 0
        return self.palette[palette_index]

    def get(self, index: int) -> BlockStateId:
        if not 0 <= index < BLOCKS:
            raise _invalid("section index out of bounds")
        return self.state(index)

    def uniform_state(self) -> Optional[BlockStateId]:
        return self.palette[0] if self.storage is None else None

    def fill_states(self, out: List[int]) -> None:
        if self.storage is None:
            value = self.palette[0].id
            for i in range(BLOCKS):
                out[i] = value
            return
        raw = self.storage.unpack()
        for i, value in enumerate(raw):
            out[i] = self.palette[value].id

    def set(self, index: int, state: BlockStateId) -> BlockStateId:
        if not 0 <= index < BLOCKS:
            raise _invalid("section index out of bounds")
        if not 0 <= state.id < self.registry.len():
            raise _invalid("state ID outside registry")
        old_index = self.storage.read(index) if self.storage is not None else 0
        old = self.palette[old_index]
        if old == state:
            return old

        entry = _id_in(self.palette, self.counts, state)
        if entry is None and self.counts[old_index] == 1:
            # Последнее вхождение старого состояния: слот можно занять.
            self.palette[old_index] = state
            return old
        if entry is None:
            if self.free:
                entry = self.free.pop()
                self.palette[entry] = state
            else:
                entry = len(self.palette)
                next_bits = bits_for_palette(len(self.palette) + 1, 4)
                if next_bits != self.bits():
                    next_storage = BitStorage.new(next_bits, BLOCKS)
                    if self.storage is not None:
                        for i in range(BLOCKS):
                            next_storage.write(i, self.storage.read(i))
                    self.storage = next_storage
                self.palette.append(state)
                self.counts.append(0)

        if self.storage is None:
            raise _invalid("section storage missing for palette entry")
        self.storage.write(index, entry)
        self.counts[old_index] -= 1
        self.counts[entry] += 1
        if self.counts[old_index] == 0:
            self.free.append(old_index)

        if self.counts[entry] == BLOCKS:
            self.palette = [state]
            self.counts = [BLOCKS]
            self.free.clear()
            self.storage = None
        return old

    def fill_run(
        self,
        x: int,
        y_start: int,
        z: int,
        length: int,
        state: BlockStateId,
        air: BlockStateId,
    ) -> int:
        """``fill_run``: вертикальный прогон, возвращает добавленные не-air."""
        if (
            not 0 <= x < 16
            or not 0 <= z < 16
            or length <= 0
            or y_start < 0
            or y_start + length > 16
        ):
            raise _invalid("section fill outside its bounds")

        def index(y: int) -> int:
            return (y << 8) | (z << 4) | x

        top = y_start + length - 1
        added = 0
        old = self.set(index(top), state)
        if old == air:
            added += 1
        entry = _id_in(self.palette, self.counts, state)
        if entry is None or self.storage is None:
            return added
        for y in range(top - 1, y_start - 1, -1):
            i = index(y)
            old_index = self.storage.read(i)
            old_state = self.palette[old_index]
            if old_state == state:
                continue
            self.storage.write(i, entry)
            self.counts[old_index] -= 1
            self.counts[entry] += 1
            if old_state == air:
                added += 1
            if self.counts[old_index] == 0:
                self.free.append(old_index)
        if self.counts[entry] == BLOCKS:
            self.palette = [state]
            self.counts = [BLOCKS]
            self.free.clear()
            self.storage = None
        return added

    def compact(self) -> None:
        values = [self.get(i) for i in range(BLOCKS)]
        self.palette.clear()
        self.counts.clear()
        self.free.clear()
        for state in values:
            entry = _id_in(self.palette, self.counts, state)
            if entry is not None:
                self.counts[entry] += 1
            else:
                self.palette.append(state)
                self.counts.append(1)
        bits = bits_for_palette(len(self.palette), 4)
        if bits == 0:
            self.storage = None
            return
        storage = BitStorage.new(bits, BLOCKS)
        for i, state in enumerate(values):
            entry = _id_in(self.palette, self.counts, state)
            storage.set(i, entry if entry is not None else 0)
        self.storage = storage

    def to_nbt(self) -> Tag:
        mapping = dict(self.extra)
        palette: List[Tag] = []
        for state_id in self.palette:
            state = self.registry.state(state_id)
            if state is None:
                raise _invalid("state ID outside registry")
            palette.append(block_state_to_nbt(state))
        mapping["palette"] = Tag(tag_type=TagType.List, list_val=palette)
        if self.storage is not None:
            mapping["data"] = Tag(
                tag_type=TagType.LongArray,
                longarray_val=[_as_i64(word) for word in self.storage.words()],
            )
        return Tag(tag_type=TagType.Compound, compound_val=mapping)


# ---- NbtChunkData (сохранённый чанк, world/src/chunk.rs) -----------------


class NbtChunkData:
    """``ChunkData`` сохранения: корневой compound + позиция."""

    def __init__(self, root: Dict[str, Tag], position: Tuple[int, int]) -> None:
        self._root = root
        self._position = position

    @classmethod
    def new(cls, root: Dict[str, Tag]) -> "NbtChunkData":
        if "xPos" not in root or not root["xPos"].is_int:
            raise _invalid("chunk is missing xPos")
        if "zPos" not in root or not root["zPos"].is_int:
            raise _invalid("chunk is missing zPos")
        position = (root["xPos"].int_val, root["zPos"].int_val)
        if "DataVersion" not in root or not root["DataVersion"].is_int:
            raise _invalid("chunk is missing DataVersion")
        version = root["DataVersion"].int_val
        if version != DATA_VERSION:
            raise _invalid(
                f"expected DataVersion {DATA_VERSION}, got {version}; "
                "data fixing is not implemented"
            )
        sections = root.get("sections")
        if sections is None or not sections.is_list or sections.list_val is None:
            raise _invalid("chunk is missing sections")
        seen = set()
        for section in sections.list_val:
            y_tag = section.compound_val.get("Y") if section.is_compound else None
            if y_tag is None or not y_tag.is_byte:
                raise _invalid("section is missing byte Y")
            if y_tag.byte_val in seen:
                raise _invalid("duplicate section Y")
            seen.add(y_tag.byte_val)
        return cls(root, position)

    def position(self) -> Tuple[int, int]:
        return self._position

    def into_nbt(self) -> Dict[str, Tag]:
        return self._root

    def root(self) -> Dict[str, Tag]:
        return self._root

    def _section_index(self, block: Tuple[int, int, int]) -> Optional[int]:
        x, y, z = block
        if (x >> 4, z >> 4) != self._position:
            raise _invalid("block is outside this chunk")
        section_y = y >> 4
        if not -128 <= section_y <= 127:
            raise _invalid("block height outside saved section range")
        sections = self._root["sections"].list_val or []
        for index, section in enumerate(sections):
            y_tag = section.compound_val.get("Y")
            if y_tag is not None and y_tag.byte_val == section_y:
                return index
        return None

    def block(self, block: Tuple[int, int, int]) -> Optional[BlockState]:
        index = self._section_index(block)
        if index is None:
            return None
        sections = self._root["sections"].list_val or []
        container_tag = sections[index].compound_val.get("block_states")
        if container_tag is None:
            return None
        x, y, z = block
        palette = NbtPalettedContainer.from_nbt(container_tag, BLOCKS, 4)
        section_index = ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)
        return block_state_from_nbt(palette.get(section_index))

    def set_block_data(self, block: Tuple[int, int, int], state: BlockState) -> BlockState:
        index = self._section_index(block)
        if index is None:
            raise _invalid("section is not present")
        sections = self._root["sections"].list_val or []
        section = sections[index]
        container_tag = section.compound_val.get("block_states")
        if container_tag is None:
            raise _invalid("section has no block-state data")
        x, y, z = block
        section_index = ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)
        palette = NbtPalettedContainer.from_nbt(container_tag, BLOCKS, 4)
        old = block_state_from_nbt(palette.get(section_index))
        palette.set(section_index, block_state_to_nbt(state))
        section.compound_val["block_states"] = palette.to_nbt()
        return old


def __getattr__(name: str):
    """``ChunkPos`` уже в buf.py; отдаём его и отсюда без второго класса."""
    if name == "ChunkPos":
        from quadrix.protocol.buf import ChunkPos

        return ChunkPos
    raise AttributeError(f"[QuadRix] module {__name__!r} has no attribute {name!r}")