# !Порт horizon-core/src/jmath.rs — `java.lang.Math` так, как его считает HotSpot.
# !
# !Rust вызывает платформенный libm, а тот округляет иначе (glibc / Apple libm /
# !Windows libm расходятся в последнем бите). Здесь повторены ветки, которые
# !выбирает Horizon:
# !  - `sin`/`cos` на Windows — правильно округлённые ([exact]).
# !  - `atan2`, `atan`, `asin`, `acos`, `hypot` — fdlibm (`StrictMath`).
# !  - `tan`, `exp`, `log`, `log10`, `pow`, `cbrt` — платформенный libm.
# !
# !Дополнительно (используется остальным портом, семантика Java):
# !  - Java `Math`/`Integer`/`Long`/`Float`/`Double` помощники (floorDiv,
# !    floorMod, round, numberOfLeadingZeros, floatToIntBits, ...).
# !  - Таблица синусов vanilla (`geometry/trig.rs`): SCALE, SIN_TABLE.

from __future__ import annotations

import math
import struct
from fractions import Fraction

__all__ = [
    # jmath.rs
    "round_f32", "round", "sin", "cos", "tan", "exp", "log", "log10",
    "pow", "cbrt", "atan2", "atan", "asin", "acos", "hypot",
    "fdlibm", "aarch64", "exact",
    # Java Math
    "floor", "ceil", "sqrt", "signum", "clamp", "java_min", "java_max",
    "floor_div", "floor_mod", "to_radians", "to_degrees",
    "next_after", "copy_sign",
    # Integer / Long
    "number_of_leading_zeros", "number_of_leading_zeros_long",
    "bit_count", "bit_count_long", "highest_one_bit", "lowest_one_bit",
    # Float / Double
    "is_nan", "is_infinite", "float_to_int_bits", "int_bits_to_float",
    "double_to_long_bits", "long_bits_to_double",
    # trig.rs (табличный синус vanilla)
    "SCALE", "QUARTER", "SIN_TABLE", "sine_table", "trig_sin", "trig_cos",
    "trig_atan2", "fdlibm_asin", "fdlibm_atan", "fdlibm_atan2",
    "f64_bits", "f64_from_bits", "f32_bits", "f32_from_bits",
]

# ── Побитовые помощники (Rust `f64::to_bits` / `from_bits`) ──────────────
_U64 = struct.Struct(">Q")
_I64 = struct.Struct(">q")
_F64 = struct.Struct(">d")
_U32 = struct.Struct(">I")
_I32 = struct.Struct(">i")
_F32 = struct.Struct(">f")

MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_INF = math.inf
_NAN = math.nan


def f64_bits(x: float) -> int:
    """`x.to_bits()` как u64."""
    return _U64.unpack(_F64.pack(float(x)))[0]


def f64_from_bits(b: int) -> float:
    """`f64::from_bits(b)`."""
    return _F64.unpack(_U64.pack(b & MASK64))[0]


def f32_bits(x: float) -> int:
    """`f32::to_bits` с насыщением в бесконечность вместо OverflowError."""
    try:
        return _U32.unpack(_F32.pack(float(x)))[0]
    except OverflowError:
        return 0xFF80_0000 if x < 0 else 0x7F80_0000


def f32_from_bits(b: int) -> float:
    """`f32::from_bits(b)`, возвращает Python float (f64) значения f32."""
    return _F32.unpack(_U32.pack(b & 0xFFFF_FFFF))[0]


def _f32(x: float) -> float:
    """Округлить double до ближайшего f32 (как `x as f32`)."""
    return f32_from_bits(f32_bits(x))


def _signed32(b: int) -> int:
    b &= 0xFFFF_FFFF
    return b - 0x1_0000_0000 if b >= 0x8000_0000 else b


def _signed64(b: int) -> int:
    b &= MASK64
    return b - 0x1_0000_0000_0000_0000 if b >= 0x8000_0000_0000_0000 else b


def hi(x: float) -> int:
    """Старшее 32-битное слово как i32."""
    return _signed32(f64_bits(x) >> 32)


def with_hi(x: float, high: int) -> float:
    """Заменить старшее слово `x` на `high` (младшее сохраняется)."""
    return f64_from_bits((f64_bits(x) & 0xFFFF_FFFF) | ((high & 0xFFFF_FFFF) << 32))


_I64_MIN = -(2 ** 63)
_I64_MAX = 2 ** 63 - 1
_I32_MIN = -(2 ** 31)
_I32_MAX = 2 ** 31 - 1


def _f64_to_i64_sat(x: float) -> int:
    """Rust `x as i64`: насыщение, NaN → 0."""
    if x != x:
        return 0
    if x >= 9_223_372_036_854_775_808.0:  # 2^63
        return _I64_MAX
    if x < -9_223_372_036_854_775_808.0:  # -2^63
        return _I64_MIN
    return int(x)


def _f32_to_i32_sat(x: float) -> int:
    """Rust `x as i32`: насыщение, NaN → 0."""
    if x != x:
        return 0
    if x >= 2_147_483_648.0:  # 2^31
        return _I32_MAX
    if x < -2_147_483_648.0:
        return _I32_MIN
    return int(x)


def _round_half_away(x: float) -> float:
    """Rust `f64::round`: ближайшее, полуцелые — от нуля."""
    if x >= 0.0:
        return float(math.floor(x + 0.5))
    return float(math.ceil(x - 0.5))


def _sqrt(x: float) -> float:
    """sqrt с Java-семантикой (отрицательное → NaN), без исключений."""
    if x != x:
        return x
    if x < 0.0:
        return _NAN
    return math.sqrt(x)


def _platform_sin(x: float) -> float:
    if x != x or math.isinf(x):
        return _NAN
    return math.sin(x)


def _platform_cos(x: float) -> float:
    if x != x or math.isinf(x):
        return _NAN
    return math.cos(x)


