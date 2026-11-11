# Порт horizon-client-core/src/snbt.rs + horizon-world/src/snbt_text.rs +
# horizon-world/src/nbt.rs::parse_snbt (Minecraft 26.3).
#
# SNBT (stringified NBT): парсер строки `TagParser`/`Snbt` и писатель
# `StringTagVisitor` (`Tag.toString`), плюс форматирование чисел как в Java
# (`Double.toString`/`Float.toString`) и `StringTag.quoteAndEscape`.
#
# Компаунд в Rust — BTreeMap<JavaString, Tag>, поэтому ключи идут в порядке
# UTF-16 (как StringTagVisitor). В Python это обычный dict, так что писатель
# сортирует ключи по UTF-16 (big-endian байты = лексикографический порядок
# u16), а парсер сохраняет порядок файла.
#
# Tag переиспользуется из quadrix/world/nbt.py (TagType, Tag).

from __future__ import annotations

import math
import re
import struct
import sys
from typing import Any, Dict, List, Optional, Tuple

from quadrix.world.nbt import JavaString, Tag, TagType

__all__ = [
    "Tag",
    "TagType",
    "JavaString",
    "SnbtTag",
    "NbtTag",
    "parse",
    "parse_snbt",
    "to_snbt",
    "write_snbt",
    "quote_and_escape",
    "java_double",
    "java_float",
    "MAX_DEPTH",
]

# Синонимы: в задаче фигурируют под именами SnbtTag/NbtTag.
SnbtTag = Tag
NbtTag = Tag

# NbtAccounter предел: глубже — ошибка, а не переполнение стека.
MAX_DEPTH = 512


# ── Java-числа ───────────────────────────────────────────────────────────
def _shortest_f32(x: float) -> str:
    """Кратчайшая десятичная запись, однозначно дающая тот же f32 (как
    Rust `{}`/`{:e}` для f32)."""
    x32 = struct.unpack(">f", struct.pack(">f", x))[0]
    if x32 == 0.0:
        return "0"
    for p in range(1, 10):
        s = format(x32, ".{}g".format(p))
        if struct.unpack(">f", struct.pack(">f", float(s)))[0] == x32:
            return s
    return repr(x32)


def _decimal_parts(s: str) -> Tuple[str, int]:
    """Разобрать положительную десятичную запись в (значащие цифры, k), где
    значение = d1.d2d3... × 10^k."""
    s = s.lower()
    if "e" in s:
        mant, _, exp = s.partition("e")
        exponent = int(exp)
    else:
        mant, exponent = s, 0
    if "." in mant:
        intp, frac = mant.split(".")
    else:
        intp, frac = mant, ""
    combine = intp + frac
    scale = exponent - len(frac)
    trimmed = combine.lstrip("0")
    if trimmed == "":
        return "", 0
    trail = trimmed.rstrip("0")
    scale += len(trimmed) - len(trail)
    digits = trail
    k = scale + len(digits) - 1
    return digits, k


def _positional(digits: str, k: int) -> str:
    """Цифры + k → запись без экспоненты (как Rust Display)."""
    if k >= 0:
        if len(digits) <= k + 1:
            intp = digits + "0" * (k + 1 - len(digits))
            frac = ""
        else:
            intp = digits[: k + 1]
            frac = digits[k + 1:]
    else:
        intp = "0"
        frac = "0" * (-k - 1) + digits
    return intp + ("." + frac if frac else "")


def _round_1e_positive(a: float) -> str:
    """Rust `format!("{v:.1e}")`, без знака: "1.0e7" → "1.0E7"."""
    mant, _, exp = format(a, ".1e").partition("e")
    return mant + "E" + str(int(exp))


def _java_number(v: float, is_float: bool) -> str:
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    if v == 0.0:
        return "-0.0" if math.copysign(1.0, v) < 0 else "0.0"
    neg = math.copysign(1.0, v) < 0
    a = abs(v)
    shortest = _shortest_f32(a) if is_float else repr(a)
    digits, k = _decimal_parts(shortest)
    if 1.0e-3 <= a < 1.0e7:
        text = _positional(digits, k)
        if "." not in text:
            text += ".0"
    else:
        mant = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
        if "." in mant:
            text = mant + "E" + str(k)
        else:
            # Как Java: одноразрядную кратчайшую запись заменяют на f64 .1e.
            text = _round_1e_positive(a)
    return ("-" + text) if neg else text


def java_double(v: float) -> str:
    """`Double.toString`."""
    return _java_number(v, False)


def java_float(v: float) -> str:
    """`Float.toString` (v — значение f32, хранимое как Python float)."""
    return _java_number(v, True)


# ── экранирование строк ──────────────────────────────────────────────────
def _escape_control(c: str) -> Optional[str]:
    """`SnbtGrammar.escapeControlCharacters`."""
    return {
        "\b": "b",
        "\f": "f",
        "\n": "n",
        "\r": "r",
        "\t": "t",
    }.get(c)


