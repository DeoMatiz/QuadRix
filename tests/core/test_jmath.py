# !Тесты quadrix.core.jmath
# !Источник: horizon-core/src/jmath.rs #[cfg(test)] и horizon-core/src/geometry/trig.rs

from __future__ import annotations

import math

import pytest

from quadrix.core import jmath
from quadrix.core.jmath import (
    QUARTER,
    SIN_TABLE,
    aarch64,
    bit_count,
    bit_count_long,
    clamp,
    copy_sign,
    exact,
    fdlibm,
    float_to_int_bits,
    floor,
    ceil,
    floor_div,
    floor_mod,
    highest_one_bit,
    hypot,
    int_bits_to_float,
    long_bits_to_double,
    lowest_one_bit,
    next_after,
    number_of_leading_zeros,
    number_of_leading_zeros_long,
    round,
    round_f32,
    signum,
    sqrt,
    to_degrees,
    to_radians,
    trig_atan2,
    trig_cos,
    trig_sin,
)


def fb(bits: int) -> float:
    """Биты u64 → float (как f64::from_bits)."""
    return jmath.f64_from_bits(bits)


def b(x: float) -> int:
    """float → биты u64 (как f64::to_bits)."""
    return jmath.f64_bits(x)


# ── Math.round(float) / Math.round(double) ───────────────────────────────
@pytest.mark.parametrize(
    "x, expected",
    [
        (0.499_999_97, 0),
        (0.5, 1),
        (-0.5, 0),
        (2.5, 3),
        (-2.5, -2),
        (1e10, 2147483647),
        (-1e10, -2147483648),
        (float("nan"), 0),
        (8_388_609.0, 8_388_609),
    ],
)
def test_round_f32_is_exact_like_java(x, expected):
    assert round_f32(x) == expected


@pytest.mark.parametrize(
    "x, want",
    [
        (-2.5, -2),
        (2.5, 3),
        (-0.5, 0),
        (-1.5, -1),
        (0.5, 1),
        (-2.6, -3),
        (0.49999999999999994, 0),
        (float("nan"), 0),
        (float("inf"), 2 ** 63 - 1),
        (float("-inf"), -(2 ** 63)),
    ],
)
def test_round_ties_toward_positive_infinity(x, want):
    assert round(x) == want


# ── exact::sin / exact::cos ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "x_bits, expected_bits",
    [
        (0x400CFED4C52A225F, 0xBFDDB6FB8DFC34D9),
        (0x401562E96DC95E79, 0xBFE9C702A472EB20),
        (0x3FE83DEFDDA344B2, 0x3FE5FD24AE6866F7),
        (0x4015F2973D92BDCE, 0xBFE6DF4F6EB17F8B),
        (0x400CCAB8C6BCA404, 0xBFDC43578964FCD9),
        (0x4081275DB9D375BB, 0x3FE835467B8BB2A8),
        (0x408545BC77918C1A, 0x3FEB130E731423B6),
        (0xC08A86D7F86386D0, 0xBFE2BC064EFF6F2B),
    ],
)
def test_exact_sin_rounds_like_javas_x86_intrinsics(x_bits, expected_bits):
    assert b(exact.sin(fb(x_bits))) == expected_bits


@pytest.mark.parametrize(
    "x_bits, expected_bits",
    [
        (0x3FFF44A3B3C18058, 0xBFD7F1CA30696AA9),
        (0x401824074317A30F, 0x3FEF055D8C6CC46E),
        (0x4001B86D21E7B163, 0xBFE33824A109FCC3),
        (0xC08B37219EFA0D36, 0xBFE913C9A4E569FE),
        (0xC084CE175C9DC180, 0x3FEEF489EC429BA7),
        (0x40156DB4B780DCAB, 0x3FE33B5A52983C7C),
        (0x408E8B5ACCBB6A88, 0xBFEDAB57AE231703),
        # Около 3e-28 ниже половины: running sum это теряет.
        (0x3E937B1311FB4936, 0x3FEFFFFFFFFFFE85),
    ],
)
def test_exact_cos_rounds_like_javas_x86_intrinsics(x_bits, expected_bits):
    assert b(exact.cos(fb(x_bits))) == expected_bits