# ── Math.round(float) / Math.round(double) ───────────────────────────────
def round_f32(a: float) -> int:
    """`Math.round(float)` бит в бит: без `x + 0.5` в f32, полуцелые — к
    +бесконечности, насыщение в диапазон int, NaN → 0."""
    b = f32_bits(a)
    bits = _signed32(b)
    biased_exp = (bits & 0x7F80_0000) >> 23
    shift = (22 + 127) - biased_exp
    if (shift & -32) == 0:
        r = (bits & 0x007F_FFFF) | 0x0080_0000
        if bits < 0:
            r = -r
        return ((r >> shift) + 1) >> 1
    return _f32_to_i32_sat(_f32(a))


def round(x: float) -> int:
    """`Math.round(double)`: ближайший long, полуцелые к +бесконечности
    (значит `-2.5` → `-2`), насыщение, NaN → 0."""
    if x != x:
        return 0
    if math.isinf(x):
        return _I64_MAX if x > 0 else _I64_MIN
    f = math.floor(x)
    r = f + 1.0 if x - f >= 0.5 else f
    return _f64_to_i64_sat(float(r))


# ── Платформенные функции (ветка не-aarch64 в Rust) ──────────────────────
def tan(x: float) -> float:
    """`Math.tan`."""
    if x != x or math.isinf(x):
        return _NAN
    return math.tan(x)


def exp(x: float) -> float:
    """`Math.exp`."""
    try:
        return math.exp(x)
    except OverflowError:
        return _INF


def log(x: float) -> float:
    """`Math.log`: log(0) = -∞, log(<0) = NaN."""
    if x != x:
        return x
    if x < 0.0:
        return _NAN
    if x == 0.0:
        return -_INF
    return math.log(x)


def log10(x: float) -> float:
    """`Math.log10`: log10(0) = -∞, log10(<0) = NaN."""
    if x != x:
        return x
    if x < 0.0:
        return _NAN
    if x == 0.0:
        return -_INF
    return math.log10(x)


def pow(x: float, y: float) -> float:
    """`Math.pow`.
    # FALLBACK: Python math.pow не считает 0^-n и (-x)^дробное; отдаём как Java.
    """
    if x == 0.0 and y < 0.0:
        # Java: 0.0^-n = +∞; -0.0^-нечётное = -∞.
        neg = math.copysign(1.0, x) < 0.0 and float(y).is_integer() and int(y) % 2 != 0
        return -_INF if neg else _INF
    try:
        return math.pow(x, y)
    except OverflowError:
        # Знак бесконечности как у math.pow, если он не переполнился.
        return _INF
    except ValueError:
        return _NAN


def cbrt(x: float) -> float:
    """`Math.cbrt`."""
    if hasattr(math, "cbrt"):
        return math.cbrt(x)
    # FALLBACK: Python < 3.11 без math.cbrt.
    if x != x or math.isinf(x) or x == 0.0:
        return x
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def atan(x: float) -> float:
    """`Math.atan` (libm, как в Rust)."""
    return math.atan(x)


def asin(x: float) -> float:
    """`Math.asin`: вне [-1, 1] → NaN."""
    if x != x or x < -1.0 or x > 1.0:
        return _NAN
    return math.asin(x)


def acos(x: float) -> float:
    """`Math.acos`: вне [-1, 1] → NaN."""
    if x != x or x < -1.0 or x > 1.0:
        return _NAN
    return math.acos(x)


# ── fdlibm (`StrictMath`) ────────────────────────────────────────────────
_TWO54 = 1.80143985094819840000e16


def _fdlibm_log(x: float) -> float:
    LN2_HI = 6.93147180369123816490e-01
    LN2_LO = 1.90821492927058770002e-10
    LG1 = 6.666666666666735130e-01
    LG2 = 3.999999999940941908e-01
    LG3 = 2.857142874366239149e-01
    LG4 = 2.222219843214978396e-01
    LG5 = 1.818357216161805012e-01
    LG6 = 1.531383769920937332e-01
    LG7 = 1.479819860511658591e-01

    hx = hi(x)
    lx = f64_bits(x) & 0xFFFF_FFFF
    k = 0
    if hx < 0x0010_0000:
        if (((hx & 0x7FFF_FFFF) | lx) & 0xFFFF_FFFF) == 0:
            return -_INF
        if hx < 0:
            return _NAN
        k -= 54
        x *= _TWO54
        hx = hi(x)
    if hx >= 0x7FF0_0000:
        return x + x
    k += (hx >> 20) - 1023
    hx &= 0x000F_FFFF
    i = (hx + 0x9_5F64) & 0x10_0000
    x = with_hi(x, hx | (i ^ 0x3FF0_0000))
    k += i >> 20
    f = x - 1.0
    if (0x000F_FFFF & (2 + hx)) < 3:
        if f == 0.0:
            if k == 0:
                return 0.0
            dk = float(k)
            return dk * LN2_HI + dk * LN2_LO
        r = f * f * (0.5 - 0.33333333333333333 * f)
        if k == 0:
            return f - r
        dk = float(k)
        return dk * LN2_HI - ((r - dk * LN2_LO) - f)
    s = f / (2.0 + f)
    dk = float(k)
    z = s * s
    i = hx - 0x6_147A
    w = z * z
    j = 0x6B851 - hx
    t1 = w * (LG2 + w * (LG4 + w * LG6))
    t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)))
    i |= j
    r = t2 + t1
    if i > 0:
        hfsq = 0.5 * f * f
        if k == 0:
            return f - (hfsq - s * (hfsq + r))
        return dk * LN2_HI - ((hfsq - (s * (hfsq + r) + dk * LN2_LO)) - f)
    if k == 0:
        return f - s * (f - r)
    return dk * LN2_HI - ((s * (f - r) - dk * LN2_LO) - f)


