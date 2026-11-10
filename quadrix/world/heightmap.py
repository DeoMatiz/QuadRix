#!/usr/bin/env python3
"""Heightmaps: упакованные высоты колонн и шесть предикатов Java 26.3.

Порт ``horizon/crates/horizon-world/src/heightmap.rs`` (Minecraft 26.3).

Поведение по блокам (air/fluid, членство в тегах) поставляет блоковое
поведение.  Heightmap не выводит эти факты из формы коллизии или имени блока —
он спрашивает реализацию ``HeightmapState``.  Позиции ``x``/``z`` всегда в
``0..16`` (локальные для чанка).
"""

from __future__ import annotations

from enum import IntEnum
from typing import List, Protocol, runtime_checkable

__all__ = [
    "MIN_Y",
    "HEIGHT",
    "HEIGHTMAP_TYPES",
    "HeightmapType",
    "HeightmapState",
    "HeightmapChunk",
    "HeightmapError",
    "Heightmap",
]

# Пределы вертикального диапазона кодека (heightmap.rs:112).
_LOWEST_Y = -2032
_HIGHEST_Y = 2031

# Ванильные значения колонны Overworld (render/src/chunk.rs::ColumnLayout).
MIN_Y = -64
HEIGHT = 384

_I32_MASK = 0xFFFFFFFF


def _invalid(reason: str) -> ValueError:
    """``compression::invalid`` — ошибка формата с префиксом QuadRix."""
    return ValueError(f"[QuadRix] {reason}")


def _storage_cls():
    """``horizon_core::storage::PackedStorage`` -> ``BitStorage`` (chunk.py).

    Импорт ленивый: ``chunk`` импортирует этот модуль сверху, обратная
    зависимость на верхнем уровне дала бы цикл.
    """
    from quadrix.world.chunk import BitStorage

    return BitStorage


# ---- HeightmapType (heightmap.rs:9) ----------------------------------------


class HeightmapType(IntEnum):
    """Шесть типов карт высот; порядок = ``repr(u8)`` из Rust."""

    WorldSurfaceWg = 0
    WorldSurface = 1
    OceanFloorWg = 2
    OceanFloor = 3
    MotionBlocking = 4
    MotionBlockingNoLeaves = 5

    def name(self) -> str:
        """``HeightmapType::name``: проводное имя в верхнем регистре."""
        return _HEIGHTMAP_NAMES[self]

    @property
    def nbt_name(self) -> str:
        """Псевдоним ``name`` для сохранённого формата."""
        return _HEIGHTMAP_NAMES[self]

    def send_to_client(self) -> bool:
        """``send_to_client``: три карты уходят в пакет чанка."""
        return self in (
            HeightmapType.WorldSurface,
            HeightmapType.MotionBlocking,
            HeightmapType.MotionBlockingNoLeaves,
        )

    def keep_after_worldgen(self) -> bool:
        """``keep_after_worldgen``: WG-карты не сохраняются на диск."""
        return self not in (HeightmapType.WorldSurfaceWg, HeightmapType.OceanFloorWg)

    def is_opaque(self, state: "HeightmapState") -> bool:
        """``is_opaque``: считается ли блок «препятствием» для этого типа."""
        if self is HeightmapType.WorldSurfaceWg or self is HeightmapType.WorldSurface:
            return not state.is_air()
        if self is HeightmapType.OceanFloorWg or self is HeightmapType.OceanFloor:
            return state.blocks_motion_in_heightmap()
        if self is HeightmapType.MotionBlocking:
            return state.blocks_motion_in_heightmap() or state.has_fluid()
        return state.blocks_motion_in_heightmap_no_leaves() or state.has_fluid()


_HEIGHTMAP_NAMES = {
    HeightmapType.WorldSurfaceWg: "WORLD_SURFACE_WG",
    HeightmapType.WorldSurface: "WORLD_SURFACE",
    HeightmapType.OceanFloorWg: "OCEAN_FLOOR_WG",
    HeightmapType.OceanFloor: "OCEAN_FLOOR",
    HeightmapType.MotionBlocking: "MOTION_BLOCKING",
    HeightmapType.MotionBlockingNoLeaves: "MOTION_BLOCKING_NO_LEAVES",
}


