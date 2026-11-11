# !Порт horizon-core/src/random.rs (+ random/hash.rs, random/positional.rs,
# !random/worldgen.rs) — два seeded-потока vanilla и их позиционные фабрики.
# !
# !Никакой платформенный RNG не используется: последовательности повторяют
# !`java.util.Random` (48-битный LCG) и `Xoroshiro128++` из vanilla.
# !
# !Java-семантика сохранена точно:
# !  - `nextInt(bound)` — rejection sampling, а не modulo (modulo искажает
# !    распределение и не совпадает с vanilla);
# !  - 32-битные операции заворачиваются как i32, 64-битные — как i64;
# !  - порядок вызовов nextDouble в MarsagliaPolarGaussian важен.
# !
# !Не портировано здесь (следующие файлы): noise, density, paletted.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

from quadrix.core.jmath import log as _java_log

__all__ = [
    "InvalidBound",
    "RandomSource",
    "LegacyRandom",
    "XoroshiroRandom",
    "marsaglia_polar",
    "mix_stafford13",
    "seed_from_hash",
    "seed_from_hash_utf16",
    "PositionalRandom",
    "LegacyPositionalRandom",
    "XoroshiroPositionalRandom",
    "java_string_hash",
    "position_seed",
    "WorldgenSource",
    "WorldgenRandom",
    "WorldgenPositional",
    "slime_chunk_random",
    "MULTIPLIER",
    "ADDEND",
    "MASK",
    "GOLDEN_RATIO",
    "SILVER_RATIO",
]

# ── 64-битные маски и преобразования знака ───────────────────────────────
MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_SIGN64 = 0x8000_0000_0000_0000
_U32 = 0xFFFF_FFFF
_SIGN32 = 0x8000_0000

# LegacyRandom (java.util.Random)
MULTIPLIER = 0x5_DEEC_E66D
ADDEND = 0xB
MASK = (1 << 48) - 1

# XoroshiroRandom
GOLDEN_RATIO = 0x9E37_79B9_7F4A_7C15
SILVER_RATIO = 0x6A09_E667_F3BC_C909


def _as_i32(value: int) -> int:
    """Обрезать до 32 бит и вернуть как знаковое (Rust `as i32`)."""
    value &= _U32
    return value - 0x1_0000_0000 if value >= _SIGN32 else value


def _as_u32(value: int) -> int:
    return value & _U32


def _as_i64(value: int) -> int:
    """Обрезать до 64 бит и вернуть как знаковое (Rust `as i64`)."""
    value &= MASK64
    return value - 0x1_0000_0000_0000_0000 if value >= _SIGN64 else value


def _as_u64(value: int) -> int:
    return value & MASK64


def _rotl64(value: int, count: int) -> int:
    value &= MASK64
    count &= 63
    if count == 0:
        return value
    return ((value << count) | (value >> (64 - count))) & MASK64


class InvalidBound(Exception):
    """Rust `InvalidBound` — bound должен быть положительным."""

    def __init__(self, message: str = "bound must be positive") -> None:
        super().__init__(message)


class RandomSource:
    """Rust trait `RandomSource` — общие методы поверх базового потока.

    Ядро (`next_int`, `next_long`, ...) реализуют наследники; здесь только
    default-методы трейта, чтобы имена и семантика совпадали с Rust.
    """

    def consume_count(self, count: int) -> None:
        for _ in range(count):
            self.next_int()

    def next_int_between_inclusive(self, min_: int, max_: int) -> int:
        bound = _as_i32(_as_i32(max_ - min_) + 1)
        return _as_i32(self.next_int_bound(bound) + min_)

    def next_int_between(self, origin: int, bound: int) -> int:
        if origin >= bound:
            raise InvalidBound()
        return _as_i32(self.next_int_bound(_as_i32(bound - origin)) + origin)

    def triangle(self, mean: float, deviation: float) -> float:
        return mean + deviation * (self.next_double() - self.next_double())

    def triangle_float(self, mean: float, deviation: float) -> float:
        return mean + deviation * (self.next_float() - self.next_float())


