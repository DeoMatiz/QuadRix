"""Тесты quadrix.core.noise — PART 1 (Perlin, NormalNoise, GradientTable, стек).

Эталонные битовые значения взяты из Rust-тестов
``horizon-core/src/noise/{mod,perlin,normal,stack}.rs`` (снятые с vanilla-сервера).
"""

from __future__ import annotations

import math
import struct

import pytest

from quadrix.core.jmath import f32_bits
from quadrix.core.noise import (
    GRADIENTS,
    PERLIN_GRADIENTS,
    GradientTable,
    NanRange,
    NoiseBuildError,
    NoiseStack,
    Normalization,
    NormalNoise,
    NormalNoiseBuilder,
    PerlinNoise,
    SmearedPerlinNoise,
    create_legacy_fbm,
    lerp,
    smoothstep,
    smoothstep_derivative,
    wrap,
)
from quadrix.core.random import LegacyRandom


def _d_bits(value: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", value))[0]


# ── mod.rs: константы и общие функции ────────────────────────────────────────


def test_gradient_tables_preserved():
    # 16 направлений Perlin включают четыре повтора — ровно как в Rust.
    assert len(GRADIENTS) == 16
    assert GRADIENTS[0] == (1, 1, 0)
    assert GRADIENTS[12] == (1, 1, 0)
    assert GRADIENTS[13] == (0, -1, 1)
    assert PERLIN_GRADIENTS[0] == (1.0, 1.0, 0.0)
    # Симплекс берёт первые двенадцать направлений.
    assert PERLIN_GRADIENTS[:12][-1] == (0.0, -1.0, -1.0)


def test_smoothstep_and_derivative_endpoints():
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0
    # 6t^5-15t^4+10t^3: производная на концах нулевая.
    assert smoothstep_derivative(0.0) == 0.0
    assert smoothstep_derivative(1.0) == 0.0
    # Середина: 0.5 -> 0.5, производная 30*0.25*0.25 = 1.875.
    assert smoothstep(0.5) == 0.5
    assert smoothstep_derivative(0.5) == 1.875


def test_lerp_matches_rust_order():
    assert lerp(0.0, 3.0, 7.0) == 3.0
    assert lerp(1.0, 3.0, 7.0) == 7.0
    assert lerp(0.5, 0.0, 4.0) == 2.0


def test_wrap_boundary_and_period():
    # Быстрый путь: ниже 2^24 значение возвращается без изменений.
    assert wrap(123.5) == 123.5
    assert wrap(-0.0) == -0.0
    period = 33_554_432.0
    assert wrap(period) == 0.0
    assert wrap(-period) == 0.0
    assert wrap(period + 5.0) == 5.0


# ── perlin.rs ────────────────────────────────────────────────────────────────


def test_perlin_seed_zero_sample_and_derivatives():
    # Снято оригинальным адаптером с закреплённого server JAR.
    random = LegacyRandom(0)
    noise = PerlinNoise(random)
    assert random.next_long() == -6_819_959_017_335_327_829
    derivative = [0.0, 0.0, 0.0]
    value = noise.noise_with_derivative(0.0, 0.0, 0.0, derivative)
    assert f32_bits(value) == 3_183_733_582
    assert [f32_bits(d) for d in derivative] == [
        3_189_117_465,
        3_214_556_526,
        1_017_326_887,
    ]


def test_perlin_determinism_same_seed():
    first = PerlinNoise(LegacyRandom(42))
    second = PerlinNoise(LegacyRandom(42))
    for x, y, z in [(0.0, 0.0, 0.0), (1.25, -3.5, 7.75), (-100.5, 64.0, 0.125)]:
        assert first.get3(x, y, z) == second.get3(x, y, z)
        assert first.get2(x, z) == second.get2(x, z)


def test_perlin_different_seed_differs():
    first = PerlinNoise(LegacyRandom(1))
    second = PerlinNoise(LegacyRandom(2))
    assert first.get3(0.5, 0.5, 0.5) != second.get3(0.5, 0.5, 0.5)


def test_perlin_range_over_1000_points():
    noise = PerlinNoise(LegacyRandom(7))
    bounds = noise.range()
    assert bounds == [-2.0, 2.0]
    for i in range(-500, 500):
        value = noise.get3(i * 0.37, i * 0.11, i * -0.53)
        assert math.isfinite(value)
        assert bounds[0] <= value <= bounds[1]


def test_perlin_get2_equals_get3_zero_y():
    noise = PerlinNoise(LegacyRandom(9))
    assert noise.get2(3.5, -2.25) == noise.get3(3.5, 0.0, -2.25)


def test_smeared_perlin_nan_range_is_error():
    smeared = SmearedPerlinNoise(LegacyRandom(0), math.nan)
    with pytest.raises(NanRange):
        smeared.range()
    finite = SmearedPerlinNoise(LegacyRandom(0), 0.125)
    assert finite.range() == [-2.125, 2.125]


# ── GradientTable: seed → permutation ────────────────────────────────────────


def test_gradient_table_permutation_is_bijection_and_seed_dependent():
    first = GradientTable.new(LegacyRandom(123), 256.0)
    second = GradientTable.new(LegacyRandom(123), 256.0)
    other = GradientTable.new(LegacyRandom(124), 256.0)
    # Одинаковый seed → одинаковая таблица перестановок.
    assert first.permutations() == second.permutations()
    # Разные seed → разные таблицы.
    assert first.permutations() != other.permutations()
    # Каждая таблица — перестановка 0..255.
    assert sorted(first.permutations()) == list(range(256))
    assert sorted(other.permutations()) == list(range(256))
    # permute индекс маскируется по & 255.
    assert first.permute(0) == first.permutations()[0]
    assert first.permute(256) == first.permutations()[0]


# ── normal.rs: NormalNoise ───────────────────────────────────────────────────


def _reference_builder() -> NormalNoiseBuilder:
    builder = NormalNoise.builder()
    builder.set_base_octave(-3)
    builder.set_octave_count(3)
    builder.set_amplitude_modifier(1, 0.0)
    return builder


def test_normal_noise_reference_values():
    definition = _reference_builder().build()
    assert _d_bits(definition.normalization_factor()) == 4_607_442_513_526_237_848
    assert [o.octave_index for o in definition.octaves()] == [-3, -1]
    random = LegacyRandom(0)
    modern = definition.create(random)
    assert f32_bits(modern.get3(0.0, 0.0, 0.0)) == 1_042_650_710
    assert random.next_long() == -6_688_467_811_848_818_630


def test_normal_noise_legacy_nether_reference():
    definition = _reference_builder().build()
    random = LegacyRandom(0)
    legacy = definition.create_for_legacy_nether_biome(random)
    assert f32_bits(legacy.get3(0.0, 0.0, 0.0)) == 3_199_632_936
    assert random.next_long() == 4_966_550_093_728_345_520


def test_normal_noise_builder_errors():
    builder = NormalNoise.builder()
    builder.set_base_octave(-3)
    with pytest.raises(NoiseBuildError) as excinfo:
        builder.set_amplitude_modifier(-1, 0.0)
    assert excinfo.value.kind == NoiseBuildError.MODIFIER_INDEX

    builder.set_octave_count(3)
    builder.set_amplitude_modifier(1, 0.0)
    with pytest.raises(NoiseBuildError) as excinfo:
        builder.set_octave_count(4)
    assert excinfo.value.kind == NoiseBuildError.COUNT_AFTER_MODIFIERS


def test_normal_noise_range_is_symmetric_and_samples_within():
    definition = _reference_builder().build()
    bounds = definition.range()
    assert bounds[0] < 0.0 < bounds[1]
    assert math.isclose(bounds[0], -bounds[1])
    noise = definition.create(LegacyRandom(5))
    value = noise.get3(1.5, 2.5, 3.5)
    assert bounds[0] <= value <= bounds[1]


def test_normal_noise_octave_count_influences_result():
    one = NormalNoise.builder().set_octave_count(1).build()
    three = NormalNoise.builder().set_octave_count(3).build()
    assert len(one.octaves()) == 1
    assert len(three.octaves()) == 3
    # Разное число октав → разный нормировочный множитель и разный шум.
    assert one.normalization_factor() != three.normalization_factor()
    a = one.create(LegacyRandom(11))
    b = three.create(LegacyRandom(11))
    assert a.get3(0.25, 0.25, 0.25) != b.get3(0.25, 0.25, 0.25)


def test_normal_noise_empty_legacy_is_positive_octaves():
    builder = NormalNoise.builder()
    builder.set_base_octave(2)
    builder.set_octave_count(0)
    definition = builder.build()
    random = LegacyRandom(0)
    with pytest.raises(NoiseBuildError) as excinfo:
        definition.create_for_legacy_nether_biome(random)
    assert excinfo.value.kind == NoiseBuildError.POSITIVE_LEGACY_OCTAVES
    # Отказ до розыгрышей: поток не сдвинут.
    assert random.next_long() == -6_819_959_017_335_327_829


def test_normal_noise_disabled_normalization_changes_amplitudes():
    enabled = (
        NormalNoise.builder()
        .set_octave_count(2)
        .set_normalization(Normalization.ENABLED)
        .build()
    )
    disabled = (
        NormalNoise.builder()
        .set_octave_count(2)
        .set_normalization(Normalization.DISABLED)
        .build()
    )
    # Отключённая нормировка не масштабирует амплитуды октав (2/3 для Enabled).
    assert enabled.octaves()[0].amplitude == pytest.approx(2.0 / 3.0)
    assert disabled.octaves()[0].amplitude == 1.0
    # Сумма амплитуд и верхняя граница поэтому различны.
    assert enabled.range()[1] != disabled.range()[1]


def test_create_legacy_fbm_work_limit_preserves_stream():
    random = LegacyRandom(0)
    with pytest.raises(NoiseBuildError) as excinfo:
        create_legacy_fbm(random, -2_147_483_648, [1.0])
    assert excinfo.value.kind == NoiseBuildError.LEGACY_WORK_LIMIT
    assert random.next_long() == LegacyRandom(0).next_long()


# ── stack.rs: скалярная часть ────────────────────────────────────────────────


def test_stack_zero_amplitude_and_nested_infinity():
    sampler = PerlinNoise(LegacyRandom(0))
    builder = NoiseStack.builder()
    builder.add(sampler, 1.0, 0.0)
    zero = builder.build()
    # Нулевая амплитуда даёт центр [0, 0], слой сохраняется.
    assert zero.range() == [0.0, 0.0]
    assert len(zero.layers()) == 1
    assert zero.get_layer(0) is sampler
    assert zero.get_layer(1) is None

    # Плоское добавление: амплитуда inf * 0.0 = NaN → ошибка сборки.
    flattened = NoiseStack.builder()
    flattened.add_stack(zero, 1.0, math.inf)
    with pytest.raises(NanRange):
        flattened.build()

    # Вложенный стек с inf: диапазон [0, 0], сэмпл NaN.
    nested = NoiseStack.builder().add(zero, 1.0, math.inf).build()
    assert nested.range() == [0.0, 0.0]
    assert math.isnan(nested.get3(1.0, 2.0, 3.0))


def test_stack_get2_and_get3_accumulate_layers():
    sampler = PerlinNoise(LegacyRandom(3))
    stack = (
        NoiseStack.builder()
        .add(sampler, 1.0, 1.0)
        .add(sampler, 2.0, 0.5)
        .build()
    )
    expected3 = 1.0 * sampler.get3(1.0, 2.0, 3.0) + 0.5 * sampler.get3(2.0, 4.0, 6.0)
    # Накопление идёт в f32, а эталон — в f64: сравниваем с допуском.
    assert stack.get3(1.0, 2.0, 3.0) == pytest.approx(expected3, abs=1e-6)
    expected2 = 1.0 * sampler.get2(1.0, 3.0) + 0.5 * sampler.get2(2.0, 6.0)
    assert stack.get2(1.0, 3.0) == pytest.approx(expected2, abs=1e-6)


def test_normal_noise_create_reference_stack_layout():
    definition = _reference_builder().build()
    stack = definition.create(LegacyRandom(0))
    # Две копии Perlin на октаву: 2 октавы * 2 = 4 слоя.
    assert len(stack.layers()) == 4
    frequencies = [layer.frequency for layer in stack.layers()]
    # Второй Perlin каждой октавы смещён на множитель 1.0181...
    assert frequencies[0] == 1.0 / 8.0
    assert math.isclose(frequencies[1], frequencies[0] * 1.018_126_888_217_522_7)