def quote_and_escape(input: str) -> str:
    """`StringTag.quoteAndEscape`: выбрать кавычку и экранировать."""
    out: List[str] = [" "]  # место под кавычку
    quote = "\0"
    for c in input:
        if c == "\\":
            out.append("\\\\")
        elif c != '"' and c != "'":
            esc = _escape_control(c)
            if esc is not None:
                out.append("\\")
                out.append(esc)
            else:
                out.append(c)
        else:
            if quote == "\0":
                quote = "'" if c == '"' else '"'
            if quote == c:
                out.append("\\")
            out.append(c)
    if quote == "\0":
        quote = '"'
    out[0] = quote
    out.append(quote)
    return "".join(out)


def _utf16_key(s: str) -> bytes:
    """Ключ сортировки в порядке UTF-16 (big-endian байты = порядок u16)."""
    return s.encode("utf-16-be", "surrogatepass")


def _unquoted_key(key: str) -> bool:
    """`SnbtGrammar`: `[A-Za-z._]+[A-Za-z0-9._+-]*`, не true/false."""
    if key.lower() in ("true", "false") or key == "":
        return False
    first = key[0]
    if not (first.isascii() and (first.isalpha() or first in "._")):
        return False
    return all(
        (c.isascii() and c.isalnum()) or c in "._+-" for c in key[1:]
    )


# ── писатель ─────────────────────────────────────────────────────────────
def to_snbt(tag: Tag) -> str:
    """`Tag.toString` (StringTagVisitor): компактная строка SNBT."""
    old = sys.getrecursionlimit()
    if old < 4096:
        sys.setrecursionlimit(4096)
    try:
        return _visit(tag)
    finally:
        sys.setrecursionlimit(old)


write_snbt = to_snbt


def _visit(tag: Tag) -> str:
    tt = tag.tag_type
    if tt == TagType.End:
        return "END"
    if tt == TagType.Byte:
        return "{}b".format(tag.byte_val)
    if tt == TagType.Short:
        return "{}s".format(tag.short_val)
    if tt == TagType.Int:
        return "{}".format(tag.int_val)
    if tt == TagType.Long:
        return "{}L".format(tag.long_val)
    if tt == TagType.Float:
        return java_float(tag.float_val or 0.0) + "f"
    if tt == TagType.Double:
        return java_double(tag.double_val or 0.0) + "d"
    if tt == TagType.String:
        return quote_and_escape(tag.str_val or "")
    if tt == TagType.ByteArray:
        data = tag.bytes_val or b""
        body = ",".join("{}B".format(b if b < 128 else b - 256) for b in data)
        return "[B;" + body + "]"
    if tt == TagType.IntArray:
        return "[I;" + ",".join(str(v) for v in (tag.intarray_val or [])) + "]"
    if tt == TagType.LongArray:
        return "[L;" + ",".join("{}L".format(v) for v in (tag.longarray_val or [])) + "]"
    if tt == TagType.List:
        return "[" + ",".join(_visit(t) for t in (tag.list_val or [])) + "]"
    if tt == TagType.Compound:
        compound = tag.compound_val or {}
        parts: List[str] = []
        for key in sorted(compound, key=_utf16_key):
            k = key if _unquoted_key(key) else quote_and_escape(key)
            parts.append(k + ":" + _visit(compound[key]))
        return "{" + ",".join(parts) + "}"
    raise ValueError("неизвестный тип тега")


# ── парсер (TagParser / Snbt) ─────────────────────────────────────────────
_WS = " \t\n\x0c\r"  # Rust u8::is_ascii_whitespace
_INT_RE = re.compile(r"[+-]?\d+\Z")
_FLOAT_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\Z")


def _is_bare(c: str) -> bool:
    return (c.isascii() and c.isalnum()) or c in "_-+."