# ── MarsagliaPolarGaussian ───────────────────────────────────────────────
def marsaglia_polar(cache: list, next_double) -> float:
    """`MarsagliaPolarGaussian.nextGaussian` с внешним кэшем второго значения.

    `cache` — список длины 1 (аналог `&mut Option<f64>`): cache[0] это либо
    None, либо готовое второе значение.
    """
    if cache[0] is not None:
        value = cache[0]
        cache[0] = None
        return value
    while True:
        x = 2.0 * next_double() - 1.0
        y = 2.0 * next_double() - 1.0
        radius = x * x + y * y
        if radius >= 1.0 or radius == 0.0:
            continue
        multiplier = math.sqrt(-2.0 * _java_log(radius) / radius)
        cache[0] = y * multiplier
        return x * multiplier


# ── LegacyRandom: java.util.Random ──────────────────────────────────────
class LegacyRandom(RandomSource):
    """48-битный LCG Java: state = state * MULTIPLIER + ADDEND (mod 2^48)."""

    __slots__ = ("state", "gaussian")

    def __init__(self, seed: int) -> None:
        self.state = (_as_u64(seed) ^ MULTIPLIER) & MASK
        self.gaussian: Optional[float] = None

    @classmethod
    def from_state(cls, state: int) -> "LegacyRandom":
        """Собрать из уже замаскированного 48-битного состояния."""
        obj = cls.__new__(cls)
        obj.state = state & MASK
        obj.gaussian = None
        return obj

    def state_value(self) -> int:
        """48-битное состояние (дифференциальные тесты сравнивают его)."""
        return self.state

    def bits(self, count: int) -> int:
        self.state = (self.state * MULTIPLIER + ADDEND) & MASK
        return _as_i32(self.state >> (48 - count))

    # ── RandomSource ──
    def set_seed(self, seed: int) -> None:
        self.state = (_as_u64(seed) ^ MULTIPLIER) & MASK
        self.gaussian = None

    def next_int(self) -> int:
        return self.bits(32)

    def next_int_bound(self, bound: int) -> int:
        if bound <= 0:
            raise InvalidBound()
        # Степень двойки: Java берёт старшие биты без rejection.
        if bound & (bound - 1) == 0:
            return _as_i32((bound * self.bits(31)) >> 31)
        while True:
            bits = self.bits(31)
            value = bits % bound
            # Знаковое переполнение i32 — часть правила rejection.
            if _as_i32(bits - value + (bound - 1)) >= 0:
                return value

    def next_long(self) -> int:
        high = _as_i64(self.bits(32) << 32)
        # Java расширяет знак младшего int перед сложением.
        return _as_i64(high + self.bits(32))

    def next_boolean(self) -> bool:
        return self.bits(1) != 0

    def next_float(self) -> float:
        # f32 * (1 / 2^24) — обе величины точны, поэтому обычный float верен.
        return self.bits(24) * (1.0 / 16_777_216.0)

    def next_double(self) -> float:
        value = (self.bits(26) << 27) + self.bits(27)
        return value * (1.0 / 9_007_199_254_740_992.0)

    def next_gaussian(self) -> float:
        cache = [self.gaussian]
        value = marsaglia_polar(cache, self.next_double)
        self.gaussian = cache[0]
        return value

    def fork(self) -> "LegacyRandom":
        return LegacyRandom(self.next_long())

    def fork_positional(self) -> "LegacyPositionalRandom":
        return LegacyPositionalRandom(self.next_long())

    # ── WorldgenSource: сырые биты без Java-обёртки ──
    def worldgen_bits(self, count: int) -> int:
        self.state = (self.state * MULTIPLIER + ADDEND) & MASK
        return _as_i32(self.state >> (48 - count))