def test_exact_small_arguments_and_edges():
    assert exact.sin(1e-300) == 1e-300
    assert exact.cos(-1e-10) == 1.0
    assert b(exact.sin(0.0)) == 0
    assert b(exact.sin(-0.0)) == b(-0.0)
    assert math.isnan(exact.sin(float("nan")))
    assert math.isnan(exact.cos(float("inf")))
    assert exact.sin(math.pi / 2.0) == 1.0
    assert exact.cos(math.pi) == -1.0
    assert exact.sin(3.0e6) == math.sin(3.0e6)


# ── AArch64 sin / cos (fdlibm + FMA) ─────────────────────────────────────
@pytest.mark.parametrize(
    "x_bits, expected_bits",
    [
        (0x3FE63C5AB66B09F0, 0x3FE47D34215B54F7),
        (0xC0569150FE105E6F, 0xBFE7BC19D65AB55C),
        (0x4072C3F15B47B5D6, 0xBFEF32BE0F0A9124),
        (0x3FEE86C6FFCE047E, 0x3FEA1A47F46CBF28),
    ],
)
def test_aarch64_sin_matches_hotspot(x_bits, expected_bits):
    assert b(aarch64.sin(fb(x_bits))) == expected_bits


@pytest.mark.parametrize(
    "x_bits, expected_bits",
    [
        (0x3FBB10690EEADB00, 0x3FEFD24375DBAE28),
        (0xC0496CC08A65245D, 0x3FEAB1A44A8022C4),
        (0x40099262F89E73F8, 0xBFEFF3AA148795CE),
        (0x4001CE4E022387BC, 0xBFE37DD512BE4D00),
    ],
)
def test_aarch64_cos_matches_hotspot(x_bits, expected_bits):
    assert b(aarch64.cos(fb(x_bits))) == expected_bits


# ── fdlibm (StrictMath) ──────────────────────────────────────────────────
def test_fdlibm_log_and_log10_match_hotspot():
    assert b(fdlibm.log(fb(0x40569150FE105E6F))) == 0x401202E102F27B78
    assert b(fdlibm.log(fb(0x3FF5DEC70F518390))) == 0x3FD4009CDA1F8856
    assert b(fdlibm.log(fb(0x3FEB3D17325D493E))) == 0xBFC49EE8C4866F84
    assert b(fdlibm.log10(fb(0x3FF5DEC70F518390))) == 0x3FC15FB52AA5F051
    assert b(fdlibm.log10(fb(0x3FEB3D17325D493E))) == 0xBFB1E933CAE02F5F
    assert fdlibm.log(0.0) == -math.inf
    assert math.isnan(fdlibm.log(-1.0))


def test_fdlibm_cbrt_matches_hotspot():
    assert b(fdlibm.cbrt(fb(0x401BB21F8568BD0C))) == 0x3FFE7EE30C7A56F9
    assert b(fdlibm.cbrt(fb(0x3FC59F3A45C8FB80))) == 0x3FE1B0791E0F8A74
    assert b(fdlibm.cbrt(fb(0xBFDD73CDC693DDAB))) == 0xBFE8B4A6F43F1B73
    assert b(fdlibm.cbrt(fb(0xBFEB0715A8425E10))) == 0xBFEE3F99498DA6F6


def test_fdlibm_hypot_matches_hotspot():
    assert b(fdlibm.hypot(fb(0xC0569150FE105E6F), fb(0xC0056B970BF3B41A))) == 0x405693DB72F461A6
    assert b(fdlibm.hypot(fb(0x3FDC5999DF9270F4), fb(0xC006C3AD990F72C0))) == 0x400709DE26A1E40A
    assert b(fdlibm.hypot(fb(0x401BB21F8568BD0C), fb(0xBFFEB93D1A2EF904))) == 0x401CBDBB623D20C3
    assert fdlibm.hypot(3.0, 4.0) == 5.0


