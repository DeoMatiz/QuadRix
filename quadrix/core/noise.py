"""Порт horizon-core/src/noise/{mod,perlin,normal,stack}.rs — PART 1.

PART 1 покрывает базовые сэмплеры шума:
  * ``mod.rs``    — ``GradientTable``, таблицы градиентов, ``wrap``, ``smoothstep``,
                    ``smoothstep_derivative``, ``lerp/lerp2/lerp3``;
  * ``perlin.rs`` — ``PerlinNoise`` (Java vanilla ImprovedPerlinNoise) и
                    ``SmearedPerlinNoise``;
  * ``normal.rs`` — ``NormalNoise``, ``NormalNoiseBuilder``, ``OctaveInfo``,
                    ``NoiseBuildError``, ``create_legacy_fbm``;
  * ``stack.rs``  — ``Noise`` (Protocol), ``NoiseLayer``, ``NoiseStack``,
                    ``NoiseStackBuilder``. Скалярная часть нужна ``NormalNoise``
                    (``create`` возвращает ``NoiseStack``), поэтому портирована
                    здесь; объёмные пути (``add_to_volume``/``add_to_needed``)
                    требуют ``DensityVolume`` из ``volume.rs`` — PART 2.

PART 2 (отдельно): ``simplex.rs``, ``volume.rs`` и объёмные циклы стека.

Правила точности (как в Rust):

* координаты — double; интерполяция Perlin и производные — f32;
* порядок операций не менять: алгебраическая перестановка меняет worldgen;
* каждое f32-действие округляется до f32 (Python float — double).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Sequence

from .geometry import floor_i32
from .jmath import f32_bits, f32_from_bits, f64_bits, f64_from_bits

__all__ = [
    "GRADIENTS",
    "PERLIN_GRADIENTS",
    "GradientTable",
    "NanRange",
    "Noise",
    "NoiseBuildError",
    "NoiseLayer",
    "NoiseStack",
    "NoiseStackBuilder",
    "NormalNoise",
    "NormalNoiseBuilder",
    "Normalization",
    "OctaveInfo",
    "PerlinNoise",
    "SmearedPerlinNoise",
    "compute_fudge_y",
    "create_legacy_fbm",
    "dot",
    "lerp",
    "lerp2",
    "lerp3",
    "power_of_two",
    "smoothstep",
    "smoothstep_derivative",
    "wrap",
]

I32_MIN = -2_147_483_648
I32_MAX = 2_147_483_647
I32_MASK = 0xFFFF_FFFF


def _f32(value: float) -> float:
    """Округлить double до ближайшего f32 (как `value as f32`)."""
    return f32_from_bits(f32_bits(value))


def _i32(value: int) -> int:
    """Привести к i32 с переполнением (wrapping cast)."""
    v = value & I32_MASK
    return v - 0x1_0000_0000 if v >= 0x8000_0000 else v


def _i32_add(a: int, b: int) -> int:
    """`a.wrapping_add(b)` для i32."""
    return _i32(a + b)


def _i32_neg(value: int) -> int:
    """`value.wrapping_neg()` для i32."""
    return _i32(-value)


# ── mod.rs: константы и общие функции ────────────────────────────────────────

# Таблица 16 направлений Perlin: четыре направления повторены. Simplex берёт
# первые двенадцать и выбирает их остатком, а не маской.
GRADIENTS: tuple[tuple[int, int, int], ...] = (
    (1, 1, 0),
    (-1, 1, 0),
    (1, -1, 0),
    (-1, -1, 0),
    (1, 0, 1),
    (-1, 0, 1),
    (1, 0, -1),
    (-1, 0, -1),
    (0, 1, 1),
    (0, -1, 1),
    (0, 1, -1),
    (0, -1, -1),
    (1, 1, 0),
    (0, -1, 1),
    (-1, 1, 0),
    (0, -1, -1),
)

# GRADIENTS как f32: каждый компонент -1, 0 или 1, поэтому представим точно.
PERLIN_GRADIENTS: tuple[tuple[float, float, float], ...] = tuple(
    (float(g[0]), float(g[1]), float(g[2])) for g in GRADIENTS
)

# Граница быстрого пути wrap: double непосредственно ниже 2^24.
_WRAP_HALF = f64_from_bits(f64_bits(16_777_216.0) - 1)
_WRAP_PERIOD = 33_554_432.0


def dot(gradient: Sequence[float], point: Sequence[float]) -> float:
    """Скалярное произведение в f32, порядок слагаемых как в Rust."""
    first = _f32(gradient[0] * point[0])
    second = _f32(gradient[1] * point[1])
    third = _f32(gradient[2] * point[2])
    return _f32(_f32(first + second) + third)


def wrap(value: float) -> float:
    """Периодическое приведение координат vanilla при выключенном Far Lands."""
    if value >= -_WRAP_HALF and value < _WRAP_HALF:
        return value
    return value - math.floor(value / _WRAP_PERIOD + 0.5) * _WRAP_PERIOD


def smoothstep(value: float) -> float:
    """`value^3 * (value * (value * 6 - 15) + 10)` в f32."""
    v = value
    cube = _f32(_f32(v * v) * v)
    scaled = _f32(_f32(v * 6.0) - 15.0)
    inner = _f32(_f32(v * scaled) + 10.0)
    return _f32(cube * inner)


def smoothstep_derivative(value: float) -> float:
    """`30 * v^2 * (v - 1)^2` в f32."""
    v = value
    first = _f32(30.0 * v)
    second = _f32(first * v)
    third = _f32(second * _f32(v - 1.0))
    return _f32(third * _f32(v - 1.0))


def lerp(delta: float, start: float, end: float) -> float:
    """`start + delta * (end - start)` в f32."""
    return _f32(start + _f32(delta * _f32(end - start)))


def lerp2(a: float, b: float, values: Sequence[float]) -> float:
    """Билинейная интерполяция четырёх значений."""
    return lerp(
        b,
        lerp(a, values[0], values[1]),
        lerp(a, values[2], values[3]),
    )


def lerp3(fade: Sequence[float], values: Sequence[float]) -> float:
    """Трилинейная интерполяция восьми значений."""
    return lerp(
        fade[2],
        lerp2(fade[0], fade[1], values[:4]),
        lerp2(fade[0], fade[1], values[4:]),
    )


class NanRange(Exception):
    """Границы шумового интервала не могут содержать NaN."""

    def __init__(self) -> None:
        super().__init__("noise interval bounds cannot include NaN")


class GradientTable:
    """Неизменяемые смещения и таблица перестановок общих градиентных сэмплеров."""

    __slots__ = ("_offsets", "_permutations")

    def __init__(self, offsets: Sequence[float], permutations: Sequence[int]) -> None:
        self._offsets = (float(offsets[0]), float(offsets[1]), float(offsets[2]))
        self._permutations = [int(p) & 0xFF for p in permutations]

    @classmethod
    def new(cls, random, offset_scale: float) -> "GradientTable":
        # Нулевой масштаб всё равно расходует все три розыгрыша.
        offsets = [random.next_double() * offset_scale for _ in range(3)]
        permutations = [i & 0xFF for i in range(256)]
        for i in range(256):
            other = i + random.next_int_bound(256 - i)
            permutations[i], permutations[other] = permutations[other], permutations[i]
        return cls(offsets, permutations)

    def offsets(self) -> tuple[float, float, float]:
        return self._offsets

    def permutations(self) -> List[int]:
        return list(self._permutations)

    def permute(self, index: int) -> int:
        return self._permutations[index & 255]


# ── perlin.rs ────────────────────────────────────────────────────────────────


class PerlinNoise:
    """Java vanilla ``ImprovedPerlinNoise`` (16 направлений, сглаживание 6t^5-15t^4+10t^3)."""

    __slots__ = ("_table",)

    def __init__(self, random) -> None:
        self._table = GradientTable.new(random, 256.0)

    def table(self) -> GradientTable:
        return self._table

    def range(self) -> List[float]:
        return [-2.0, 2.0]

    def get2(self, x: float, z: float) -> float:
        return self.get3(wrap(x), 0.0, wrap(z))

    def get3(self, x: float, y: float, z: float) -> float:
        cell, relative = self._coordinates([x, y, z])
        point = [_f32(v) for v in relative]
        return self._sample(cell, point, point[1])

    def _coordinates(self, point: Sequence[float]):
        offsets = self._table.offsets()
        shifted = [wrap(point[i]) + offsets[i] for i in range(3)]
        cell = [floor_i32(v) for v in shifted]
        relative = [shifted[i] - float(cell[i]) for i in range(3)]
        return cell, relative

    def _gradients(self, cell: Sequence[int]) -> List[tuple[float, float, float]]:
        return self._gradients_at(
            self._table.permute(cell[0]),
            self._table.permute(_i32_add(cell[0], 1)),
            cell[1],
            cell[2],
        )

    def _gradients_at(
        self, p: int, q: int, cell_y: int, cell_z: int
    ) -> List[tuple[float, float, float]]:
        indices = self._gradient_indices_at(p, q, cell_y, cell_z)
        return [PERLIN_GRADIENTS[i] for i in indices]

    def _gradient_indices_at(
        self, p: int, q: int, cell_y: int, cell_z: int
    ) -> List[int]:
        lower = self._table.permute(_i32_add(p, cell_y))
        upper = self._table.permute(_i32_add(_i32_add(p, cell_y), 1))
        lower_x = self._table.permute(_i32_add(q, cell_y))
        upper_x = self._table.permute(_i32_add(_i32_add(q, cell_y), 1))
        rows = (lower, lower_x, upper, upper_x, lower, lower_x, upper, upper_x)
        return [
            self._table.permute(_i32_add(_i32_add(rows[i], cell_z), i // 4)) & 15
            for i in range(8)
        ]

    @staticmethod
    def _corner_values(
        gradients: Sequence[Sequence[float]], point: Sequence[float]
    ) -> List[float]:
        values = []
        for i in range(8):
            corner = (
                _f32(point[0] - float(i & 1)),
                _f32(point[1] - float((i >> 1) & 1)),
                _f32(point[2] - float((i >> 2) & 1)),
            )
            values.append(dot(gradients[i], corner))
        return values

    def _sample(
        self, cell: Sequence[int], point: Sequence[float], interpolation_y: float
    ) -> float:
        values = self._corner_values(self._gradients(cell), point)
        fade = [
            smoothstep(point[0]),
            smoothstep(interpolation_y),
            smoothstep(point[2]),
        ]
        return lerp3(fade, values)

    def noise_with_derivative(
        self, x: float, y: float, z: float, derivative: List[float]
    ) -> float:
        """Возвращает значение и добавляет градиент в ``derivative`` (f32)."""
        cell, relative = self._coordinates([x, y, z])
        point = [_f32(v) for v in relative]
        gradients = self._gradients(cell)
        values = self._corner_values(gradients, point)
        fade = [smoothstep(p) for p in point]
        gradient = [
            lerp3(fade, [g[axis] for g in gradients]) for axis in range(3)
        ]
        # Каждая разность округляется до f32, как отдельная f32-операция Rust.
        changes = [
            lerp2(
                fade[1],
                fade[2],
                [
                    _f32(values[1] - values[0]),
                    _f32(values[3] - values[2]),
                    _f32(values[5] - values[4]),
                    _f32(values[7] - values[6]),
                ],
            ),
            lerp2(
                fade[2],
                fade[0],
                [
                    _f32(values[2] - values[0]),
                    _f32(values[6] - values[4]),
                    _f32(values[3] - values[1]),
                    _f32(values[7] - values[5]),
                ],
            ),
            lerp2(
                fade[0],
                fade[1],
                [
                    _f32(values[4] - values[0]),
                    _f32(values[5] - values[1]),
                    _f32(values[6] - values[2]),
                    _f32(values[7] - values[3]),
                ],
            ),
        ]
        for axis in range(3):
            term = _f32(
                gradient[axis]
                + _f32(smoothstep_derivative(point[axis]) * changes[axis])
            )
            derivative[axis] = _f32(derivative[axis] + term)
        return lerp3(fade, values)


def compute_fudge_y(input_y: float, relative_y: float, scale: float) -> float:
    """Смещение по Y «размазанного» Perlin (как в vanilla)."""
    limited_y = input_y if (input_y >= 0.0 and input_y < relative_y) else relative_y
    # Rust: f64::from(1e-7_f32) — f32-литерал, расширенный до f64.
    return float(floor_i32(limited_y / scale + _f32(1e-7))) * scale


class SmearedPerlinNoise:
    """Perlin с «размазыванием» по Y; наследует несглаженный derivative."""

    __slots__ = ("_base", "_fudge_y_scale")

    def __init__(self, random, fudge_y_scale: float) -> None:
        self._base = PerlinNoise(random)
        self._fudge_y_scale = fudge_y_scale

    def table(self) -> GradientTable:
        return self._base.table()

    def get2(self, x: float, z: float) -> float:
        return self.get3(wrap(x), 0.0, wrap(z))

    def get3(self, x: float, y: float, z: float) -> float:
        cell, relative = self._base._coordinates([x, y, z])
        fudge = compute_fudge_y(y, relative[1], self._fudge_y_scale)
        return self._base._sample(
            cell,
            [
                _f32(relative[0]),
                _f32(relative[1] - fudge),
                _f32(relative[2]),
            ],
            _f32(relative[1]),
        )

    def noise_with_derivative(
        self, x: float, y: float, z: float, derivative: List[float]
    ) -> float:
        # Унаследованный метод сэмплирует несглаженное поле, как в vanilla.
        return self._base.noise_with_derivative(x, y, z, derivative)

    def range(self) -> List[float]:
        bound = _f32(abs(self._fudge_y_scale) + 2.0)
        if math.isnan(bound):
            raise NanRange()
        return [-bound, bound]


# ── stack.rs: скалярная часть ────────────────────────────────────────────────


class Noise(Protocol):
    """Неизменяемый сэмплер шума."""

    def range(self) -> List[float]:
        ...

    def get2(self, x: float, z: float) -> float:
        ...

    def get3(self, x: float, y: float, z: float) -> float:
        ...


@dataclass
class NoiseLayer:
    """Один слой стека: сэмплер, частота и амплитуда (f32)."""

    noise: Noise
    frequency: float
    amplitude: float


class NoiseStack:
    """Сумма слоёв шума; f32-накопление в порядке добавления."""

    __slots__ = ("_layers", "_range")

    def __init__(self, layers: Sequence[NoiseLayer], range_: Sequence[float]) -> None:
        self._layers = list(layers)
        self._range = [float(range_[0]), float(range_[1])]

    @staticmethod
    def builder() -> "NoiseStackBuilder":
        return NoiseStackBuilder()

    def layers(self) -> List[NoiseLayer]:
        return list(self._layers)

    def get_layer(self, index: int):  # -> Optional[Noise]
        if 0 <= index < len(self._layers):
            return self._layers[index].noise
        return None

    def range(self) -> List[float]:
        return list(self._range)

    def get2(self, x: float, z: float) -> float:
        value = 0.0
        for layer in self._layers:
            sample = layer.noise.get2(x * layer.frequency, z * layer.frequency)
            value = _f32(value + _f32(layer.amplitude * sample))
        return value

    def get3(self, x: float, y: float, z: float) -> float:
        value = 0.0
        for layer in self._layers:
            sample = layer.noise.get3(
                x * layer.frequency,
                y * layer.frequency,
                z * layer.frequency,
            )
            value = _f32(value + _f32(layer.amplitude * sample))
        return value


@dataclass
class NoiseStackBuilder:
    """Сборщик стека шума (плоское добавление слоёв)."""

    layers: List[NoiseLayer] = field(default_factory=list)

    def add(self, noise: Noise, frequency: float, amplitude: float) -> "NoiseStackBuilder":
        self.layers.append(
            NoiseLayer(noise=noise, frequency=float(frequency), amplitude=_f32(amplitude))
        )
        return self

    def add_stack(
        self, stack: NoiseStack, frequency: float, amplitude: float
    ) -> "NoiseStackBuilder":
        """Плоское добавление: частоты и амплитуды слоёв пересчитываются."""
        amp = _f32(amplitude)
        for layer in stack.layers():
            self.layers.append(
                NoiseLayer(
                    noise=layer.noise,
                    frequency=layer.frequency * frequency,
                    amplitude=_f32(layer.amplitude * amp),
                )
            )
        return self

    def build(self) -> NoiseStack:
        range_ = [0.0, 0.0]
        for layer in self.layers:
            bounds = layer.noise.range()
            if math.isnan(layer.amplitude):
                raise NanRange()
            if math.isnan(bounds[0]) or math.isnan(bounds[1]):
                scaled = [math.nan, math.nan]
            else:
                # Interval.mulBound: ноль, умноженный на бесконечность, даёт +0.
                def product(v: float, a: float = layer.amplitude) -> float:
                    if v == 0.0 or a == 0.0:
                        return 0.0
                    return _f32(v * a)

                a = product(bounds[0])
                b = product(bounds[1])
                if a < b:
                    scaled = [a, b]
                elif a > b:
                    scaled = [b, a]
                elif a == 0.0:
                    scaled = [
                        f32_from_bits(f32_bits(a) | f32_bits(b)),
                        f32_from_bits(f32_bits(a) & f32_bits(b)),
                    ]
                else:
                    scaled = [a, b]
            range_ = [
                _f32(range_[0] + scaled[0]),
                _f32(range_[1] + scaled[1]),
            ]
            if math.isnan(range_[0]) or math.isnan(range_[1]):
                range_ = [math.nan, math.nan]
            # Interval.of канонизирует [0, 1], включая подставленный -0.
            if range_[0] == 0.0 and range_[1] == 1.0:
                range_[0] = 0.0
        return NoiseStack(self.layers, range_)


# ── normal.rs ────────────────────────────────────────────────────────────────

# Верхняя граница аллокации builder API (data codec vanilla разрешает 32).
MAX_BUILDER_OCTAVES = 4096

_ERROR_MESSAGES = {
    "NegativeOctaveCount": "octave count cannot be negative",
    "TooManyOctaves": "octave count exceeds the 4096-layer allocation bound",
    "CountAfterModifiers": "cannot change octave count after setting amplitude modifiers",
    "ModifierIndex": "amplitude modifier index is outside the octave range",
    "EmptyAmplitudes": "at least one amplitude is required",
    "NanRange": "noise interval bounds cannot include NaN",
    "InvertedRange": "noise interval lower bound exceeds its upper bound",
    "MissingNoiseLevels": "legacy initializer could not create all nonzero octaves",
    "PositiveLegacyOctaves": "positive legacy octaves are disabled",
    "LegacyWorkLimit": "legacy initializer exceeds the 4096-octave work bound",
}


class NoiseBuildError(Exception):
    """Ошибка сборки ``NormalNoise`` (варианты как в Rust-энуме)."""

    NEGATIVE_OCTAVE_COUNT = "NegativeOctaveCount"
    TOO_MANY_OCTAVES = "TooManyOctaves"
    COUNT_AFTER_MODIFIERS = "CountAfterModifiers"
    MODIFIER_INDEX = "ModifierIndex"
    EMPTY_AMPLITUDES = "EmptyAmplitudes"
    NAN_RANGE = "NanRange"
    INVERTED_RANGE = "InvertedRange"
    MISSING_NOISE_LEVELS = "MissingNoiseLevels"
    POSITIVE_LEGACY_OCTAVES = "PositiveLegacyOctaves"
    LEGACY_WORK_LIMIT = "LegacyWorkLimit"

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(_ERROR_MESSAGES[kind])


class Normalization:
    """Режим нормализации амплитуд октав."""

    ENABLED = "Enabled"
    DISABLED = "Disabled"
    LEGACY = "Legacy"


@dataclass
class OctaveInfo:
    """Одна октава: индекс, частота и амплитуда."""

    octave_index: int
    frequency: float
    amplitude: float

    def seed(self) -> str:
        return f"octave_{self.octave_index}"


class NormalNoise:
    """Две копии Perlin на октаву, нормированные в примерно [-1, 1]."""

    __slots__ = ("_parameters", "_octaves", "_normalization_factor", "_range")

    def __init__(
        self,
        parameters: "NormalNoiseBuilder",
        octaves: Sequence[OctaveInfo],
        normalization_factor: float,
        range_: Sequence[float],
    ) -> None:
        self._parameters = parameters
        self._octaves = list(octaves)
        self._normalization_factor = normalization_factor
        self._range = [float(range_[0]), float(range_[1])]

    @staticmethod
    def builder() -> "NormalNoiseBuilder":
        return NormalNoiseBuilder()

    def octaves(self) -> List[OctaveInfo]:
        return list(self._octaves)

    def normalization_factor(self) -> float:
        return self._normalization_factor

    def range(self) -> List[float]:
        return list(self._range)

    def create(self, random) -> NoiseStack:
        # Даже пустой стек расходует оба позиционных форка.
        first = random.fork_positional()
        second = random.fork_positional()
        builder = NoiseStack.builder()
        for octave in self._octaves:
            name = octave.seed()
            a = PerlinNoise(first.from_hash_of(name))
            b = PerlinNoise(second.from_hash_of(name))
            amplitude = _f32(self._normalization_factor * octave.amplitude)
            builder.add(a, octave.frequency, amplitude)
            builder.add(
                b,
                octave.frequency * 1.018_126_888_217_522_7,
                amplitude,
            )
        return builder.build()

    def create_for_legacy_nether_biome(self, random) -> NoiseStack:
        if self._parameters.modifiers:
            modifiers = self._parameters.modifiers
        else:
            modifiers = [1.0] * self._parameters.octave_count
        first = create_legacy_fbm(random, self._parameters.base_octave, modifiers)
        second = create_legacy_fbm(random, self._parameters.base_octave, modifiers)
        amplitude = _f32(
            self._normalization_factor * self._parameters.base_amplitude
        )
        return (
            NoiseStack.builder()
            .add_stack(first, 1.0, amplitude)
            .add_stack(second, 1.018_126_888_217_522_7, amplitude)
            .build()
        )

    @staticmethod
    def create_parity(base_octave: int, amplitudes: Sequence[float]) -> "NormalNoise":
        if not amplitudes:
            raise NoiseBuildError(NoiseBuildError.EMPTY_AMPLITUDES)
        if len(amplitudes) > MAX_BUILDER_OCTAVES:
            raise NoiseBuildError(NoiseBuildError.TOO_MANY_OCTAVES)
        count = len(amplitudes)
        octaves = build_octaves(base_octave, 1.0, count, True, amplitudes)
        factor = normalization_factor_of(sum_abs(octaves), octaves)
        if factor == 0.0:
            base_amplitude = 1.0
        else:
            base_amplitude = parity_factor(1.0, count, amplitudes) / factor
        builder = NormalNoiseBuilder(
            base_amplitude=base_amplitude,
            base_octave=base_octave,
            octave_count=count,
            normalization=Normalization.ENABLED,
            modifiers=list(amplitudes),
        )
        return builder.build()


@dataclass
class NormalNoiseBuilder:
    """Builder как в vanilla: базовая октава, амплитуда, счётчик, модификаторы."""

    base_amplitude: float = 1.0
    base_octave: int = 0
    octave_count: int = 1
    normalization: str = Normalization.ENABLED
    modifiers: List[float] = field(default_factory=list)

    def set_base_amplitude(self, amplitude: float) -> "NormalNoiseBuilder":
        self.base_amplitude = amplitude
        return self

    def set_base_octave(self, octave: int) -> "NormalNoiseBuilder":
        self.base_octave = octave
        return self

    def set_normalization(self, normalization: str) -> "NormalNoiseBuilder":
        self.normalization = normalization
        return self

    def set_octave_count(self, count: int) -> "NormalNoiseBuilder":
        if self.modifiers:
            raise NoiseBuildError(NoiseBuildError.COUNT_AFTER_MODIFIERS)
        self.octave_count = count
        return self

    def set_amplitude_modifier(
        self, index: int, value: float
    ) -> "NormalNoiseBuilder":
        if index < 0 or index >= self.octave_count:
            raise NoiseBuildError(NoiseBuildError.MODIFIER_INDEX)
        if self.octave_count > MAX_BUILDER_OCTAVES:
            raise NoiseBuildError(NoiseBuildError.TOO_MANY_OCTAVES)
        if not self.modifiers:
            self.modifiers = [1.0] * self.octave_count
        self.modifiers[index] = value
        return self

    def build(self) -> NormalNoise:
        if self.octave_count < 0:
            raise NoiseBuildError(NoiseBuildError.NEGATIVE_OCTAVE_COUNT)
        if self.octave_count > MAX_BUILDER_OCTAVES:
            raise NoiseBuildError(NoiseBuildError.TOO_MANY_OCTAVES)
        octaves = build_octaves(
            self.base_octave,
            self.base_amplitude,
            self.octave_count,
            self.normalization != Normalization.DISABLED,
            self.modifiers,
        )
        total = sum_abs(octaves)
        factor = normalization_factor_of(total, octaves)
        if self.normalization == Normalization.LEGACY and factor != 0.0:
            legacy = parity_factor(
                self.base_amplitude, self.octave_count, self.modifiers
            )
            total *= legacy / factor
            factor = legacy
        bound = _f32(total * (1.0 / 3.0) * 6.0)
        if math.isnan(bound):
            raise NoiseBuildError(NoiseBuildError.NAN_RANGE)
        if bound < 0.0:
            raise NoiseBuildError(NoiseBuildError.INVERTED_RANGE)
        return NormalNoise(self, octaves, factor, [-bound, bound])


def create_legacy_fbm(
    random, base_octave: int, amplitudes: Sequence[float]
) -> NoiseStack:
    """Legacy-инициализатор: расходует поток в обратном порядке октав.

    Пропущенные и нулевые октавы расходуют ровно 262 целочисленных розыгрыша.
    Запросы за пределами границ аллокации/работы падают до розыгрышей.
    """
    if len(amplitudes) > MAX_BUILDER_OCTAVES:
        raise NoiseBuildError(NoiseBuildError.TOO_MANY_OCTAVES)
    zero_index = _i32_neg(base_octave)
    if _i32(_i32_add(zero_index, -1)) >= MAX_BUILDER_OCTAVES:
        raise NoiseBuildError(NoiseBuildError.LEGACY_WORK_LIMIT)
    count = len(amplitudes)
    levels: List[Optional[PerlinNoise]] = [None] * len(amplitudes)
    zero_noise = PerlinNoise(random)
    if 0 <= zero_index < count and amplitudes[zero_index] != 0.0:
        levels[zero_index] = zero_noise
    for index in range(zero_index - 1, -1, -1):
        if index < count and amplitudes[index] != 0.0:
            levels[index] = PerlinNoise(random)
        else:
            random.consume_count(262)
    if sum(1 for v in levels if v is not None) != sum(
        1 for v in amplitudes if v != 0.0
    ):
        raise NoiseBuildError(NoiseBuildError.MISSING_NOISE_LEVELS)
    if zero_index < count - 1:
        raise NoiseBuildError(NoiseBuildError.POSITIVE_LEGACY_OCTAVES)
    frequency = power_of_two(_i32_neg(zero_index))
    amplitude = _f64_div(power_of_two(count - 1), power_of_two(count) - 1.0)
    builder = NoiseStack.builder()
    for index, noise in enumerate(levels):
        if noise is not None:
            builder.add(
                noise,
                frequency,
                _f32(amplitude * amplitudes[index]),
            )
        frequency *= 2.0
        amplitude /= 2.0
    return builder.build()


def modifier(modifiers: Sequence[float], index: int) -> float:
    """Модификатор амплитуды октавы (1.0, если список пуст)."""
    if not modifiers:
        return 1.0
    return modifiers[index]


def build_octaves(
    base: int,
    amplitude: float,
    count: int,
    normalize: bool,
    modifiers: Sequence[float],
) -> List[OctaveInfo]:
    """Список октав: частота удваивается, амплитуда делится вдвое."""
    frequency = power_of_two(base)
    amp = amplitude
    if normalize:
        amp *= _f64_div(power_of_two(count - 1), power_of_two(count) - 1.0)
    result: List[OctaveInfo] = []
    for index in range(count):
        multiplier = modifier(modifiers, index)
        if multiplier != 0.0:
            result.append(
                OctaveInfo(
                    octave_index=_i32_add(base, index),
                    frequency=frequency,
                    amplitude=amp * multiplier,
                )
            )
        frequency *= 2.0
        amp *= 0.5
    return result


def _f64_div(numerator: float, denominator: float) -> float:
    """Деление f64 по IEEE-754: деление на ноль даёт inf/NaN, а не исключение."""
    if denominator == 0.0:
        if numerator != numerator or numerator == 0.0:
            return math.nan
        sign = -1.0 if (math.copysign(1.0, numerator) * math.copysign(1.0, denominator)) < 0.0 else 1.0
        return sign * math.inf
    return numerator / denominator


def power_of_two(exponent: int) -> float:
    """``2^exponent`` для f64 без libm, включая субнормали и насыщение."""
    if exponent <= -1075:
        return 0.0
    if -1074 <= exponent <= -1023:
        return f64_from_bits(1 << (exponent + 1074))
    if -1022 <= exponent <= 1023:
        return f64_from_bits((exponent + 1023) << 52)
    return math.inf


def sum_abs(octaves: Sequence[OctaveInfo]) -> float:
    """Последовательная сумма |амплитуд| с компенсацией (Java DoubleStream.sum)."""
    total = 0.0
    correction = 0.0
    simple = 0.0
    for octave in octaves:
        value = abs(octave.amplitude)
        adjusted = value - correction
        nxt = total + adjusted
        correction = (nxt - total) - adjusted
        total = nxt
        simple += value
    result = total - correction
    if math.isnan(result) and math.isinf(simple):
        return simple
    return result


def normalization_factor_of(sum_: float, octaves: Sequence[OctaveInfo]) -> float:
    """Нормировочный множитель по дисперсии амплитуд."""
    variance = 0.0
    for octave in octaves:
        deviation = 0.270_224_783_124_521_1 * abs(octave.amplitude)
        variance += deviation * deviation
    deviation = math.sqrt(variance)
    if deviation == 0.0:
        return 0.0
    return (sum_ * (1.0 / 3.0)) / (deviation * math.sqrt(2.0))


def parity_factor(
    base_amplitude: float, count: int, modifiers: Sequence[float]
) -> float:
    """Legacy-нормировка vanilla (биом Незера)."""
    first = I32_MAX
    last = I32_MIN
    for index in range(count):
        if modifier(modifiers, index) != 0.0:
            first = min(first, index)
            last = max(last, index)
    distance = _i32_add(_i32(last - first), 1)
    return base_amplitude * 0.5 * (1.0 / 3.0) / (0.1 * (1.0 + 1.0 / float(distance)))