# ── XoroshiroRandom: Xoroshiro128++ ─────────────────────────────────────
class XoroshiroRandom(RandomSource):
    """Xoroshiro128++ в той же форме, что и vanilla."""

    __slots__ = ("lo", "hi", "gaussian")

    def __init__(self, seed: int) -> None:
        lo = _as_u64(seed) ^ SILVER_RATIO
        self.lo = mix_stafford13(lo)
        self.hi = mix_stafford13(_as_u64(lo + GOLDEN_RATIO))
        self.gaussian = None

    @classmethod
    def from_state(cls, lo: int, hi: int) -> "XoroshiroRandom":
        obj = cls.__new__(cls)
        if (lo | hi) == 0:
            obj.lo = GOLDEN_RATIO
            obj.hi = SILVER_RATIO
        else:
            obj.lo = _as_u64(lo)
            obj.hi = _as_u64(hi)
        obj.gaussian = None
        return obj

    def state_words(self) -> tuple:
        """Оба слова состояния (`Xoroshiro128PlusPlus.CODEC`)."""
        return (self.lo, self.hi)

    # ── RandomSource ──
    def set_seed(self, seed: int) -> None:
        fresh = XoroshiroRandom(seed)
        self.lo = fresh.lo
        self.hi = fresh.hi
        self.gaussian = None

    def next_int(self) -> int:
        return _as_i32(self.next_long())

    def next_int_bound(self, bound: int) -> int:
        if bound <= 0:
            raise InvalidBound()
        bound_u = _as_u32(bound)
        threshold = _as_u32(-bound_u) % bound_u
        while True:
            product = _as_u32(self.next_int()) * bound_u
            if _as_u32(product) >= threshold:
                return _as_i32(product >> 32)

    def next_long(self) -> int:
        lo = self.lo
        hi = self.hi ^ lo
        result = _as_u64(_rotl64(_as_u64(lo + self.hi), 17) + lo)
        self.lo = _as_u64(_rotl64(lo, 49) ^ hi ^ ((hi << 21) & MASK64))
        self.hi = _rotl64(hi, 28)
        return _as_i64(result)

    def next_boolean(self) -> bool:
        return (self.next_long() & 1) != 0

    def next_float(self) -> float:
        return (_as_u64(self.next_long()) >> 40) * (1.0 / 16_777_216.0)

    def next_double(self) -> float:
        return (_as_u64(self.next_long()) >> 11) * (1.0 / 9_007_199_254_740_992.0)

    def next_gaussian(self) -> float:
        cache = [self.gaussian]
        value = marsaglia_polar(cache, self.next_double)
        self.gaussian = cache[0]
        return value

    def fork(self) -> "XoroshiroRandom":
        lo = _as_u64(self.next_long())
        hi = _as_u64(self.next_long())
        return XoroshiroRandom.from_state(lo, hi)

    def fork_positional(self) -> "XoroshiroPositionalRandom":
        lo = _as_u64(self.next_long())
        hi = _as_u64(self.next_long())
        return XoroshiroPositionalRandom(lo, hi)

    # ── WorldgenSource ──
    def worldgen_bits(self, count: int) -> int:
        return _as_i32(_as_u64(self.next_long()) >> (64 - count))


# ── Stafford mix13 ───────────────────────────────────────────────────────
def mix_stafford13(value: int) -> int:
    value = _as_u64((value ^ (value >> 30)) * 0xBF58_476D_1CE4_E5B9)
    value = _as_u64((value ^ (value >> 27)) * 0x94D0_49BB_1331_11EB)
    return _as_u64(value ^ (value >> 31))


# ── MD5: детерминированные seed'ы из имён ───────────────────────────────
_K = (
    0xD76AA478, 0xE8C7B756, 0x242070DB, 0xC1BDCEEE,
    0xF57C0FAF, 0x4787C62A, 0xA8304613, 0xFD469501,
    0x698098D8, 0x8B44F7AF, 0xFFFF5BB1, 0x895CD7BE,
    0x6B901122, 0xFD987193, 0xA679438E, 0x49B40821,
    0xF61E2562, 0xC040B340, 0x265E5A51, 0xE9B6C7AA,
    0xD62F105D, 0x02441453, 0xD8A1E681, 0xE7D3FBC8,
    0x21E1CDE6, 0xC33707D6, 0xF4D50D87, 0x455A14ED,
    0xA9E3E905, 0xFCEFA3F8, 0x676F02D9, 0x8D2A4C8A,
    0xFFFA3942, 0x8771F681, 0x6D9D6122, 0xFDE5380C,
    0xA4BEEA44, 0x4BDECFA9, 0xF6BB4B60, 0xBEBFBC70,
    0x289B7EC6, 0xEAA127FA, 0xD4EF3085, 0x04881D05,
    0xD9D4D039, 0xE6DB99E5, 0x1FA27CF8, 0xC4AC5665,
    0xF4292244, 0x432AFF97, 0xAB9423A7, 0xFC93A039,
    0x655B59C3, 0x8F0CCC92, 0xFFEFF47D, 0x85845DD1,
    0x6FA87E4F, 0xFE2CE6E0, 0xA3014314, 0x4E0811A1,
    0xF7537E82, 0xBD3AF235, 0x2AD7D2BB, 0xEB86D391,
)
_SHIFT = (
    (7, 12, 17, 22),
    (5, 9, 14, 20),
    (4, 11, 16, 23),
    (6, 10, 15, 21),
)