# ── Math.atan2 (fdlibm) ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    "y_bits, x_bits, expected_bits",
    [
        (0x440E8AFF5D1E293C, 0xC007E9768E83B37E, 0x3FF921FB54442D19),
        (0x440C610B44A22B37, 0xBFB07327BCB4C280, 0x3FF921FB54442D19),
        (0x43EB71600E035874, 0xBFEAFF77E5A9EA38, 0x3FF921FB54442D19),
        (0x3FF0000000000000, 0x8000000000000001, 0x3FF921FB54442D19),
        (0xBFF0000000000000, 0x8000000000000001, 0xBFF921FB54442D19),
        (0x0000000000000000, 0xBFF0000000000000, 0x400921FB54442D18),
        (0x8000000000000000, 0xBFF0000000000000, 0xC00921FB54442D18),
        (0x3FF0000000000000, 0x3FF0000000000000, 0x3FE921FB54442D18),
        (0x7FF0000000000000, 0xFFF0000000000000, 0x4002D97C7F3321D2),
    ],
)
def test_atan2_matches_strictmath(y_bits, x_bits, expected_bits):
    assert b(jmath.atan2(fb(y_bits), fb(x_bits))) == expected_bits


def test_atan2_nan():
    assert math.isnan(jmath.atan2(float("nan"), 1.0))
    assert math.isnan(jmath.atan2(1.0, float("nan")))


# ── Таблица синусов vanilla (trig.rs) ────────────────────────────────────
def test_sine_table_edges():
    assert SIN_TABLE[0] == 0.0
    assert SIN_TABLE[QUARTER] == 1.0
    assert len(SIN_TABLE) == 65536


def test_trig_sin_cos_and_long_narrowing():
    assert trig_sin(0.0) == 0.0
    assert trig_cos(0.0) == 1.0
    assert trig_sin(math.pi / 2.0) == 1.0
    # Java long-narrowing: NaN → 0, +∞ → 65535, -∞ → 0.
    assert trig_sin(float("nan")) == SIN_TABLE[0]
    assert trig_sin(float("inf")) == SIN_TABLE[65535]
    assert trig_sin(float("-inf")) == SIN_TABLE[0]


@pytest.mark.parametrize(
    "y_bits, x_bits, expected_bits",
    [
        (0x402F3B4B80414DF1, 0xC01853CA369B9E91, 0x3FFF13349F9DE798),
        (0xC025D31635F29DE8, 0xC018FB4A7EC43BA8, 0xC000B9966547A498),
        (0xC0265D9C2B5A472D, 0xC030954DC2DC3D10, 0xC00462E782D4C97E),
    ],
)
def test_trig_atan2_matches_client_tables(y_bits, x_bits, expected_bits):
    assert b(trig_atan2(fb(y_bits), fb(x_bits))) == expected_bits


def test_fdlibm_asin_table_values():
    assert b(jmath.fdlibm_asin(60.0 / 256.0)) == 0x3FCE481C0FCE7134
    assert b(jmath.fdlibm_asin(61.0 / 256.0)) == 0x3FCECBD75B6CD8F0


# ── Java Math helpers ────────────────────────────────────────────────────
def test_floor_div_is_java_not_truncation():
    # Java Math.floorDiv: -7 / 3 == -3, а не -2 (усечение).
    assert floor_div(-7, 3) == -3
    assert floor_div(7, -3) == -3
    assert floor_div(-7, -3) == 2
    assert floor_div(7, 3) == 2
    with pytest.raises(ZeroDivisionError):
        floor_div(1, 0)


def test_floor_mod_for_negatives():
    # Java Math.floorMod: -7 % 3 == 2 (не -1, как у % в C).
    assert floor_mod(-7, 3) == 2
    assert floor_mod(7, -3) == -2
    assert floor_mod(-7, -3) == -1
    assert floor_mod(7, 3) == 1
    # floorMod согласован с floorDiv: a == floorDiv(a,b)*b + floorMod(a,b).
    for a in (-7, -1, 0, 5):
        for bb in (-3, 3):
            assert a == floor_div(a, bb) * bb + floor_mod(a, bb)