class _Snbt:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)
        self.depth = 0

    def _skip(self) -> None:
        while self.i < self.n and self.s[self.i] in _WS:
            self.i += 1

    def _peek(self) -> Optional[str]:
        self._skip()
        return self.s[self.i] if self.i < self.n else None

    def _expect(self, c: str) -> None:
        if self._peek() == c:
            self.i += 1
        else:
            raise ValueError("expected '{}' at {}".format(c, self.i))

    def string(self) -> str:
        q = self._peek()
        if q is not None and q in "\"'":
            self.i += 1
            out: List[str] = []
            while self.i < self.n:
                c = self.s[self.i]
                self.i += 1
                if c == "\\":
                    if self.i < self.n:
                        n = self.s[self.i]
                        self.i += 1
                        out.append({"n": "\n", "t": "\t"}.get(n, n))
                elif c == q:
                    return "".join(out)
                else:
                    out.append(c)
            raise ValueError("unterminated string")
        start = self.i
        while self.i < self.n and _is_bare(self.s[self.i]):
            self.i += 1
        if start == self.i:
            raise ValueError("expected a value at {}".format(start))
        return self.s[start:self.i]

    def value(self) -> Tag:
        c = self._peek()
        if c == "{":
            if self.depth >= MAX_DEPTH:
                raise ValueError("tag nesting too deep at {}".format(self.i))
            self.depth += 1
            tag = self.compound()
            self.depth -= 1
            return tag
        if c == "[":
            if self.depth >= MAX_DEPTH:
                raise ValueError("tag nesting too deep at {}".format(self.i))
            self.depth += 1
            tag = self.list()
            self.depth -= 1
            return tag
        if c is not None and c in "\"'":
            return Tag(TagType.String, str_val=self.string())
        word = self.string()
        return _scalar(word)

    def compound(self) -> Tag:
        self.i += 1  # '{'
        m: Dict[str, Tag] = {}
        if self._peek() == "}":
            self.i += 1
            return Tag(TagType.Compound, compound_val=m)
        while True:
            key = self.string()
            self._expect(":")
            m[key] = self.value()
            p = self._peek()
            if p == ",":
                self.i += 1
            elif p == "}":
                self.i += 1
                return Tag(TagType.Compound, compound_val=m)
            else:
                raise ValueError("expected ',' or '}}' at {}".format(self.i))

    def list(self) -> Tag:
        self.i += 1  # '['
        typed: Optional[str] = None
        if self.i < self.n and self.i + 1 < self.n \
                and self.s[self.i] in "BIL" and self.s[self.i + 1] == ";":
            typed = self.s[self.i]
            self.i += 2
        items: List[Tag] = []
        if self._peek() != "]":
            while True:
                items.append(self.value())
                p = self._peek()
                if p == ",":
                    self.i += 1
                elif p == "]":
                    break
                else:
                    raise ValueError("expected ',' or ']' at {}".format(self.i))
        self.i += 1  # ']'
        if typed == "B":
            return Tag(TagType.ByteArray, bytes_val=bytes(_long(t) & 0xFF for t in items))
        if typed == "I":
            return Tag(
                TagType.IntArray,
                intarray_val=[_to_i32(_long(t)) for t in items],
            )
        if typed == "L":
            return Tag(TagType.LongArray, longarray_val=[_long(t) for t in items])
        return Tag(TagType.List, list_val=items)


def _long(tag: Tag) -> int:
    """Замыкание `long` из Rust: числовые → i64, иначе 0."""
    tt = tag.tag_type
    if tt == TagType.Byte:
        return int(tag.byte_val or 0)
    if tt == TagType.Short:
        return int(tag.short_val or 0)
    if tt == TagType.Int:
        return int(tag.int_val or 0)
    if tt == TagType.Long:
        return int(tag.long_val or 0)
    return 0


def _to_i32(v: int) -> int:
    """`v as i32` в Rust: усечение до 32 бит со знаком."""
    return struct.unpack(">i", struct.pack(">I", v & 0xFFFFFFFF))[0]


def _to_f32(v: float) -> float:
    return struct.unpack(">f", struct.pack(">f", v))[0]


def _scalar(word: str) -> Tag:
    """Голое слово: типизированное число, булево или иначе строка."""
    if word == "true":
        return Tag(TagType.Byte, byte_val=1)
    if word == "false":
        return Tag(TagType.Byte, byte_val=0)
    lower = word.lower()
    if lower and lower[-1] in "bslfd":
        suffix: Optional[str] = lower[-1]
        body = word[:-1]
    else:
        suffix = None
        body = word
    # Только цифры (и экспонента) делают число: "nan"/"infd" — строки.
    if any(c.isalpha() and c not in "eE" for c in body):
        return Tag(TagType.String, str_val=word)
    if suffix in ("b", "s", "l"):
        if not _INT_RE.match(body):
            return Tag(TagType.String, str_val=word)
        value = int(body)
        if suffix == "b" and -128 <= value <= 127:
            return Tag(TagType.Byte, byte_val=value)
        if suffix == "s" and -32768 <= value <= 32767:
            return Tag(TagType.Short, short_val=value)
        if suffix == "l" and -(2 ** 63) <= value <= 2 ** 63 - 1:
            return Tag(TagType.Long, long_val=value)
        return Tag(TagType.String, str_val=word)
    if suffix in ("f", "d"):
        if not _FLOAT_RE.match(body):
            return Tag(TagType.String, str_val=word)
        if suffix == "f":
            return Tag(TagType.Float, float_val=_to_f32(float(body)))
        return Tag(TagType.Double, double_val=float(body))
    if "." in body or "e" in body or "E" in body:
        if not _FLOAT_RE.match(body):
            return Tag(TagType.String, str_val=word)
        return Tag(TagType.Double, double_val=float(body))
    if _INT_RE.match(body):
        value = int(body)
        if -(2 ** 31) <= value <= 2 ** 31 - 1:
            return Tag(TagType.Int, int_val=value)
    return Tag(TagType.String, str_val=word)


def parse_snbt(text: str) -> Tuple[Tag, int]:
    """`parse_snbt`: вернуть (тег, число прочитанных символов)."""
    old = sys.getrecursionlimit()
    if old < 4096:
        sys.setrecursionlimit(4096)
    try:
        parser = _Snbt(text)
        tag = parser.value()
        return tag, parser.i
    finally:
        sys.setrecursionlimit(old)


def parse(text: str) -> Tag:
    """Разобрать строку SNBT и вернуть `Tag`."""
    tag, _used = parse_snbt(text)
    return tag