# ``HeightmapType::ALL`` — присваиваем после класса: ``ALL`` внутри тела Enum
# стал бы лишним членом (heightmap.rs:19).
HEIGHTMAP_TYPES: List[HeightmapType] = [
    HeightmapType.WorldSurfaceWg,
    HeightmapType.WorldSurface,
    HeightmapType.OceanFloorWg,
    HeightmapType.OceanFloor,
    HeightmapType.MotionBlocking,
    HeightmapType.MotionBlockingNoLeaves,
]

HeightmapType.ALL = HEIGHTMAP_TYPES  # type: ignore[attr-defined]


# ---- HeightmapState / HeightmapChunk (heightmap.rs:62) ---------------------


@runtime_checkable
class HeightmapState(Protocol):
    """``trait HeightmapState``: факты о блоке, нужные heightmap'ам."""

    def is_air(self) -> bool:
        """Не-air (включая пещерный/пустотный воздух)."""
        ...

    def is_air_block(self) -> bool:
        """Точная идентичность блока AIR, отдельно от cave/void air."""
        ...

    def has_fluid(self) -> bool:
        """Блок содержит жидкость."""
        ...

    def blocks_motion_in_heightmap(self) -> bool:
        """Тег ``blocks_motion`` для карт высот."""
        ...

    def blocks_motion_in_heightmap_no_leaves(self) -> bool:
        """Тег ``blocks_motion`` без листвы."""
        ...


@runtime_checkable
class HeightmapChunk(Protocol):
    """``trait HeightmapChunk``: доступ к блокам и вертикали чанка."""

    def min_y(self) -> int:
        ...

    def height(self) -> int:
        ...

    def highest_section_y(self) -> int:
        """Базовая y самой верхней секции чанка."""
        ...

    def block_state(self, x: int, y: int, z: int) -> HeightmapState:
        ...


# ---- HeightmapError (heightmap.rs:79) --------------------------------------


class HeightmapError(Exception):
    """``enum HeightmapError``: неверные границы, чужой чанк, хранилище."""

    INVALID_BOUNDS = "InvalidBounds"
    MISMATCHED_CHUNK = "MismatchedChunk"
    STORAGE = "Storage"

    def __init__(self, kind: str, detail: str = "") -> None:
        self.kind = kind
        self.detail = detail
        message = f"[QuadRix] heightmap: {kind}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


# ---- Heightmap (heightmap.rs:97) -------------------------------------------