def test_clamp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 0, 3) == 2
    assert math.isnan(clamp(float("nan"), 0.0, 3.0))
    with pytest.raises(ValueError):
        clamp(1, 3, 0)


def test_signum():
    assert signum(0.0) == 0.0
    assert signum(-5.0) == -1.0
    assert signum(5.0) == 1.0
    assert math.isnan(signum(float("nan")))
    assert math.copysign(1.0, signum(-0.0)) < 0.0


def test_sqrt_negative_is_nan_like_java():
    assert math.isnan(sqrt(-1.0))
    assert sqrt(9.0) == 3.0
    assert sqrt(float("inf")) == math.inf


def test_floor_and_ceil_return_doubles():
    assert floor(2.7) == 2.0
    assert floor(-2.1) == -3.0
    assert ceil(2.1) == 3.0
    assert ceil(-2.7) == -2.0
    assert math.isnan(floor(float("nan")))
    assert floor(float("inf")) == math.inf


def test_java_min_max_zero_and_nan():
    assert jmath.java_min(1.0, 2.0) == 1.0
    assert jmath.java_max(1.0, 2.0) == 2.0
    assert math.isnan(jmath.java_min(float("nan"), 1.0))
    assert math.isnan(jmath.java_max(float("nan"), 1.0))
    # -0.0 < +0.0
    assert math.copysign(1.0, jmath.java_min(0.0, -0.0)) < 0.0
    assert math.copysign(1.0, jmath.java_max(-0.0, 0.0)) > 0.0


def test_hypot_java_helper():
    assert hypot(3.0, 4.0) == 5.0
    assert hypot(-3.0, -4.0) == 5.0


def test_to_radians_to_degrees():
    assert to_radians(180.0) == pytest.approx(math.pi, abs=1e-15)
    assert to_radians(0.0) == 0.0
    assert to_degrees(math.pi) == pytest.approx(180.0, abs=1e-13)


def test_next_after_and_copy_sign():
    assert next_after(1.0, 2.0) > 1.0
    assert next_after(1.0, 0.0) < 1.0
    assert next_after(0.0, 1.0) == 5e-324  # Double.MIN_VALUE
    assert copy_sign(3.0, -1.0) == -3.0
    assert copy_sign(-3.0, 1.0) == 3.0


# ── Integer / Long helpers ──────────────────────────────────────────────
def test_number_of_leading_zeros_and_bit_count():
    assert number_of_leading_zeros(1) == 31
    assert number_of_leading_zeros(0) == 32
    assert number_of_leading_zeros(-1) == 0
    assert bit_count(0b1011) == 3
    assert bit_count(0) == 0
    assert number_of_leading_zeros_long(1) == 63
    assert bit_count_long(0b1011) == 3


def test_highest_and_lowest_one_bit():
    assert highest_one_bit(0b1011) == 0b1000
    assert highest_one_bit(0) == 0
    assert highest_one_bit(-1) == -(2 ** 31)  # Integer.MIN_VALUE
    assert lowest_one_bit(0b1011) == 0b1
    assert lowest_one_bit(0) == 0
    assert lowest_one_bit(-(2 ** 31)) == -(2 ** 31)


# ── Float / Double helpers ──────────────────────────────────────────────
def test_float_to_int_bits():
    assert float_to_int_bits(1.0) == 0x3F800000
    assert float_to_int_bits(-0.0) == 0x80000000 - 2 ** 32  # int знак
    assert float_to_int_bits(float("nan")) == 0x7FC00000
    assert int_bits_to_float(0x3F800000) == 1.0


def test_double_to_long_bits():
    assert jmath.double_to_long_bits(1.0) == 0x3FF0000000000000
    assert jmath.double_to_long_bits(float("nan")) == 0x7FF8000000000000
    assert long_bits_to_double(0x3FF0000000000000) == 1.0


def test_is_nan_is_infinite():
    assert jmath.is_nan(float("nan"))
    assert not jmath.is_nan(1.0)
    assert jmath.is_infinite(float("inf"))
    assert not jmath.is_infinite(1.0)
