#!/usr/bin/env python3
"""Кэшированные формы столкновений блоков (без контекста мира).

Порт horizon/crates/horizon-world/src/block_collision.rs и
horizon/crates/horizon-world/src/collision.rs (Minecraft 26.3).

Данные берутся из:
  .local/horizon-client-collision/cached-collision.nbt
  .local/horizon-client-collision/block-registry.nbt

`cached-collision.nbt` содержит:
  * ``shapes``        — список описаний сеток/кубов (LongArray биты f64,
                        ByteArray занятости, cube/cube_axes/canonical,
                        discrete_min/discrete_max);
  * ``cached_shapes`` — IntArray: id состояния -> индекс в ``shapes`` (-1 =
                        форма не кэширована, нужна block behavior);
  * ``states``        — идентичности состояний в порядке id (сверяются с
                        block-registry.nbt);
  * ``DataVersion``.

Функции портированы один-к-одному, включая жадное разложение сетки на
прямоугольники (VoxelShape::decompose), чтобы число и границы боксов
совпадали с Rust.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union
from weakref import WeakKeyDictionary

from quadrix.core.geometry import Aabb, Direction, Vec3
from quadrix.world import nbt as _nbt
from quadrix.world.nbt import Tag, TagType
from quadrix.world.registry import (
    DATA_VERSION,
    BlockRegistry,
    BlockState,
    BlockStateId,
)

__all__ = [
    "VoxelShape",
    "CachedCollisionRegistry",
    "ShulkerCollisionState",
    "read_collision_nbt",
    "load_cached_collision",
    "default_collision_registry",
    "collision_shape",
    "block_collision_boxes",
    "full_cube",
]

# collision.rs:15 — версия данных, ожидаемая в cached-collision.nbt.
COLLISION_DATA_VERSION = DATA_VERSION

# Корень данных столкновений (AGENTS.md: путь фиксирован).
COLLISION_ROOT = Path(".local/horizon-client-collision")
COLLISION_FILE = COLLISION_ROOT / "cached-collision.nbt"

# Ограничения VoxelShape из horizon-core (shape.rs:554).
MAX_VOLUME = 1_048_576
MAX_COORDINATES = 1_048_577

# i32::MAX / i32::MIN + 1 — маркеры пустого join-результата (shape.rs:297).
_I32_MAX = 2_147_483_647
_I32_MIN_PLUS_ONE = -2_147_483_647


# ---------------------------------------------------------------------------
# Вспомогательные преобразования
# ---------------------------------------------------------------------------

def _f64_from_bits(bits: int) -> float:
    """f64::from_bits для значения LongArray (целое со знаком)."""
    return struct.unpack(">d", struct.pack(">q", bits))[0]


def _f64_bits(value: float) -> int:
    """Аналог v.to_bits() для сравнения координат побитово."""
    return struct.unpack(">q", struct.pack(">d", value))[0]


def _f32(value: float) -> float:
    """Округление до f32 (Rust op на f32, затем приведение к f64)."""
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _as_state_id(value: Union[BlockStateId, int]) -> BlockStateId:
    if isinstance(value, BlockStateId):
        return value
    return BlockStateId(int(value))


def _compound(tag_or_dict) -> Dict[str, Tag]:
    """Принимает либо dict из read_nbt, либо Tag-Compound."""
    if isinstance(tag_or_dict, Tag):
        if not tag_or_dict.is_compound or tag_or_dict.compound_val is None:
            raise ValueError("block collision: ожидался compound-тег")
        return tag_or_dict.compound_val
    return dict(tag_or_dict)


# ---------------------------------------------------------------------------
# VoxelShape — port horizon-core/src/geometry/shape.rs
# ---------------------------------------------------------------------------

@dataclass(frozen=True, eq=False)
class VoxelShape:
    """Неизменяемая дискретная занятость с точными границами double.

    ``coords[i]`` — границы по оси i, ``occupancy`` — занятость ячеек в
    порядке index = (x * sizes[1] + y) * sizes[2] + z (shape.rs:565).
    ``boxes`` вычисляются один раз жадным разложением (shape.rs:504).
    """

    coords: Tuple[Tuple[float, ...], Tuple[float, ...], Tuple[float, ...]]
    sizes: Tuple[int, int, int]
    occupancy: Tuple[bool, ...]
    cube: bool
    coordinate_cubes: Tuple[bool, bool, bool]
    boxes: Tuple[Aabb, ...]
    discrete_min: Tuple[int, int, int]
    discrete_max: Tuple[int, int, int]

    # --- конструкторы (shape.rs:113, 116, 241, 179, 194) ---

    @staticmethod
    def from_grid(
        coords: Sequence[Sequence[float]], occupied: Sequence[bool]
    ) -> "VoxelShape":
        return VoxelShape._build(coords, occupied, False, (False, False, False))

    @staticmethod
    def from_cube(
        sizes: Sequence[int], occupied: Sequence[bool]
    ) -> "VoxelShape":
        sizes_t = tuple(int(s) for s in sizes)
        if 0 in sizes_t:
            raise ValueError("invalid voxel shape: InvalidCoordinates")
        volume = _volume(sizes_t)
        if len(occupied) != volume:
            raise ValueError("invalid voxel shape: InvalidOccupancy")
        coords = tuple(
            tuple(i / size for i in range(size + 1)) for size in sizes_t
        )
        return VoxelShape._build(coords, occupied, True, (True, True, True))

    @staticmethod
    def from_mixed_grid(
        coords: Sequence[Sequence[float]],
        occupied: Sequence[bool],
        coordinate_cubes: Sequence[bool],
    ) -> "VoxelShape":
        # shape.rs:246 — оси-кубы обязаны быть i/size побитово.
        for i in range(3):
            if coordinate_cubes[i]:
                axis = coords[i]
                size = max(len(axis) - 1, 0)
                if size == 0 or any(
                    _f64_bits(v) != _f64_bits(j / size)
                    for j, v in enumerate(axis)
                ):
                    raise ValueError(
                        "invalid voxel shape: InvalidCoordinates"
                    )
        return VoxelShape._build(
            coords, occupied, False, tuple(bool(v) for v in coordinate_cubes)
        )

    @staticmethod
    def _build(
        coords: Sequence[Sequence[float]],
        occupied: Sequence[bool],
        cube: bool,
        coordinate_cubes: Tuple[bool, bool, bool],
    ) -> "VoxelShape":
        coords_t = tuple(tuple(float(v) for v in axis) for axis in coords)
        if len(coords_t) != 3:
            raise ValueError("invalid voxel shape: InvalidCoordinates")
        for axis in coords_t:
            if (
                len(axis) == 0
                or len(axis) > MAX_COORDINATES
                or any(v != v for v in axis)  # NaN
                or any(axis[k] >= axis[k + 1] for k in range(len(axis) - 1))
            ):
                raise ValueError("invalid voxel shape: InvalidCoordinates")
        sizes = tuple(len(axis) - 1 for axis in coords_t)
        count = _volume(sizes)
        if count != len(occupied):
            raise ValueError("invalid voxel shape: InvalidOccupancy")

        occ = tuple(bool(v) for v in occupied)
        discrete_min = [sizes[0], sizes[1], sizes[2]]
        discrete_max = [0, 0, 0]
        for i, full_cell in enumerate(occ):
            if full_cell:
                position = (
                    i // (sizes[1] * sizes[2]),
                    i // sizes[2] % sizes[1],
                    i % sizes[2],
                )
                for axis in range(3):
                    discrete_min[axis] = min(discrete_min[axis], position[axis])
                    discrete_max[axis] = max(
                        discrete_max[axis], position[axis] + 1
                    )

        shape = VoxelShape(
            coords=coords_t,
            sizes=sizes,
            occupancy=occ,
            cube=cube,
            coordinate_cubes=coordinate_cubes,
            boxes=(),
            discrete_min=tuple(discrete_min),
            discrete_max=tuple(discrete_max),
        )
        boxes = shape._decompose()
        return replace(
            shape,
            boxes=tuple(boxes),
            discrete_min=tuple(discrete_min),
            discrete_max=tuple(discrete_max),
        )

    @staticmethod
    def empty() -> "VoxelShape":
        return _empty_shape()

    @staticmethod
    def block() -> "VoxelShape":
        return _block_shape()

    # --- запросы (shape.rs:206-278, 504) ---

    def is_empty(self) -> bool:
        # shape.rs:206 — bounds.is_none() эквивалентно отсутствию боксов.
        return len(self.boxes) == 0

    def is_block(self) -> bool:
        return (
            self.cube
            and self.sizes == (1, 1, 1)
            and len(self.boxes) == 1
            and self.boxes[0].min == Vec3(0.0, 0.0, 0.0)
            and self.boxes[0].max == Vec3(1.0, 1.0, 1.0)
        )

    def is_cube(self) -> bool:
        return self.cube

    def cube_coordinate_axes(self) -> Tuple[bool, bool, bool]:
        return self.coordinate_cubes

    def boxes_list(self) -> List[Aabb]:
        return list(self.boxes)

    def coordinates(self, axis) -> Sequence[float]:
        return self.coords[axis.value if hasattr(axis, "value") else axis]

    def min(self, axis) -> float:
        i = axis.value if hasattr(axis, "value") else axis
        index = self.discrete_min[i]
        if index >= self.sizes[i]:
            return float("inf")
        return self.coords[i][index]

    def max(self, axis) -> float:
        i = axis.value if hasattr(axis, "value") else axis
        index = self.discrete_max[i]
        if index <= 0:
            return float("-inf")
        return self.coords[i][index]

    def discrete_bounds(self) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
        return (self.discrete_min, self.discrete_max)

    def fresh_identity(self) -> "VoxelShape":
        """shape.rs:231 — отдельная идентичность при той же сетке."""
        return replace(self)

    def with_discrete_bounds(
        self, minimum: Sequence[int], maximum: Sequence[int]
    ) -> "VoxelShape":
        """shape.rs:286 — импорт эталонных экстремумов из экспорта."""
        mn = tuple(int(v) for v in minimum)
        mx = tuple(int(v) for v in maximum)
        if len(mn) != 3 or len(mx) != 3:
            raise ValueError("invalid voxel shape: InvalidBounds")
        in_range = all(
            0 <= mn[i] <= self.sizes[i] and 0 <= mx[i] <= self.sizes[i]
            for i in range(3)
        )
        join_sentinel = (
            mn == (_I32_MAX, _I32_MAX, _I32_MAX)
            and mx == (_I32_MIN_PLUS_ONE,) * 3
        )
        if (not in_range and not join_sentinel) or (
            not self.is_empty()
            and (mn != self.discrete_min or mx != self.discrete_max)
        ):
            raise ValueError("invalid voxel shape: InvalidBounds")
        if mn == self.discrete_min and mx == self.discrete_max:
            return self
        return replace(self, discrete_min=mn, discrete_max=mx)

    # --- жадное разложение (shape.rs:504-551) ---

    def _decompose(self) -> List[Aabb]:
        remaining = list(self.occupancy)
        boxes: List[Aabb] = []
        nx, ny, nz = self.sizes

        def index(x: int, y: int, z: int) -> int:
            return (x * ny + y) * nz + z

        def is_full(x: int, y: int, z: int) -> bool:
            return remaining[index(x, y, z)]

        def strip_full(x: int, y: int, lo: int, hi: int) -> bool:
            return all(is_full(x, y, z) for z in range(lo, hi))

        def clear_strip(x: int, y: int, lo: int, hi: int) -> None:
            for z in range(lo, hi):
                remaining[index(x, y, z)] = False

        for y in range(ny):
            for x in range(nx):
                run: Optional[int] = None
                for z in range(nz + 1):
                    if z < nz and is_full(x, y, z):
                        if run is None:
                            run = z
                        continue
                    if run is None:
                        continue
                    z_start = run
                    run = None
                    clear_strip(x, y, z_start, z)
                    x_end = x + 1
                    while x_end < nx and strip_full(x_end, y, z_start, z):
                        clear_strip(x_end, y, z_start, z)
                        x_end += 1
                    y_end = y + 1
                    while y_end < ny and all(
                        strip_full(u, y_end, z_start, z)
                        for u in range(x, x_end)
                    ):
                        for u in range(x, x_end):
                            clear_strip(u, y_end, z_start, z)
                        y_end += 1
                    boxes.append(
                        Aabb.new(
                            Vec3(
                                self.coords[0][x],
                                self.coords[1][y],
                                self.coords[2][z_start],
                            ),
                            Vec3(
                                self.coords[0][x_end],
                                self.coords[1][y_end],
                                self.coords[2][z],
                            ),
                        )
                    )
        return boxes


def _volume(sizes: Sequence[int]) -> int:
    count = 1
    for size in sizes:
        count *= int(size)
    if count > MAX_VOLUME:
        raise ValueError("invalid voxel shape: TooLarge")
    return count


_EMPTY_SHAPE: Optional[VoxelShape] = None
_BLOCK_SHAPE: Optional[VoxelShape] = None


def _empty_shape() -> VoxelShape:
    global _EMPTY_SHAPE
    if _EMPTY_SHAPE is None:
        _EMPTY_SHAPE = VoxelShape.from_grid(
            ([0.0], [0.0], [0.0]), []
        )
    return _EMPTY_SHAPE


def _block_shape() -> VoxelShape:
    global _BLOCK_SHAPE
    if _BLOCK_SHAPE is None:
        _BLOCK_SHAPE = VoxelShape.from_cube((1, 1, 1), [True])
    return _BLOCK_SHAPE


# ---------------------------------------------------------------------------
# Контекстные правила, перенесённые из block_collision.rs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ShulkerCollisionState:
    """block_collision.rs:17 — состояние открытия шалкера."""

    previous_progress: float
    progress: float

    def bounding_box(self, direction: Direction) -> Aabb:
        # block_collision.rs:22 — getProgress(1) на f32, включая округление.
        progress = _f32(
            0.5 * _f32(self.previous_progress + _f32(
                self.progress - self.previous_progress
            ))
        )
        if progress != progress:  # NaN
            maximum = progress
            minimum = progress
        else:
            maximum = float(max(-1.0, progress))
            minimum = float(min(-1.0, progress))
        x, y, z = direction.normal()
        return (
            Aabb.new(Vec3(-0.5, 0.0, -0.5), Vec3(0.5, 1.0, 0.5))
            .expand_towards(
                Vec3(float(x) * maximum, float(y) * maximum, float(z) * maximum)
            )
            .contract(
                Vec3(
                    float(-x) * (1.0 + minimum),
                    float(-y) * (1.0 + minimum),
                    float(-z) * (1.0 + minimum),
                )
            )
            .move_by(Vec3(0.5, 0.0, 0.5))
        )


# ---------------------------------------------------------------------------
# Чтение cached-collision.nbt
# ---------------------------------------------------------------------------

class _CollisionNbtReader(_nbt._Reader):
    """Читатель NBT с корректной длиной LongArray.

    В ``quadrix/world/nbt.py`` длина LongArray читается как i64, тогда как
    формат NBT (и horizon-world/src/nbt.rs) задаёт i32. Чужие файлы не
    правим — переопределяем только этот тег, остальное наследуем.
    """

    def payload(self, tag_id: int, depth: int) -> Tag:
        if tag_id == TagType.LongArray:
            length = self._i32_be()
            if length < 0:
                raise self._error("negative LongArray length")
            values = [self._i64_be() for _ in range(length)]
            return Tag(TagType.LongArray, longarray_val=values)
        return super().payload(tag_id, depth)


def read_collision_nbt(data: bytes) -> Dict[str, Tag]:
    """read_nbt для кэша столкновений (с исправленной длиной LongArray)."""
    reader = _CollisionNbtReader(data, _nbt.Limits())
    compound, _consumed = reader.read_named_root()
    return compound


# ---------------------------------------------------------------------------
# CachedCollisionRegistry — port collision.rs:58-264
# ---------------------------------------------------------------------------

GridKey = Tuple[
    Tuple[Tuple[int, ...], Tuple[int, ...], Tuple[int, ...]],
    Tuple[int, ...],
    bool,
    int,
    Tuple[int, int, int],
    Tuple[int, int, int],
]


@dataclass
class CachedCollisionRegistry:
    """Кэш форм столкновений по id состояния (collision.rs:58)."""

    registry: BlockRegistry
    shapes: Tuple[VoxelShape, ...]
    state_shapes: Tuple[int, ...]
    grid_count: int
    canonical_identities: bool

    # --- загрузка (collision.rs:69, 72) ---

    @classmethod
    def from_nbt(
        cls, tag, registry: BlockRegistry, verify_states: bool = True
    ) -> "CachedCollisionRegistry":
        """Проверяет таблицу (BlockTable::check) и читает формы."""
        return cls.from_table(tag, registry, verify_states=verify_states)

    @classmethod
    def from_table(
        cls, tag, registry: BlockRegistry, verify_states: bool = True
    ) -> "CachedCollisionRegistry":
        data = _compound(tag)

        dv_tag = data.get("DataVersion")
        if dv_tag is None or not dv_tag.is_int:
            raise ValueError("collision DataVersion mismatch")
        if dv_tag.int_val != COLLISION_DATA_VERSION:
            raise ValueError("collision DataVersion mismatch")

        # registry.rs:226 — список идентичностей состояний.
        states_tag = data.get("states")
        if states_tag is None or not states_tag.is_list:
            raise ValueError("missing collision state identities")
        if len(states_tag.list_val) != registry.len():
            raise ValueError("collision registry size mismatch")
        if verify_states:
            for i, state_tag in enumerate(states_tag.list_val):
                if registry.states[i] != BlockState.from_nbt(state_tag):
                    raise ValueError("collision state identities differ")

        shapes_tag = data.get("shapes")
        if shapes_tag is None or not shapes_tag.is_list:
            raise ValueError("missing collision shapes")
        entries = shapes_tag.list_val
        if len(entries) > registry.len():
            raise ValueError("too many cached collision shapes")

        shapes: List[VoxelShape] = []
        canonical_identities = True
        seen_canonical = [False, False, False]
        grids: Dict[GridKey, VoxelShape] = {}

        for entry_tag in entries:
            entry = _compound(entry_tag)

            canonical = 0
            canonical_tag = entry.get("canonical")
            if canonical_tag is None:
                canonical_identities = False
            elif canonical_tag.is_byte and 0 <= canonical_tag.byte_val <= 2:
                canonical = int(canonical_tag.byte_val)
            else:
                raise ValueError("invalid canonical collision identity")
            if canonical != 0:
                if seen_canonical[canonical]:
                    raise ValueError("duplicate canonical collision identity")
                seen_canonical[canonical] = True

            coords: List[List[float]] = []
            for axis in ("x", "y", "z"):
                axis_tag = entry.get(axis)
                if axis_tag is None or not axis_tag.is_longarray:
                    raise ValueError("missing collision coordinates")
                coords.append(
                    [_f64_from_bits(b) for b in axis_tag.longarray_val]
                )

            occupied_tag = entry.get("occupied")
            if occupied_tag is None or not occupied_tag.is_bytearray:
                raise ValueError("missing collision occupancy")
            occ_bytes = occupied_tag.bytes_val
            if any(b not in (0, 1) for b in occ_bytes):
                raise ValueError("invalid collision occupancy")
            occupied = [b != 0 for b in occ_bytes]

            cube_axes_tag = entry.get("cube_axes")
            if cube_axes_tag is None or not cube_axes_tag.is_byte:
                raise ValueError("missing cube-coordinate metadata")
            cube_axes = int(cube_axes_tag.byte_val)
            if cube_axes < 0 or cube_axes > 7:
                raise ValueError("invalid cube-coordinate metadata")
            coordinate_cubes = (
                cube_axes & 1 != 0,
                cube_axes & 2 != 0,
                cube_axes & 4 != 0,
            )

            def discrete_bounds(name: str) -> Tuple[int, int, int]:
                bounds_tag = entry.get(name)
                if bounds_tag is None or not bounds_tag.is_intarray:
                    raise ValueError("missing collision discrete extrema")
                values = list(bounds_tag.intarray_val)
                if len(values) != 3:
                    raise ValueError("invalid collision discrete extrema length")
                return (values[0], values[1], values[2])

            minimum = discrete_bounds("discrete_min")
            maximum = discrete_bounds("discrete_max")

            cube_tag = entry.get("cube")
            if cube_tag is None or not cube_tag.is_byte or cube_tag.byte_val not in (0, 1):
                raise ValueError("invalid collision cube flag")
            cube = cube_tag.byte_val == 1

            key: GridKey = (
                (
                    tuple(_f64_bits(v) for v in coords[0]),
                    tuple(_f64_bits(v) for v in coords[1]),
                    tuple(_f64_bits(v) for v in coords[2]),
                ),
                tuple(int(b) for b in occ_bytes),
                cube,
                cube_axes,
                minimum,
                maximum,
            )

            existing = grids.get(key)
            if existing is not None:
                shape = existing.fresh_identity()
            else:
                if cube:
                    if cube_axes != 7:
                        raise ValueError(
                            "cube shape has array-coordinate metadata"
                        )
                    sizes = [
                        max(len(coords[i]) - 1, 0) for i in range(3)
                    ]
                    shape = VoxelShape.from_cube(sizes, occupied)
                    for axis in range(3):
                        if tuple(_f64_bits(v) for v in shape.coords[axis]) != tuple(
                            _f64_bits(v) for v in coords[axis]
                        ):
                            raise ValueError("cube collision coordinates differ")
                else:
                    shape = VoxelShape.from_mixed_grid(
                        coords, occupied, coordinate_cubes
                    )
                shape = shape.with_discrete_bounds(minimum, maximum)

            if canonical != 0:
                reference = (
                    _empty_shape() if canonical == 1 else _block_shape()
                )
                expected_count = 1 if canonical == 2 else 0
                if (
                    cube != reference.is_cube()
                    or coordinate_cubes != reference.cube_coordinate_axes()
                    or occupied != [True] * expected_count
                    or minimum != (0, 0, 0)
                    or maximum != (expected_count,) * 3
                    or any(
                        tuple(_f64_bits(v) for v in reference.coords[axis])
                        != key[0][axis]
                        for axis in range(3)
                    )
                ):
                    raise ValueError(
                        "canonical collision identity has different geometry"
                    )
                shape = reference

            grids.setdefault(key, shape)
            shapes.append(shape)

        mapping_tag = data.get("cached_shapes")
        if mapping_tag is None or not mapping_tag.is_intarray:
            raise ValueError("missing cached shape mapping")
        state_shapes = tuple(int(v) for v in mapping_tag.intarray_val)
        if len(state_shapes) != registry.len() or any(
            v < -1 or v >= len(shapes) for v in state_shapes
        ):
            raise ValueError("invalid cached shape mapping")

        return cls(
            registry=registry,
            shapes=tuple(shapes),
            state_shapes=state_shapes,
            grid_count=len(grids),
            canonical_identities=canonical_identities,
        )

    # --- запросы (collision.rs:229-253) ---

    def has_canonical_identities(self) -> bool:
        return self.canonical_identities

    def shape_count(self) -> int:
        return len(self.shapes)

    def unique_grid_count(self) -> int:
        return self.grid_count

    def cached_state_count(self) -> int:
        return sum(1 for v in self.state_shapes if v >= 0)

    def cached_shape(
        self, state: Union[BlockStateId, int]
    ) -> Optional[VoxelShape]:
        """None — форма не кэширована (нужна block behavior), не «воздух»."""
        index = _as_state_id(state).id
        if index < 0 or index >= len(self.state_shapes):
            raise ValueError("collision state outside registry")
        shape_id = self.state_shapes[index]
        if shape_id < 0:
            return None
        return self.shapes[shape_id]


# ---------------------------------------------------------------------------
# Загрузка из .local
# ---------------------------------------------------------------------------

def load_cached_collision(
    registry: BlockRegistry,
    path: Union[str, Path, None] = None,
    verify_states: bool = True,
) -> CachedCollisionRegistry:
    """Читает cached-collision.nbt и сверяет идентичности состояний."""
    file_path = Path(path) if path is not None else COLLISION_FILE
    raw = file_path.read_bytes()
    tag = read_collision_nbt(raw)
    return CachedCollisionRegistry.from_table(
        tag, registry, verify_states=verify_states
    )


_CACHE: "WeakKeyDictionary[BlockRegistry, Dict[Path, CachedCollisionRegistry]]" = (
    WeakKeyDictionary()
)


def default_collision_registry(
    registry: BlockRegistry,
    root: Union[str, Path, None] = None,
) -> CachedCollisionRegistry:
    """Кэширует разбор файла на время жизни реестра блоков."""
    base = Path(root) if root is not None else COLLISION_ROOT
    path = (base / "cached-collision.nbt") if base.name != "cached-collision.nbt" else base
    per_registry = _CACHE.get(registry)
    if per_registry is None:
        per_registry = {}
        _CACHE[registry] = per_registry
    cached = per_registry.get(path)
    if cached is None:
        cached = load_cached_collision(registry, path)
        per_registry[path] = cached
    return cached


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------

# block_collision.rs:109 — powder snow / скаффолдинг / жидкости контекстны и
# сюда не входят. Не кэшированные состояния без правила получают заглушку:
# полный куб для тел, у которых в ваниле всегда есть коллизия (block_collision.rs:188).
_UNCACHED_FULL_CUBE_NAMES = frozenset({"minecraft:moving_piston"})


def _uncached_fallback(state: Optional[BlockState]) -> VoxelShape:
    if state is None:
        return _empty_shape()
    name = state.name
    if (
        name in _UNCACHED_FULL_CUBE_NAMES
        or name == "minecraft:shulker_box"
        or name.endswith("_shulker_box")
    ):
        return _block_shape()
    # Остальные (scaffolding, powder_snow, dripstone, bamboo, ...) — динамика.
    return _empty_shape()


def full_cube() -> VoxelShape:
    """Полный куб [0,0,0]..[1,1,1] (VoxelShape::block, shape.rs:194)."""
    return _block_shape()


def collision_shape(
    registry: BlockRegistry,
    block_state_id: Union[BlockStateId, int],
    cached: Optional[CachedCollisionRegistry] = None,
) -> VoxelShape:
    """Форма столкновения состояния без учёта контекста (block_collision.rs:175)."""
    cached = cached or default_collision_registry(registry)
    shape = cached.cached_shape(block_state_id)
    if shape is not None:
        return shape
    return _uncached_fallback(registry.state(_as_state_id(block_state_id)))


def block_collision_boxes(
    registry: BlockRegistry,
    block_state_id: Union[BlockStateId, int],
    cached: Optional[CachedCollisionRegistry] = None,
) -> List[Aabb]:
    """Список Aabb формы столкновения (VoxelShape::boxes, shape.rs:212)."""
    return collision_shape(registry, block_state_id, cached).boxes_list()
