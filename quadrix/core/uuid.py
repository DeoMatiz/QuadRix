# Порт horizon-client-core/src/uuid.rs → quadrix/core/uuid.py.
#
# Rust хранит UUID вандаловым «четыре-int» видом `[i32; 4]` (big-endian),
# а не парой знаковых long, и умеет только два действия:
#   * `uuid_text(u)`      — четыре int → каноническую строку 8-4-4-4-12;
#   * `uuid_from_text(s)` — строку (дефисы игнорируются) → четыре int.
#
# Эти две функции портированы точно как в Rust (имена, поведение на невалидном
# вводе → None). Поверх них добавлен класс `UUID` — удобная обёртка над
# `uuid.UUID` стандартной библиотеки (from_bytes/to_bytes/from_int/to_int/
# version/variant/from_str/to_str), при этом каноническим представлением
# остаётся вандалов вид из четырёх int. `uuid_text` согласован с
# `crypto.uuid_string` (u128 big-endian) из protocol.

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "UUID",
    "uuid_text",
    "uuid_from_text",
]

_MASK32 = 0xFFFFFFFF


def _to_i32(v: int) -> int:
    """`v as i32` в Rust: младшие 32 бита, знаковая интерпретация."""
    v &= _MASK32
    return v - 0x100000000 if v & 0x80000000 else v


def _from_i32(v: int) -> int:
    """`v as u32` в Rust: беззнаковые 32 бита."""
    return int(v) & _MASK32


def uuid_text(u: Tuple[int, int, int, int]) -> str:
    """`uuid_text` (uuid.rs:3): четыре int → строка 8-4-4-4-12.

    Каждый int печатается как 32-битный hex (`format!("{:08x}", *v as u32)`).
    """
    hexs = "".join(format(_from_i32(v), "08x") for v in u)
    return (
        f"{hexs[0:8]}-{hexs[8:12]}-{hexs[12:16]}-{hexs[16:20]}-{hexs[20:32]}"
    )


def uuid_from_text(s: str) -> Optional[List[int]]:
    """`uuid_from_text` (uuid.rs:14): строка → четыре int или None.

    Обходит байты UTF-8: дефисы пропускаются, остальное обязано быть ascii-hex;
    ровно 32 hex-цифры, иначе None. Многобайтные символы (например `€`) — не
    hex и дают None.
    """
    hex_bytes = bytearray()
    for b in s.encode("utf-8"):
        if b == 0x2D:  # b'-'
            continue
        is_hex = (0x30 <= b <= 0x39) or (0x61 <= b <= 0x66) or (0x41 <= b <= 0x46)
        if not is_hex or len(hex_bytes) >= 32:
            return None
        hex_bytes.append(b)
    if len(hex_bytes) != 32:
        return None
    text = hex_bytes.decode("ascii")
    out: List[int] = []
    for i in range(4):
        out.append(_to_i32(int(text[i * 8:i * 8 + 8], 16)))
    return out


@dataclass(frozen=True)
class UUID:
    """UUID вандалов: четыре знаковых int (`[i32; 4]`, big-endian).

    Обёртка добавляет привычный API Python (`uuid.UUID`) поверх того же
    представления; `bytes`/`int` — 128-битные big-endian.
    """

    parts: Tuple[int, int, int, int]

    # ── создание ───────────────────────────────────────────────────────────
    @classmethod
    def from_parts(cls, parts) -> "UUID":
        """Из последовательности из четырёх int (как в Rust `[i32; 4]`)."""
        vals = list(parts)
        if len(vals) != 4:
            raise ValueError("UUID: нужно ровно четыре int")
        return cls((_to_i32(vals[0]), _to_i32(vals[1]),
                    _to_i32(vals[2]), _to_i32(vals[3])))

    @classmethod
    def from_bytes(cls, b: bytes) -> "UUID":
        """Из 16 байт big-endian."""
        raw = bytes(b)
        if len(raw) != 16:
            raise ValueError("UUID: нужно ровно 16 байт")
        parts = tuple(
            _to_i32(int.from_bytes(raw[i * 4:i * 4 + 4], "big")) for i in range(4)
        )
        return cls(parts)  # type: ignore[arg-type]

    @classmethod
    def from_int(cls, n: int) -> "UUID":
        """Из 128-битного целого (big-endian u128)."""
        return cls.from_bytes(int(n & ((1 << 128) - 1)).to_bytes(16, "big"))

    @classmethod
    def from_str(cls, s: str) -> "UUID":
        """`UUID.fromString`: строка (дефисы необязательны) → UUID.

        Невалидная строка → `ValueError` (в Rust — None).
        """
        parts = uuid_from_text(s)
        if parts is None:
            raise ValueError(f"некорректный UUID: {s!r}")
        return cls((parts[0], parts[1], parts[2], parts[3]))

    # ── преобразование ─────────────────────────────────────────────────────
    def to_bytes(self) -> bytes:
        """16 байт big-endian."""
        return b"".join(_from_i32(p).to_bytes(4, "big") for p in self.parts)

    def to_int(self) -> int:
        """128-битное целое (big-endian u128)."""
        return int.from_bytes(self.to_bytes(), "big")

    def to_str(self) -> str:
        """Каноническая строка 8-4-4-4-12."""
        return uuid_text(self.parts)

    def __str__(self) -> str:
        return self.to_str()

    # ── метаданные ─────────────────────────────────────────────────────────
    def version(self) -> Optional[int]:
        """Версия UUID (`uuid.UUID.version`); None, если вариант не RFC 4122."""
        return _uuid.UUID(bytes=self.to_bytes()).version

    def variant(self) -> str:
        """Вариант UUID (`uuid.UUID.variant`); RFC 4122 → `uuid.RFC_4122`."""
        return _uuid.UUID(bytes=self.to_bytes()).variant

    @property
    def msb(self) -> int:
        """Старшие 64 бита как знаковый long (Java `UUID.getMostSignificantBits`)."""
        raw = int.from_bytes(self.to_bytes()[0:8], "big")
        return raw - (1 << 64) if raw & (1 << 63) else raw

    @property
    def lsb(self) -> int:
        """Младшие 64 бита как знаковый long (Java `UUID.getLeastSignificantBits`)."""
        raw = int.from_bytes(self.to_bytes()[8:16], "big")
        return raw - (1 << 64) if raw & (1 << 63) else raw