class Heightmap:
    """``struct Heightmap``: packed-высоты + min_y/height колонны."""

    def __init__(self, kind: HeightmapType, min_y: int, height: int, data) -> None:
        self.kind = HeightmapType(kind)
        self.min_y = min_y
        self.height = height
        self.data = data

    # -- создание --
    @classmethod
    def new(cls, kind: HeightmapType, min_y: int = MIN_Y, height: int = HEIGHT) -> "Heightmap":
        """``Heightmap::new``: проверяет границы кодека и делает хранилище."""
        if (
            not (_LOWEST_Y <= min_y <= _HIGHEST_Y)
            or not (16 <= height <= 4064)
            or min_y % 16 != 0
            or height % 16 != 0
            or min_y + height > 2032
        ):
            raise HeightmapError(HeightmapError.INVALID_BOUNDS)
        bits = int(height).bit_length()
        data = _storage_cls().new(bits, 256)
        return cls(kind, min_y, height, data)

    @classmethod
    def from_longs(
        cls,
        kind: HeightmapType,
        words,
        min_y: int = MIN_Y,
        height: int = HEIGHT,
    ) -> "Heightmap":
        """Сборка из сырых long'ов (сохранённый/проводной формат)."""
        bits = int(height).bit_length()
        values = [int(w) & ((1 << 64) - 1) for w in words]
        data = _storage_cls().from_words(bits, 256, values)
        return cls(kind, min_y, height, data)

    # -- чтение --
    def raw_data(self) -> List[int]:
        """``raw_data``: сырые long'и как u64."""
        return self.data.words()

    def heap_bytes(self) -> int:
        """``heap_bytes``: 8 байт на long хранилища."""
        return len(self.data.words()) * 8

    def bits(self) -> int:
        return self.data.bits()

    def to_longs(self) -> List[int]:
        """Сырые long'и как знаковые i64 (для NBT/пакета)."""
        return [
            w - (1 << 64) if w >= (1 << 63) else w for w in self.data.words()
        ]

    @staticmethod
    def index(x: int, z: int) -> int:
        """``Heightmap::index``: ``x + z * 16``."""
        return x + z * 16

    # -- packed-доступ через хранилище --
    def _read(self, index: int) -> int:
        try:
            return self.data.get(index)
        except ValueError as error:  # pragma: no cover - индекс всегда валиден
            raise HeightmapError(HeightmapError.STORAGE, str(error)) from error

    def _write(self, index: int, value: int) -> None:
        try:
            self.data.set(index, value)
        except ValueError as error:
            raise HeightmapError(HeightmapError.STORAGE, str(error)) from error

    # -- высоты --
    def below_update(self, chunk: HeightmapChunk, x: int, y: int, z: int) -> bool:
        """``below_update``: ``update`` выйдет сразу — блок на 2+ ниже опоры.

        Несовпадение вертикали чанка даёт ``False`` (в Rust — ``is_ok``).
        """
        first = self.first_available(x, z)
        if y > first - 2:
            return False
        try:
            self.check_chunk(chunk)
        except HeightmapError:
            return False
        return True

    def first_available(self, x: int, z: int) -> int:
        """``first_available``: первая свободная (непрозрачная-1) высота."""
        return self._read(self.index(x, z)) + self.min_y

    def any_first_available_at_least(
        self, x_range, z_range, y: int
    ) -> bool:
        """``any_first_available_at_least``: есть колонна с first >= y."""
        x0, x1 = x_range
        z0, z1 = z_range
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                if self._read(self.index(x, z)) + self.min_y >= y:
                    return True
        return False

    def highest_taken(self, x: int, z: int) -> int:
        """``highest_taken``: ``first_available - 1``."""
        value = self.first_available(x, z) - 1
        return value

    def get(self, x: int, z: int) -> int:
        """Абсолютная высота колонны (``first_available``)."""
        return self.first_available(x, z)

    def set(self, x: int, z: int, y: int) -> None:
        """Прямая запись высоты колонны (как ``set_height``)."""
        self._set_height(x, z, y)

    def _set_height(self, x: int, z: int, y: int) -> None:
        raw = (y - self.min_y) & _I32_MASK
        self._write(self.index(x, z), raw)

    def check_chunk(self, chunk: HeightmapChunk) -> None:
        """``check_chunk``: вертикаль карты должна совпадать с чанком."""
        if chunk.min_y() != self.min_y or chunk.height() != self.height:
            raise HeightmapError(HeightmapError.MISMATCHED_CHUNK)

    # -- обновление --
    def update(self, chunk: HeightmapChunk, x: int, y: int, z: int, state) -> bool:
        """``update``: блок уже записан в чанк; правим карту.

        Возвращает ``True``, если карта изменилась.
        """
        self.check_chunk(chunk)
        first = self.first_available(x, z)
        if y <= first - 2:
            return False
        if self.kind.is_opaque(state):
            if y >= first:
                self._set_height(x, z, y + 1)
                return True
        elif y == first - 1:
            scan_y = y - 1
            while scan_y >= self.min_y:
                if self.kind.is_opaque(chunk.block_state(x, scan_y, z)):
                    self._set_height(x, z, scan_y + 1)
                    return True
                scan_y -= 1
            self._set_height(x, z, self.min_y)
            return True
        return False

    def set_raw_data(self, chunk: HeightmapChunk, words) -> None:
        """``set_raw_data``: сохраняет все биты при совпадении длины."""
        self.check_chunk(chunk)
        words = list(words)
        if len(words) == len(self.data.words()):
            values = [int(w) & ((1 << 64) - 1) for w in words]
            self.data = _storage_cls().from_words(self.data.bits(), 256, values)
        else:
            self.prime(chunk, [self])

    @staticmethod
    def prime(chunk: HeightmapChunk, maps: List["Heightmap"]) -> None:
        """``prime``: заново заполняет карты, скан X, затем Z, затем Y вниз."""
        if not maps:
            return
        for heightmap in maps:
            heightmap.check_chunk(chunk)
        upper = chunk.highest_section_y() + 16
        for x in range(16):
            for z in range(16):
                remaining = list(range(len(maps)))
                y = upper - 1
                while y >= chunk.min_y():
                    state = chunk.block_state(x, y, z)
                    if not state.is_air_block():
                        i = 0
                        while i < len(remaining):
                            heightmap = maps[remaining[i]]
                            if heightmap.kind.is_opaque(state):
                                heightmap._set_height(x, z, y + 1)
                                remaining.pop(i)
                            else:
                                i += 1
                        if not remaining:
                            break
                    y -= 1
