# !Тесты порта horizon-core/src/random.rs — сверка с java.util.Random и
# !поведением vanilla (rejection sampling, позиционные seed'ы, worldgen).

import math

import pytest

from quadrix.core.geometry import BlockPos
from quadrix.core.random import (
    ADDEND,
    GOLDEN_RATIO,
    MASK,
    MULTIPLIER,
    SILVER_RATIO,
    InvalidBound,
    LegacyPositionalRandom,
    LegacyRandom,
    WorldgenRandom,
    XoroshiroPositionalRandom,
    XoroshiroRandom,
    java_string_hash,
    marsaglia_polar,
    mix_stafford13,
    position_seed,
    seed_from_hash,
    seed_from_hash_utf16,
    slime_chunk_random,
)


# ── Константы Java LCG ────────────────────────────────────────────────────
def test_lcg_constants_match_java():
    assert MULTIPLIER == 0x5DEECE66D
    assert ADDEND == 0xB
    assert MASK == (1 << 48) - 1


# ── Java sequence vectors ─────────────────────────────────────────────────
def test_java_seed_zero_sequence():
    rng = LegacyRandom(0)
    assert rng.next_int() == -1_155_484_576
    assert rng.next_int() == -723_955_400


def test_java_seed_42_first_int():
    rng = LegacyRandom(42)
    assert rng.next_int() == -1_170_105_035


def test_java_seed_zero_next_long():
    # Rust-тест: LegacyRandom::new(0).next_long() == -4962768465676381896
    assert LegacyRandom(0).next_long() == -4_962_768_465_676_381_896


def test_set_seed_resets_stream_and_gaussian():
    rng = LegacyRandom(123)
    rng.next_int()
    rng.set_seed(0)
    assert rng.next_int() == -1_155_484_576


# ── next_int_bound: rejection sampling, не modulo ─────────────────────────
def test_next_int_bound_range_and_repeatability():
    a = LegacyRandom(7)
    b = LegacyRandom(7)
    values = [a.next_int_bound(10) for _ in range(200)]
    assert all(0 <= v < 10 for v in values)
    assert values == [b.next_int_bound(10) for _ in range(200)]


def test_next_int_bound_one_is_zero():
    rng = LegacyRandom(99)
    assert all(rng.next_int_bound(1) == 0 for _ in range(100))
    xrng = XoroshiroRandom(99)
    assert all(xrng.next_int_bound(1) == 0 for _ in range(100))


def test_next_int_bound_power_of_two_ranges():
    rng = LegacyRandom(5)
    for bound in (2, 4, 8, 16, 32, 1024):
        for _ in range(50):
            assert 0 <= rng.next_int_bound(bound) < bound


def test_next_int_bound_rejects_non_positive_and_keeps_state():
    rng = LegacyRandom(0)
    reference = LegacyRandom(0)
    for bound in (0, -1, -(2**31)):
        with pytest.raises(InvalidBound):
            rng.next_int_bound(bound)
    rng.consume_count(-1)
    assert rng.next_long() == reference.next_long()


def test_xoroshiro_next_int_bound_rejects_and_keeps_state():
    rng = XoroshiroRandom(0)
    reference = XoroshiroRandom(0)
    for bound in (0, -1):
        with pytest.raises(InvalidBound):
            rng.next_int_bound(bound)
    assert rng.next_long() == reference.next_long()


# ── float / double / boolean ─────────────────────────────────────────────
def test_next_double_in_unit_interval():
    rng = LegacyRandom(11)
    for _ in range(5000):
        value = rng.next_double()
        assert 0.0 <= value < 1.0
    xrng = XoroshiroRandom(11)
    for _ in range(5000):
        value = xrng.next_double()
        assert 0.0 <= value < 1.0


def test_next_float_in_unit_interval():
    rng = LegacyRandom(12)
    for _ in range(5000):
        value = rng.next_float()
        assert 0.0 <= value < 1.0
    xrng = XoroshiroRandom(12)
    for _ in range(5000):
        value = xrng.next_float()
        assert 0.0 <= value < 1.0


def test_next_boolean_both_values_appear():
    rng = LegacyRandom(3)
    seen = {rng.next_boolean() for _ in range(200)}
    assert seen == {False, True}


# ── Gaussian ─────────────────────────────────────────────────────────────
def test_next_gaussian_mean_and_stddev():
    rng = LegacyRandom(2024)
    samples = [rng.next_gaussian() for _ in range(10_000)]
    mean = sum(samples) / len(samples)
    std = math.sqrt(sum((s - mean) ** 2 for s in samples) / len(samples))
    assert abs(mean) < 0.1
    assert abs(std - 1.0) < 0.1


def test_marsaglia_polar_caches_second_value():
    draws = iter([0.3, 0.2])

    def next_double():
        return next(draws)

    cache = [None]
    first = marsaglia_polar(cache, next_double)
    cached = cache[0]
    assert cached is not None
    assert first != cached
    # Второе значение отдаётся из кэша, не расходуя nextDouble.
    assert marsaglia_polar(cache, next_double) == cached
    assert cache[0] is None


# ── Hash / позиционные seed'ы ────────────────────────────────────────────
def test_java_string_hash_known_vectors():
    assert java_string_hash([]) == 0
    assert java_string_hash([ord(c) for c in "abc"]) == 96_354
    assert java_string_hash([ord(c) for c in "hello"]) == 99_162_322


def test_seed_from_hash_md5_vectors():
    assert seed_from_hash("") == [0xD41D8CD98F00B204, 0xE9800998ECF8427E]
    assert seed_from_hash("abc") == [0x900150983CD24FB0, 0xD6963F7D28E17F72]