def _fdlibm_log10(x: float) -> float:
    IVLN10 = 4.34294481903251816668e-01
    LOG10_2HI = 3.01029995663611771306e-01
    LOG10_2LO = 3.69423907715893078616e-13

    hx = hi(x)
    lx = f64_bits(x) & 0xFFFF_FFFF
    k = 0
    if hx < 0x0010_0000:
        if (((hx & 0x7FFF_FFFF) | lx) & 0xFFFF_FFFF) == 0:
            return -_INF
        if hx < 0:
            return _NAN
        k -= 54
        x *= _TWO54
        hx = hi(x)
    if hx >= 0x7FF0_0000:
        return x + x
    k += (hx >> 20) - 1023
    i = (k & 0xFFFF_FFFF) >> 31
    hx = (hx & 0x000F_FFFF) | ((0x3FF - i) << 20)
    y = float(k + i)
    x = with_hi(x, hx)
    z = y * LOG10_2LO + IVLN10 * _fdlibm_log(x)
    return z + y * LOG10_2HI


def _fdlibm_cbrt(x: float) -> float:
    B1 = 715094163
    B2 = 696219795
    C = 5.42857142857142815906e-01
    D = -7.05306122448979611050e-01
    E = 1.41428571428571436819e+00
    F = 1.60714285714285720630e+00
    G = 3.57142857142857150787e-01

    if x == 0.0 or not math.isfinite(x):
        return x
    sign = -1.0 if x < 0.0 else 1.0
    x = abs(x)
    if x < 2.2250738585072014e-308:  # f64::MIN_POSITIVE
        t = 18014398509481984.0  # 2^54
        t *= x
        t = with_hi(t, hi(t) // 3 + B2)
    else:
        t = with_hi(0.0, hi(x) // 3 + B1)
    r = t * t / x
    s = C + r * t
    t *= G + F / (s + E + D / s)
    t = f64_from_bits(f64_bits(t) & 0xFFFF_FFFF_0000_0000)
    t = with_hi(t, hi(t) + 1)
    s = t * t
    r = x / s
    w = t + t
    r = (r - t) / (w + r)
    t += t * r
    return sign * t


def _fdlibm_hypot(x: float, y: float) -> float:
    a = abs(x)
    b = abs(y)
    if not math.isfinite(a) or not math.isfinite(b):
        if a == _INF or b == _INF:
            return _INF
        return a + b
    if b > a:
        a, b = b, a
    ha = hi(a)
    hb = hi(b)
    if ha - hb > 0x3C0_0000:
        return a + b
    k = 0
    if a > f64_from_bits(0x5F30_0000_FFFF_FFFF):
        ha -= 0x2580_0000
        hb -= 0x2580_0000
        a *= f64_from_bits(0x1A70_0000_0000_0000)  # 2^-600
        b *= f64_from_bits(0x1A70_0000_0000_0000)
        k += 600
    if b < f64_from_bits(0x20B0_0000_0000_0000):  # 2^-500
        if b < 2.2250738585072014e-308:  # f64::MIN_POSITIVE
            if b == 0.0:
                return a
            t1 = f64_from_bits(0x7FD0_0000_0000_0000)  # 2^1022
            b *= t1
            a *= t1
            k -= 1022
        else:
            ha += 0x2580_0000
            hb += 0x2580_0000
            a *= f64_from_bits(0x6570_0000_0000_0000)  # 2^600
            b *= f64_from_bits(0x6570_0000_0000_0000)
            k -= 600
    w = a - b
    if w > b:
        t1 = with_hi(0.0, ha)
        t2 = a - t1
        w = _sqrt(t1 * t1 - (b * (-b) - t2 * (a + t1)))
    else:
        a += a
        y1 = with_hi(0.0, hb)
        y2 = b - y1
        t1 = with_hi(0.0, ha + 0x0010_0000)
        t2 = a - t1
        w = _sqrt(t1 * y1 - (w * (-w) - (t1 * y2 + t2 * b)))
    if k != 0:
        return f64_from_bits(((1023 + k) & MASK64) << 52 & MASK64) * w
    return w


def _fdlibm_asin(x: float) -> float:
    PIO2_HI = 1.57079632679489655800e+00
    PIO2_LO = 6.12323399573676603587e-17
    PIO4_HI = 7.85398163397448278999e-01
    PS0 = 1.66666666666666657415e-01
    PS1 = -3.25565818622400915405e-01
    PS2 = 2.01212532134862925881e-01
    PS3 = -4.00555345006794114027e-02
    PS4 = 7.91534994289814532176e-04
    PS5 = 3.47933107596021167570e-05
    QS1 = -2.40339491173441421878e+00
    QS2 = 2.02094576023350569471e+00
    QS3 = -6.88283971605453293030e-01
    QS4 = 7.70381505559019352791e-02

    bits = f64_bits(x)
    hx = hi(x)
    ix = hx & 0x7FFF_FFFF
    if ix >= 0x3FF0_0000:
        if ((((ix - 0x3FF0_0000) & 0xFFFF_FFFF) | (bits & 0xFFFF_FFFF)) & 0xFFFF_FFFF) == 0:
            return x * PIO2_HI + x * PIO2_LO
        # |x| > 1 (или NaN): как Rust `(x - x) / (x - x)`.
        return _NAN
    elif ix < 0x3FE0_0000:
        if ix < 0x3E40_0000 and 1.0e300 + x > 1.0:
            return x
        t = x * x
        p = t * (PS0 + t * (PS1 + t * (PS2 + t * (PS3 + t * (PS4 + t * PS5)))))
        q = 1.0 + t * (QS1 + t * (QS2 + t * (QS3 + t * QS4)))
        w = p / q
        return x + x * w
    w = 1.0 - abs(x)
    t = w * 0.5
    p = t * (PS0 + t * (PS1 + t * (PS2 + t * (PS3 + t * (PS4 + t * PS5)))))
    q = 1.0 + t * (QS1 + t * (QS2 + t * (QS3 + t * QS4)))
    s = math.sqrt(t)
    if ix >= 0x3FEF_3333:
        w = p / q
        return PIO2_HI - (2.0 * (s + s * w) - PIO2_LO)
    w = f64_from_bits(f64_bits(s) & 0xFFFF_FFFF_0000_0000)
    cc = (t - w * w) / (s + w)
    r = p / q
    p = 2.0 * s * r - (PIO2_LO - 2.0 * cc)
    q = PIO4_HI - 2.0 * w
    t = PIO4_HI - (p - q)
    return t if hx > 0 else -t


def fdlibm_asin(x: float) -> float:
    """fdlibm `__ieee754_asin` (= `StrictMath.asin`)."""
    return _fdlibm_asin(x)


def _fdlibm_atan(x: float) -> float:
    ATANHI = [
        4.63647609000806093515e-01,
        7.85398163397448278999e-01,
        9.82793723247329054077e-01,
        1.57079632679489655800e+00,
    ]
    ATANLO = [
        2.26987774529616870924e-17,
        3.06161699786838301793e-17,
        1.39033110312309984516e-17,
        6.12323399573676603587e-17,
    ]
    AT = [
        3.33333333333329318027e-01,
        -1.99999999998764832476e-01,
        1.42857142725034663711e-01,
        -1.11111104054623557880e-01,
        9.09088713343650656196e-02,
        -7.69187620504482999495e-02,
        6.66107313738753120669e-02,
        -5.83357013379057348645e-02,
        4.97687799461593236017e-02,
        -3.65315727442169155270e-02,
        1.62858201153657823623e-02,
    ]

    hx = hi(x)
    ix = hx & 0x7FFF_FFFF
    if ix >= 0x4410_0000:
        if ix > 0x7FF0_0000 or (ix == 0x7FF0_0000 and (f64_bits(x) & 0xFFFF_FFFF) != 0):
            return x + x  # NaN
        return ATANHI[3] + ATANLO[3] if hx > 0 else -ATANHI[3] - ATANLO[3]
    if ix < 0x3FDC_0000:
        if ix < 0x3E20_0000 and 1.0e300 + x > 1.0:
            return x
        ident = -1
    else:
        x = abs(x)
        if ix < 0x3FF3_0000:
            if ix < 0x3FE6_0000:
                ident = 0
                x = (2.0 * x - 1.0) / (2.0 + x)
            else:
                ident = 1
                x = (x - 1.0) / (x + 1.0)
        elif ix < 0x4003_8000:
            ident = 2
            x = (x - 1.5) / (1.0 + 1.5 * x)
        else:
            ident = 3
            x = -1.0 / x
    z = x * x
    w = z * z
    s1 = z * (AT[0] + w * (AT[2] + w * (AT[4] + w * (AT[6] + w * (AT[8] + w * AT[10])))))
    s2 = w * (AT[1] + w * (AT[3] + w * (AT[5] + w * (AT[7] + w * AT[9]))))
    if ident < 0:
        return x - x * (s1 + s2)
    z = ATANHI[ident] - ((x * (s1 + s2) - ATANLO[ident]) - x)
    return -z if hx < 0 else z


def fdlibm_atan(x: float) -> float:
    """fdlibm `atan` (= `StrictMath.atan`)."""
    return _fdlibm_atan(x)


def _fdlibm_atan2(y: float, x: float) -> float:
    TINY = 1.0e-300
    PI_O_4 = 7.85398163397448278999e-01
    PI_O_2 = 1.57079632679489655800e+00
    PI = 3.14159265358979311598e+00
    PI_LO = 1.22464679914735320717e-16

    xb = f64_bits(x)
    yb = f64_bits(y)
    hx = _signed32(xb >> 32)
    ix = hx & 0x7FFF_FFFF
    lx = xb & 0xFFFF_FFFF
    hy = _signed32(yb >> 32)
    iy = hy & 0x7FFF_FFFF
    ly = yb & 0xFFFF_FFFF

    # NaN-проверка: (ix | ((lx | -lx) >> 31)) > 0x7ff00000
    tx = ((ix & 0xFFFF_FFFF) | (((lx | (-lx & 0xFFFF_FFFF)) & 0xFFFF_FFFF) >> 31)) & 0xFFFF_FFFF
    ty = ((iy & 0xFFFF_FFFF) | (((ly | (-ly & 0xFFFF_FFFF)) & 0xFFFF_FFFF) >> 31)) & 0xFFFF_FFFF
    if tx > 0x7FF0_0000 or ty > 0x7FF0_0000:
        return x + y

    if ((((hx - 0x3FF0_0000) & 0xFFFF_FFFF) | lx) & 0xFFFF_FFFF) == 0:
        return _fdlibm_atan(y)

    m = ((hy >> 31) & 1) | ((hx >> 30) & 2)

    if ((iy | ly) & 0xFFFF_FFFF) == 0:
        if m in (0, 1):
            return y
        if m == 2:
            return PI + TINY
        return -PI - TINY

    if ((ix | lx) & 0xFFFF_FFFF) == 0:
        return -PI_O_2 - TINY if hy < 0 else PI_O_2 + TINY

    if ix == 0x7FF0_0000:
        if iy == 0x7FF0_0000:
            if m == 0:
                return PI_O_4 + TINY
            if m == 1:
                return -PI_O_4 - TINY
            if m == 2:
                return 3.0 * PI_O_4 + TINY
            return -3.0 * PI_O_4 - TINY
        if m == 0:
            return 0.0
        if m == 1:
            return -0.0
        if m == 2:
            return PI + TINY
        return -PI - TINY

    if iy == 0x7FF0_0000:
        return -PI_O_2 - TINY if hy < 0 else PI_O_2 + TINY

    k = (iy - ix) >> 20
    if k > 60:
        z = PI_O_2 + 0.5 * PI_LO
    elif hx < 0 and k < -60:
        z = 0.0
    else:
        z = _fdlibm_atan(abs(y / x))

    if m == 0:
        return z
    if m == 1:
        return -z
    if m == 2:
        return PI - (z - PI_LO)
    return (z - PI_LO) - PI


def fdlibm_atan2(y: float, x: float) -> float:
    """fdlibm `__ieee754_atan2` (= `StrictMath.atan2`, а значит и `Math.atan2`)."""
    return _fdlibm_atan2(y, x)


class fdlibm:
    """Rust `mod fdlibm` — то, что `libm` считает иначе."""

    log = staticmethod(_fdlibm_log)
    log10 = staticmethod(_fdlibm_log10)
    cbrt = staticmethod(_fdlibm_cbrt)
    hypot = staticmethod(_fdlibm_hypot)


# ── HotSpot AArch64 `Math.sin` / `Math.cos` (fdlibm + FMA) ────────────────
_S = [
    -1.66666666666666324348e-01,
    8.33333333332248946124e-03,
    -1.98412698298579493134e-04,
    2.75573137070700676789e-06,
    -2.50507602534068634195e-08,
    1.58969099521155010221e-10,
]
_C = [
    4.16666666666666019037e-02,
    -1.38888888888741095749e-03,
    2.48015872894767294178e-05,
    -2.75573143513906633035e-07,
    2.08757232129817482790e-09,
    -1.13596475577881948265e-11,
]
_INVPIO2 = 6.36619772367581382433e-01
_PIO2_1 = 1.57079632673412561417e+00
_PIO2_1T = 6.07710050650619224932e-11
_PIO2_2 = 6.07710050630396597660e-11
_PIO2_2T = 2.02226624879595063154e-21
_PIO2_3 = 2.02226624871116645580e-21
_PIO2_3T = 8.47842766036889956997e-32
_NPIO2_HW = [
    0x3FF921FB, 0x400921FB, 0x4012D97C, 0x401921FB, 0x401F6A7A, 0x4022D97C, 0x4025FDBB,
    0x402921FB, 0x402C463A, 0x402F6A7A, 0x4031475C, 0x4032D97C, 0x40346B9C, 0x4035FDBB,
    0x40378FDB, 0x403921FB, 0x403AB41B, 0x403C463A, 0x403DD85A, 0x403F6A7A, 0x40407E4C,
    0x4041475C, 0x4042106C, 0x4042D97C, 0x4043A28C, 0x40446B9C, 0x404534AC, 0x4045FDBB,
    0x4046C6CB, 0x40478FDB, 0x404858EB, 0x404921FB,
]

_MATH_FMA = getattr(math, "fma", None)


def _fma(a: float, b: float, c: float) -> float:
    """`f64::mul_add`. На 3.13+ есть math.fma, иначе точная Fraction."""
    if _MATH_FMA is not None:
        return _MATH_FMA(a, b, c)
    return float(Fraction(a) * Fraction(b) + Fraction(c))


def _kernel_sin(x: float, y: float, iy: bool) -> float:
    z = x * x
    v = z * x
    r = _fma(z, _S[5], _S[4])
    r = _fma(z, r, _S[3])
    r = _fma(z, r, _S[2])
    r = _fma(z, r, _S[1])
    if not iy:
        return _fma(v, _fma(z, r, _S[0]), x)
    t = _fma(-v, r, 0.5 * y)
    t = _fma(-z, t, y)
    return x + _fma(v, _S[0], t)


def _kernel_cos(x: float, y: float, ix: int) -> float:
    z = x * x
    r = _fma(z, _C[5], _C[4])
    r = _fma(z, r, _C[3])
    xy = x * y
    r = _fma(z, r, _C[2])
    r = _fma(z, r, _C[1])
    zz = z * z
    r = _fma(z, r, _C[0])
    if ix <= 0x3FD33333:
        v = _fma(-zz, r, xy)
        return 1.0 - _fma(0.5, z, v)
    qx = 0.28125 if ix > 0x3FE90000 else f64_from_bits((((ix - 0x0020_0000) & 0xFFFF_FFFF) << 32) & MASK64)
    zr_xy = _fma(zz, r, -xy)
    h = _fma(0.5, z, -qx)
    a = 1.0 - qx
    return a - (h - zr_xy)


def _exponent(y: float) -> int:
    return (((f64_bits(y) << 1) & MASK64) >> 53)


def _rem_pio2(x: float, ix: int):
    if ix < 0x4002D97C:
        if (f64_bits(x) >> 63) == 0:
            z = x - _PIO2_1
            if ix != 0x3FF921FB:
                y0 = z - _PIO2_1T
                return (1, y0, (z - y0) - _PIO2_1T)
            z = z - _PIO2_2
            y0 = z - _PIO2_2T
            return (1, y0, (z - y0) - _PIO2_2T)
        z = x + _PIO2_1
        if ix != 0x3FF921FB:
            y0 = z + _PIO2_1T
            return (-1, y0, (z - y0) + _PIO2_1T)
        z = z + _PIO2_2
        y0 = z + _PIO2_2T
        return (-1, y0, (z - y0) + _PIO2_2T)
    if ix > 0x413921FB:
        return None
    t = abs(x)
    fnv = _fma(t, _INVPIO2, 0.5)
    fnv = float(math.trunc(fnv))
    n = int(fnv)
    r = _fma(-fnv, _PIO2_1, t)
    w = fnv * _PIO2_1T
    y0 = r - w
    if n > 32 or (n >= 1 and ix == _NPIO2_HW[n - 1]):
        j = ix >> 20
        if j - _exponent(y0) > 16:
            tt = r
            w2 = fnv * _PIO2_2
            r = tt - w2
            w = _fma(fnv, _PIO2_2T, w2 - (tt - r))
            y0 = r - w
            if j - _exponent(y0) > 49:
                tt = r
                w3 = fnv * _PIO2_3
                r = tt - w3
                w = _fma(fnv, _PIO2_3T, w3 - (tt - r))
                y0 = r - w
    y1 = (r - y0) - w
    if x > 0.0:
        return (n, y0, y1)
    return (-n, -y0, -y1)


def _aarch64_sin_cos(x: float, is_cos: bool) -> float:
    ix = hi(x) & 0x7FFF_FFFF
    if ix < 0x3E400000:
        return 1.0 if is_cos else x
    if ix <= 0x3FE921FB:
        return _kernel_cos(x, 0.0, ix) if is_cos else _kernel_sin(x, 0.0, False)
    if ix >= 0x7FF00000:
        return f64_from_bits(0x7FF0_0000_0000_0001)
    res = _rem_pio2(x, ix)
    if res is None:
        return _platform_cos(x) if is_cos else _platform_sin(x)
    n, y0, y1 = res
    if ((n & 1) == 1) != is_cos:
        value = _kernel_cos(y0, y1, ix)
    else:
        value = _kernel_sin(y0, y1, True)
    negate = ((n ^ (n >> 1)) & 1) if is_cos else (n & 2)
    return -value if negate != 0 else value


class aarch64:
    """Rust `mod aarch64` — заглушки HotSpot для Apple silicon."""

    sin = staticmethod(lambda x: _aarch64_sin_cos(x, False))
    cos = staticmethod(lambda x: _aarch64_sin_cos(x, True))


# ── `exact`: sin/cos, правильно округлённые (ветка Windows) ──────────────
class _Dd:
    """Значение `hi + lo`, |lo| <= ulp(hi)/2."""

    __slots__ = ("hi", "lo")

    def __init__(self, hi: float, lo: float):
        self.hi = hi
        self.lo = lo

    def add(self, b: "_Dd") -> "_Dd":
        s = _two_sum(self.hi, b.hi)
        t = _two_sum(self.lo, b.lo)
        s = _fast_two_sum(s.hi, s.lo + t.hi)
        return _fast_two_sum(s.hi, s.lo + t.lo)

    def mul(self, b: "_Dd") -> "_Dd":
        p = _two_prod(self.hi, b.hi)
        return _fast_two_sum(p.hi, p.lo + (self.hi * b.lo + self.lo * b.hi))

    def div(self, d: float) -> "_Dd":
        q = self.hi / d
        p = _two_prod(q, d)
        r = ((self.hi - p.hi) - p.lo + self.lo) / d
        return _fast_two_sum(q, r)

    def neg(self) -> "_Dd":
        return _Dd(-self.hi, -self.lo)


def _two_sum(a: float, b: float) -> _Dd:
    s = a + b
    v = s - a
    return _Dd(s, (a - (s - v)) + (b - v))


def _fast_two_sum(a: float, b: float) -> _Dd:
    s = a + b
    return _Dd(s, b - (s - a))


def _two_prod(a: float, b: float) -> _Dd:
    def split(v: float):
        t = 134_217_729.0 * v  # 2^27 + 1
        h = t - (t - v)
        return h, v - h

    p = a * b
    ah, al = split(a)
    bh, bl = split(b)
    return _Dd(p, ((ah * bh - p) + ah * bl + al * bh) + al * bl)


_P1 = f64_from_bits(0x3FF9_21FB_5440_0000)
_P2 = f64_from_bits(0x3DD0_B461_1A60_0000)
_P3 = f64_from_bits(0x3BA3_198A_2E00_0000)
_P4 = f64_from_bits(0x397B_839A_2520_49C1)
_FRAC_2_PI = 2.0 / math.pi


def _exact_reduce(x: float):
    k = _round_half_away(x * _FRAC_2_PI)
    r = (
        _Dd(x - k * _P1, 0.0)
        .add(_Dd(-(k * _P2), 0.0))
        .add(_Dd(-(k * _P3), 0.0))
        .add(_two_prod(k, _P4).neg())
    )
    return r, int(k) & 3


def _exact_sum(xs) -> float:
    partials = [0.0] * 64
    length = 0
    for x0 in xs:
        x = x0
        i = 0
        for j in range(length):
            y = partials[j]
            if abs(x) < abs(y):
                x, y = y, x
            h = x + y
            lo = y - (h - x)
            if lo != 0.0:
                partials[i] = lo
                i += 1
            x = h
        partials[i] = x
        length = i + 1
    if length == 0:
        return 0.0
    n = length - 1
    h = partials[n]
    lo = 0.0
    while n > 0:
        x = h
        n -= 1
        y = partials[n]
        h = x + y
        lo = y - (h - x)
        if lo != 0.0:
            break
    if n > 0 and ((lo < 0.0 and partials[n - 1] < 0.0) or (lo > 0.0 and partials[n - 1] > 0.0)):
        y = lo * 2.0
        x = h + y
        if y == x - h:
            h = x
    return h


_SIN_TAIL = [
    -1.0 / 5040.0,
    1.0 / 362880.0,
    -1.0 / 39916800.0,
    1.0 / 6227020800.0,
    -1.0 / 1307674368000.0,
    1.0 / 355687428096000.0,
    -1.0 / 121645100408832000.0,
    1.0 / 51090942171709440000.0,
    -1.0 / 25852016738884976640000.0,
]
_COS_TAIL = [
    1.0 / 40320.0,
    -1.0 / 3628800.0,
    1.0 / 479001600.0,
    -1.0 / 87178291200.0,
    1.0 / 20922789888000.0,
    -1.0 / 6402373705728000.0,
    1.0 / 2432902008176640000.0,
    -1.0 / 1124000727777607680000.0,
]


def _horner(c, x: float) -> float:
    acc = 0.0
    for k in reversed(c):
        acc = acc * x + k
    return acc


def _exact_fast(r: _Dd, cos: bool) -> _Dd:
    r2 = r.mul(r)
    x2 = r2.hi
    if cos:
        t2 = r2.div(2.0).neg()
        t4 = r2.mul(r2).div(24.0)
        t6 = t4.mul(r2).div(30.0).neg()
        tail = x2 * x2 * x2 * x2 * _horner(_COS_TAIL, x2)
        return _Dd(1.0, 0.0).add(t2).add(t4).add(t6).add(_Dd(tail, 0.0))
    t3 = r2.mul(r).div(6.0).neg()
    t5 = t3.mul(r2).div(20.0).neg()
    tail = r.hi * x2 * x2 * x2 * _horner(_SIN_TAIL, x2)
    return r.add(t3).add(t5).add(_Dd(tail, 0.0))


def _exact_rounded(v: _Dd):
    e = abs(v.hi) * f64_from_bits(0x3C30_0000_0000_0000)  # 2^-60
    a = v.hi + (v.lo - e)
    b = v.hi + (v.lo + e)
    return a if a == b else None


def _exact_series(r: _Dd, cos: bool) -> float:
    r2 = r.mul(r)
    parts = [0.0] * 32
    length = 0
    if cos:
        term = _Dd(1.0, 0.0)
        first = 1.0
    else:
        term = r
        first = 2.0
    parts[0] = term.hi
    parts[1] = term.lo
    length += 2
    for n in range(1, 15):
        k = 2.0 * float(n) + first - 1.0
        term = term.mul(r2).div(k * (k - 1.0)).neg()
        parts[length] = term.hi
        parts[length + 1] = term.lo
        length += 2
    return _exact_sum(parts[:length])


def _exact_eval(r: _Dd, q: int, cos: bool) -> float:
    q = (q + (1 if cos else 0)) & 3
    want_cos = (q & 1) == 1
    v = _exact_rounded(_exact_fast(r, want_cos))
    if v is None:
        v = _exact_series(r, want_cos)
    return -v if q >= 2 else v


def _exact_sin(x: float) -> float:
    if abs(x) < f64_from_bits(0x3E40_0000_0000_0000):
        return x
    if x != x or abs(x) > 1_048_576.0:
        return _platform_sin(x)
    r, q = _exact_reduce(x)
    return _exact_eval(r, q, False)


def _exact_cos(x: float) -> float:
    if abs(x) < f64_from_bits(0x3E40_0000_0000_0000):
        return 1.0
    if x != x or abs(x) > 1_048_576.0:
        return _platform_cos(x)
    r, q = _exact_reduce(x)
    return _exact_eval(r, q, True)


class exact:
    """Rust `mod exact` — правильно округлённые sin/cos для Windows."""

    sin = staticmethod(_exact_sin)
    cos = staticmethod(_exact_cos)


# ── Публичные `Math.sin` / `Math.cos` / `Math.atan2` / `Math.hypot` ──────
def sin(x: float) -> float:
    """`Math.sin` (ветка Windows: `exact`)."""
    return _exact_sin(x)


def cos(x: float) -> float:
    """`Math.cos` (ветка Windows: `exact`)."""
    return _exact_cos(x)


def atan2(y: float, x: float) -> float:
    """`Math.atan2` (fdlibm)."""
    return _fdlibm_atan2(y, x)


def hypot(x: float, y: float) -> float:
    """`Math.hypot` (fdlibm)."""
    return _fdlibm_hypot(x, y)


# ── Java Math helpers (семантика java.lang.Math) ─────────────────────────
def floor(x: float) -> float:
    """`Math.floor(double)` — возвращает double, NaN/∞ без изменений."""
    if x != x or math.isinf(x):
        return x
    return float(math.floor(x))


def ceil(x: float) -> float:
    """`Math.ceil(double)` — возвращает double, NaN/∞ без изменений."""
    if x != x or math.isinf(x):
        return x
    return float(math.ceil(x))


def sqrt(x: float) -> float:
    """`Math.sqrt`: sqrt(-1) → NaN (не исключение)."""
    return _sqrt(x)


def signum(x: float) -> float:
    """`Math.signum`: NaN → NaN, ±0.0 сохраняет знак."""
    if x != x:
        return x
    if x == 0.0:
        return x
    return 1.0 if x > 0.0 else -1.0


def java_min(a: float, b: float) -> float:
    """`Math.min(double, double)`: NaN пробрасывается, -0.0 < 0.0."""
    if a != a:
        return a
    if a == 0.0 and b == 0.0 and f64_bits(b) == 0x8000_0000_0000_0000:
        return b
    return a if a <= b else b


def java_max(a: float, b: float) -> float:
    """`Math.max(double, double)`: NaN пробрасывается, +0.0 > -0.0."""
    if a != a:
        return a
    if a == 0.0 and b == 0.0 and f64_bits(a) == 0x8000_0000_0000_0000:
        return b
    return a if a >= b else b


def clamp(value: float, lo: float, hi: float) -> float:
    """`Math.clamp`: lo <= value <= hi (NaN остаётся NaN)."""
    if lo > hi:
        raise ValueError("min > max")
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def floor_div(a: int, b: int) -> int:
    """`Math.floorDiv(int, int)`: -7 / 3 → -3 (не -2)."""
    if b == 0:
        raise ZeroDivisionError("integer division by zero")
    # Python `//` уже округляет к -∞, как Java floorDiv.
    return a // b


def floor_mod(a: int, b: int) -> int:
    """`Math.floorMod(int, int)`: -7 % 3 → 2 (не -1)."""
    if b == 0:
        raise ZeroDivisionError("integer modulo by zero")
    return a - (a // b) * b


def to_radians(angdeg: float) -> float:
    """`Math.toRadians`: `angdeg / 180.0 * PI`."""
    return angdeg / 180.0 * math.pi


def to_degrees(angrad: float) -> float:
    """`Math.toDegrees`: `angrad * 180.0 / PI`."""
    return angrad * 180.0 / math.pi


def next_after(start: float, direction: float) -> float:
    """`Math.nextAfter`. Python 3.9+ `math.nextafter`."""
    return math.nextafter(start, direction)


def copy_sign(magnitude: float, sign: float) -> float:
    """`Math.copySign`."""
    return math.copysign(magnitude, sign)


# ── Integer / Long ───────────────────────────────────────────────────────
def number_of_leading_zeros(i: int) -> int:
    """`Integer.numberOfLeadingZeros`: n = i как 32-битное дополнение."""
    n = i & 0xFFFF_FFFF
    return 32 if n == 0 else 32 - n.bit_length()


def number_of_leading_zeros_long(i: int) -> int:
    """`Long.numberOfLeadingZeros`."""
    n = i & MASK64
    return 64 if n == 0 else 64 - n.bit_length()


def bit_count(i: int) -> int:
    """`Integer.bitCount`."""
    return bin(i & 0xFFFF_FFFF).count("1")


def bit_count_long(i: int) -> int:
    """`Long.bitCount`."""
    return bin(i & MASK64).count("1")


def highest_one_bit(i: int) -> int:
    """`Integer.highestOneBit`: 0 → 0, для отрицательных → Integer.MIN_VALUE."""
    n = i & 0xFFFF_FFFF
    if n == 0:
        return 0
    v = 1 << (n.bit_length() - 1)
    return _signed32(v)


def lowest_one_bit(i: int) -> int:
    """`Integer.lowestOneBit`: 0 → 0."""
    n = i & 0xFFFF_FFFF
    if n == 0:
        return 0
    return _signed32(n & -n & 0xFFFF_FFFF)


# ── Float / Double ───────────────────────────────────────────────────────
def is_nan(x: float) -> bool:
    """`Float.isNaN` / `Double.isNaN`."""
    return x != x


def is_infinite(x: float) -> bool:
    """`Float.isInfinite` / `Double.isInfinite`."""
    return math.isinf(x)


def float_to_int_bits(x: float) -> int:
    """`Float.floatToIntBits`: NaN канонизируется в 0x7fc00000."""
    b = f32_bits(x)
    if (b & 0x7F80_0000) == 0x7F80_0000 and (b & 0x007F_FFFF) != 0:
        b = 0x7FC0_0000
    return _signed32(b)


def int_bits_to_float(i: int) -> float:
    """`Float.intBitsToFloat`."""
    return f32_from_bits(i)


def double_to_long_bits(x: float) -> int:
    """`Double.doubleToLongBits`: NaN канонизируется в 0x7ff8000000000000."""
    b = f64_bits(x)
    if (b & 0x7FF0_0000_0000_0000) == 0x7FF0_0000_0000_0000 and (b & 0x000F_FFFF_FFFF_FFFF) != 0:
        b = 0x7FF8_0000_0000_0000
    return _signed64(b)


def long_bits_to_double(i: int) -> float:
    """`Double.longBitsToDouble`."""
    return f64_from_bits(i)


# ── Таблица синусов vanilla (geometry/trig.rs) ───────────────────────────
SCALE = 10430.378350470453
QUARTER = 16384
_TABLE_SIZE = 65536


def _build_sine_table():
    # Формула 26.3: (i / SCALE).sin() as f32, без готового артефакта vanilla.
    return [_f32(math.sin(i / SCALE)) for i in range(_TABLE_SIZE)]


SIN_TABLE = _build_sine_table()


def sine_table():
    """Rust `trig::sine_table()`."""
    return SIN_TABLE


def trig_sin(angle: float) -> float:
    """`trig::sin`: табличный f32-синус, индекс как Java double-to-long."""
    return SIN_TABLE[_f64_to_i64_sat(angle * SCALE) & 0xFFFF]


def trig_cos(angle: float) -> float:
    """`trig::cos`: табличный f32-косинус (+квартал)."""
    return SIN_TABLE[(_f64_to_i64_sat(angle * SCALE + 16384.0)) & 0xFFFF]


_TRIG_ATAN2_TABLES = None


def _atan2_tables():
    global _TRIG_ATAN2_TABLES
    if _TRIG_ATAN2_TABLES is None:
        asin_t = []
        cos_t = []
        for i in range(257):
            a = _fdlibm_asin(float(i) / 256.0)
            # HotSpot x86-64 округляет Math.cos(entry 61) на 1 ulp выше.
            c = f64_from_bits(0x3FEF_140A_0A08_6AF1) if i == 61 else math.cos(a)
            asin_t.append(a)
            cos_t.append(c)
        _TRIG_ATAN2_TABLES = (asin_t, cos_t)
    return _TRIG_ATAN2_TABLES


def trig_atan2(y: float, x: float) -> float:
    """`trig::atan2` (= `Mth.atan2`): табличный арктангенс vanilla."""
    asin_t, cos_t = _atan2_tables()
    frac_bias = f64_from_bits(4_805_340_802_404_319_232)
    d2 = x * x + y * y
    if d2 != d2:
        return _NAN
    negative_y = y < 0.0
    if negative_y:
        y = -y
    negative_x = x < 0.0
    if negative_x:
        x = -x
    steep = y > x
    if steep:
        x, y = y, x
    # Mth.fastInvSqrt
    half = 0.5 * d2
    r = f64_from_bits((6_910_469_410_427_058_090 - (_signed64(f64_bits(d2)) >> 1)) & MASK64)
    r *= 1.5 - half * r * r
    x *= r
    y *= r
    yp = frac_bias + y
    index = f64_bits(yp) & 0xFFFF_FFFF
    s_phi = yp - frac_bias
    sd = y * cos_t[index] - x * s_phi
    theta = asin_t[index] + (6.0 + sd * sd) * sd * 0.16666666666666666
    if steep:
        theta = math.pi / 2.0 - theta
    if negative_x:
        theta = math.pi - theta
    if negative_y:
        theta = -theta
    return theta


# Короткие имена как в `java.lang.Math` (объявлены в конце, чтобы не
# перекрывать built-in во время определения модуля).
min = java_min
max = java_max