class _Md5:
    """Оригинальный MD5 (RFC 1321) — внутренний seed-преобразователь."""

    __slots__ = ("state", "buffer", "used", "bytes")

    def __init__(self) -> None:
        self.state = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476]
        self.buffer = bytearray(64)
        self.used = 0
        self.bytes = 0

    def block(self, block: bytes) -> None:
        words = [
            int.from_bytes(block[i * 4 : i * 4 + 4], "little") for i in range(16)
        ]
        a, b, c, d = self.state
        for i, constant in enumerate(_K):
            group = i // 16
            if group == 0:
                mix = (b & c) | ((~b & _U32) & d)
                index = i
            elif group == 1:
                mix = (d & b) | ((~d & _U32) & c)
                index = (5 * i + 1) % 16
            elif group == 2:
                mix = b ^ c ^ d
                index = (3 * i + 5) % 16
            else:
                mix = c ^ (b | ((~d) & _U32))
                index = (7 * i) % 16
            summed = (a + mix + constant + words[index]) & _U32
            rotate = _SHIFT[group][i % 4]
            rotated = ((summed << rotate) | (summed >> (32 - rotate))) & _U32
            nxt = (b + rotated) & _U32
            a, b, c, d = d, nxt, b, c
        self.state = [
            (old + value) & _U32 for old, value in zip(self.state, (a, b, c, d))
        ]

    def update(self, data: bytes) -> None:
        self.bytes = (self.bytes + len(data)) & MASK64
        if self.used != 0:
            count = min(64 - self.used, len(data))
            self.buffer[self.used : self.used + count] = data[:count]
            self.used += count
            data = data[count:]
            if self.used != 64:
                return
            self.block(bytes(self.buffer))
            self.used = 0
        while len(data) >= 64:
            self.block(data[:64])
            data = data[64:]
        self.buffer[: len(data)] = data
        self.used = len(data)

    def finish(self) -> bytes:
        length = ((self.bytes * 8) & MASK64).to_bytes(8, "little")
        count = 56 - self.used if self.used < 56 else 120 - self.used
        padding = bytearray(64)
        padding[0] = 0x80
        self.update(bytes(padding[:count]))
        self.update(length)
        digest = bytearray(16)
        for i in range(16):
            digest[i] = (self.state[i // 4] >> (8 * (i % 4))) & 0xFF
        return bytes(digest)


def _seed(digest: bytes) -> list:
    return [
        int.from_bytes(digest[:8], "big"),
        int.from_bytes(digest[8:], "big"),
    ]


def _decode_utf16(units: Iterable[int]) -> str:
    """Rust `char::decode_utf16`: одиночный суррогат заменяется на '?'."""
    units = list(units)
    out = []
    i = 0
    n = len(units)
    while i < n:
        unit = units[i]
        if (
            0xD800 <= unit <= 0xDBFF
            and i + 1 < n
            and 0xDC00 <= units[i + 1] <= 0xDFFF
        ):
            out.append(chr(0x10000 + ((unit - 0xD800) << 10) + (units[i + 1] - 0xDC00)))
            i += 2
        elif 0xD800 <= unit <= 0xDFFF:
            out.append("?")
            i += 1
        else:
            out.append(chr(unit))
            i += 1
    return "".join(out)


def seed_from_hash(name: str) -> list:
    """Seed из имени: два u64 из MD5-дайджеста (big-endian половины)."""
    digest = _Md5()
    digest.update(name.encode("utf-8"))
    return _seed(digest.finish())


def seed_from_hash_utf16(name: Iterable[int]) -> list:
    """Seed из UTF-16 units; одиночные суррогаты Java кодирует как '?'."""
    digest = _Md5()
    digest.update(_decode_utf16(name).encode("utf-8", "replace"))
    return _seed(digest.finish())


# ── Позиционные фабрики ─────────────────────────────────────────────────
class PositionalRandom:
    """Rust trait `PositionalRandom` — фабрика потоков по позиции/имени."""

    def at(self, position):  # pragma: no cover - переопределяют наследники
        raise AttributeError("at")

    def from_seed(self, seed: int):  # pragma: no cover
        raise AttributeError("from_seed")

    def from_hash_of(self, name: str):  # pragma: no cover
        raise AttributeError("from_hash_of")

    def from_hash_of_utf16(self, name):  # pragma: no cover
        raise AttributeError("from_hash_of_utf16")


@dataclass(frozen=True)
class LegacyPositionalRandom(PositionalRandom):
    """`LegacyPositionalRandom`: base = (seed ^ MULTIPLIER) & MASK."""

    seed: int
    base: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", (_as_u64(self.seed) ^ MULTIPLIER) & MASK)

    def at(self, position) -> LegacyRandom:
        p = _as_u64(position_seed(position)) & MASK
        return LegacyRandom.from_state(p ^ self.base)

    def from_seed(self, seed: int) -> LegacyRandom:
        return LegacyRandom(seed)

    def from_hash_of(self, name: str) -> LegacyRandom:
        h = _as_u64(_as_i64(java_string_hash(_utf16_units(name)))) & MASK
        return LegacyRandom.from_state(h ^ self.base)

    def from_hash_of_utf16(self, name) -> LegacyRandom:
        h = _as_u64(_as_i64(java_string_hash(name))) & MASK
        return LegacyRandom.from_state(h ^ self.base)


@dataclass(frozen=True)
class XoroshiroPositionalRandom(PositionalRandom):
    lo: int
    hi: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "lo", _as_u64(self.lo))
        object.__setattr__(self, "hi", _as_u64(self.hi))

    def at(self, position) -> XoroshiroRandom:
        return XoroshiroRandom.from_state(_as_u64(position_seed(position)) ^ self.lo, self.hi)

    def from_seed(self, seed: int) -> XoroshiroRandom:
        return XoroshiroRandom.from_state(_as_u64(seed) ^ self.lo, _as_u64(seed) ^ self.hi)

    def from_hash_of(self, name: str) -> XoroshiroRandom:
        lo, hi = seed_from_hash(name)
        return XoroshiroRandom.from_state(lo ^ self.lo, hi ^ self.hi)

    def from_hash_of_utf16(self, name) -> XoroshiroRandom:
        lo, hi = seed_from_hash_utf16(name)
        return XoroshiroRandom.from_state(lo ^ self.lo, hi ^ self.hi)


def _utf16_units(name: str) -> list:
    """Строка → UTF-16 units (как `name.encode_utf16()` в Rust)."""
    data = name.encode("utf-16-le", "surrogatepass")
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def java_string_hash(name: Iterable[int]) -> int:
    """`String.hashCode` по UTF-16 units (i32 wrapping)."""
    value = 0
    for unit in name:
        value = _as_i32(value * 31 + unit)
    return value


def position_seed(position) -> int:
    """`Mth.getSeed` — знаковая Java-арифметика, включая начальный int-продукт."""
    x = int(position.x)
    y = int(position.y)
    z = int(position.z)
    # x * 3129871 выполняется в i32 и расширяется знаком до i64.
    mixed = _as_i64(_as_i32(x * 3_129_871))
    mixed ^= _as_u64(z * 116_129_781)
    mixed = _as_i64(mixed ^ _as_u64(y))
    u = _as_u64(mixed)
    total = _as_u64(_as_u64(_as_u64(u * u) * 42_317_861) + _as_u64(u * 11))
    return _as_i64(total) >> 16


# ── WorldgenRandom: адаптер поверх любого WorldgenSource ────────────────
class WorldgenSource:
    """Rust trait `WorldgenSource` — сырые биты для worldgen-потока."""

    def worldgen_bits(self, count: int) -> int:  # pragma: no cover
        raise AttributeError("worldgen_bits")


class WorldgenRandom(RandomSource):
    """Legacy bit-sampling адаптер vanilla worldgen.

    `wrapped=True` (конструктор `new`) считает вызовы и берёт биты через
    `next_bits`; `plain` (внутренний, для fork'ов) делегирует источнику.
    """

    __slots__ = ("source", "count", "wrapped", "gaussian")

    def __init__(self, source) -> None:
        self.source = source
        self.count = 0
        self.wrapped = True
        self.gaussian: Optional[float] = None

    @classmethod
    def plain(cls, source) -> "WorldgenRandom":
        obj = cls.__new__(cls)
        obj.source = source
        obj.count = 0
        obj.wrapped = False
        obj.gaussian = None
        return obj

    def count_value(self) -> int:
        return self.count

    def next_bits(self, bits: int) -> int:
        if self.wrapped:
            self.count = _as_i32(self.count + 1)
        return self.source.worldgen_bits(bits)

    def set_decoration_seed(self, seed: int, x: int, z: int) -> int:
        self.set_seed(seed)
        a = self.next_long() | 1
        b = self.next_long() | 1
        mixed = _as_i64(
            _as_u64(x * a) + _as_u64(z * b)
        )
        mixed = _as_i64(mixed ^ _as_u64(seed))
        self.set_seed(mixed)
        return mixed

    def set_feature_seed(self, seed: int, index: int, step: int) -> None:
        self.set_seed(_as_i64(seed + index + _as_i32(step * 10000)))

    def set_large_feature_seed(self, seed: int, x: int, z: int) -> None:
        self.set_seed(seed)
        a = self.next_long()
        b = self.next_long()
        mixed = _as_i64(_as_u64(x * a) ^ _as_u64(z * b) ^ _as_u64(seed))
        self.set_seed(mixed)

    def set_large_feature_with_salt(self, seed: int, x: int, z: int, salt: int) -> None:
        total = (
            _as_u64(x * 341_873_128_712)
            + _as_u64(z * 132_897_987_541)
            + _as_u64(seed)
            + _as_u64(salt)
        )
        self.set_seed(_as_i64(total))

    # ── WorldgenSource ──
    def worldgen_bits(self, count: int) -> int:
        return self.next_bits(count)

    # ── RandomSource ──
    def set_seed(self, seed: int) -> None:
        # Adapter'ский gaussian-кэш native setSeed НЕ сбрасывает.
        self.source.set_seed(seed)

    def next_int(self) -> int:
        if self.wrapped:
            return self.next_bits(32)
        return self.source.next_int()

    def next_int_bound(self, bound: int) -> int:
        if not self.wrapped:
            return self.source.next_int_bound(bound)
        if bound <= 0:
            raise InvalidBound()
        if bound & (bound - 1) == 0:
            return _as_i32((bound * self.next_bits(31)) >> 31)
        while True:
            bits = self.next_bits(31)
            value = bits % bound
            if _as_i32(bits - value + (bound - 1)) >= 0:
                return value

    def next_long(self) -> int:
        if not self.wrapped:
            return self.source.next_long()
        high = _as_i64(self.next_bits(32) << 32)
        return _as_i64(high + self.next_bits(32))

    def next_boolean(self) -> bool:
        if self.wrapped:
            return self.next_bits(1) != 0
        return self.source.next_boolean()

    def next_float(self) -> float:
        if self.wrapped:
            return self.next_bits(24) * (1.0 / 16_777_216.0)
        return self.source.next_float()

    def next_double(self) -> float:
        if not self.wrapped:
            return self.source.next_double()
        bits = (self.next_bits(26) << 27) + self.next_bits(27)
        return bits * (1.0 / 9_007_199_254_740_992.0)

    def next_gaussian(self) -> float:
        if not self.wrapped:
            return self.source.next_gaussian()
        cache = [self.gaussian]
        value = marsaglia_polar(cache, self.next_double)
        self.gaussian = cache[0]
        return value

    def fork(self) -> "WorldgenRandom":
        # Native fork возвращает нижележащий источник, не другой адаптер.
        return WorldgenRandom.plain(self.source.fork())

    def fork_positional(self) -> "WorldgenPositional":
        return WorldgenPositional(self.source.fork_positional())


@dataclass(frozen=True)
class WorldgenPositional(PositionalRandom):
    inner: PositionalRandom

    def at(self, position) -> WorldgenRandom:
        return WorldgenRandom.plain(self.inner.at(position))

    def from_seed(self, seed: int) -> WorldgenRandom:
        return WorldgenRandom.plain(self.inner.from_seed(seed))

    def from_hash_of(self, name: str) -> WorldgenRandom:
        return WorldgenRandom.plain(self.inner.from_hash_of(name))

    def from_hash_of_utf16(self, name) -> WorldgenRandom:
        return WorldgenRandom.plain(self.inner.from_hash_of_utf16(name))


def slime_chunk_random(x: int, z: int, seed: int, salt: int) -> LegacyRandom:
    """`slime_chunk_random`: смешанный seed слime-чанка."""
    mixed = _as_u64(seed)
    mixed = _as_u64(mixed + _as_u64(_as_i32(_as_i32(x * x) * 4_987_142)))
    mixed = _as_u64(mixed + _as_u64(_as_i32(x * 5_947_611)))
    mixed = _as_u64(mixed + _as_u64(_as_i64(_as_i32(z * z)) * 4_392_871))
    mixed = _as_u64(mixed + _as_u64(_as_i32(z * 389_711)))
    mixed ^= _as_u64(salt)
    return LegacyRandom(_as_i64(mixed))