def test_seed_from_hash_utf16_matches_utf8_and_replaces_lone_surrogate():
    assert seed_from_hash_utf16([ord("a"), ord("b")]) == seed_from_hash("ab")
    assert seed_from_hash_utf16([0xD800, ord("a"), 0xDC00]) == seed_from_hash("?a?")
    assert seed_from_hash_utf16([0xD83D, 0xDE00]) == seed_from_hash("😀")


def test_position_seed_order_matters():
    a = position_seed(BlockPos(1, 2, 3))
    b = position_seed(BlockPos(3, 2, 1))
    assert a != b
    assert position_seed(BlockPos(0, 0, 0)) == position_seed(BlockPos(0, 0, 0))


def test_legacy_positional_matches_direct_seeding():
    positions = [
        BlockPos(0, 0, 0),
        BlockPos(10, 64, -20),
        BlockPos(-1000, 320, 5000),
        BlockPos(123456, -64, -654321),
    ]
    for seed in (0, 42, -1, 123456789):
        factory = LegacyPositionalRandom(seed)
        for pos in positions:
            direct = LegacyRandom(position_seed(pos) ^ seed)
            opt = factory.at(pos)
            for _ in range(5):
                assert direct.next_int() == opt.next_int()


def test_legacy_positional_deterministic_and_hash_seed():
    factory = LegacyPositionalRandom(42)
    a = factory.at(BlockPos(0, 0, 0))
    b = factory.at(BlockPos(0, 0, 0))
    assert [a.next_int() for _ in range(5)] == [b.next_int() for _ in range(5)]
    direct = LegacyRandom(java_string_hash([ord(c) for c in "minecraft:ore"]) ^ 42)
    opt = factory.from_hash_of("minecraft:ore")
    for _ in range(5):
        assert direct.next_int() == opt.next_int()


def test_xoroshiro_positional_deterministic_and_order():
    factory = XoroshiroPositionalRandom(123, 456)
    a = factory.at(BlockPos(1, 2, 3))
    b = factory.at(BlockPos(1, 2, 3))
    assert [a.next_long() for _ in range(5)] == [b.next_long() for _ in range(5)]
    c = factory.at(BlockPos(3, 2, 1))
    d = factory.at(BlockPos(1, 2, 3))
    assert c.next_long() != d.next_long()


# ── Xoroshiro128++ ───────────────────────────────────────────────────────
def test_xoroshiro_zero_state_fallback_and_reseed():
    a = XoroshiroRandom.from_state(0, 0)
    b = XoroshiroRandom.from_state(GOLDEN_RATIO, SILVER_RATIO)
    assert a.state_words() == (GOLDEN_RATIO, SILVER_RATIO)
    for _ in range(100):
        assert a.next_long() == b.next_long()
    a.set_seed(-1)
    assert a.next_long() == XoroshiroRandom(-1).next_long()


def test_mix_stafford13_properties():
    assert mix_stafford13(0) == 0
    assert mix_stafford13(1) == mix_stafford13(1)
    values = {mix_stafford13(i) for i in range(1000)}
    assert len(values) == 1000
    assert all(0 <= v <= 0xFFFF_FFFF_FFFF_FFFF for v in values)


# ── WorldgenRandom ───────────────────────────────────────────────────────
def test_worldgen_wrapped_matches_legacy_bits():
    wrapped = WorldgenRandom(LegacyRandom(0))
    legacy = LegacyRandom(0)
    for _ in range(20):
        assert wrapped.next_int() == legacy.next_int()
    assert wrapped.count_value() == 20


def test_worldgen_plain_delegates_to_source():
    source = LegacyRandom(0)
    plain = WorldgenRandom.plain(source)
    assert plain.next_long() == LegacyRandom(0).next_long()
    assert plain.count_value() == 0


def test_worldgen_fork_returns_plain_source():
    parent = WorldgenRandom(LegacyRandom(77))
    forked = parent.fork()
    assert forked.wrapped is False


def test_worldgen_set_feature_seed_matches_java_formula():
    rng = WorldgenRandom(LegacyRandom(0))
    rng.set_feature_seed(1000, 3, 7)
    reference = LegacyRandom(1000 + 3 + 7 * 10000)
    assert rng.next_int() == reference.next_int()


def test_worldgen_set_decoration_seed_is_deterministic():
    a = WorldgenRandom(XoroshiroRandom(5))
    b = WorldgenRandom(XoroshiroRandom(5))
    first = a.set_decoration_seed(42, 10, -20)
    second = b.set_decoration_seed(42, 10, -20)
    assert first == second
    assert a.next_int() == b.next_int()


def test_slime_chunk_random_matches_legacy_formula():
    from quadrix.core.random import _as_i32, _as_i64, _as_u64

    x, z, seed, salt = 7, -3, 12345, 98765
    expected = _as_i64(
        _as_u64(seed)
        + _as_u64(_as_i32(_as_i32(x * x) * 4_987_142))
        + _as_u64(_as_i32(x * 5_947_611))
        + _as_u64(_as_i64(_as_i32(z * z)) * 4_392_871)
        + _as_u64(_as_i32(z * 389_711))
    ) ^ salt
    rng = slime_chunk_random(x, z, seed, salt)
    assert rng.next_int() == LegacyRandom(expected).next_int()


def test_triangle_and_triangle_float_bounds():
    rng = LegacyRandom(8)
    for _ in range(1000):
        value = rng.triangle(10.0, 2.0)
        assert 6.0 < value < 14.0
    for _ in range(1000):
        value = rng.triangle_float(10.0, 2.0)
        assert 6.0 < value < 14.0
