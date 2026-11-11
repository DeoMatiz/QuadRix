# Порт horizon-client-core/src/nbt_path.rs (Minecraft 26.3).
#
# NBT-пути (`NbtPathArgument`): `foo.bar[0]`, `[]`, `list[{id:1}]`,
# `{root:match}` — с get/set/insert/remove по дереву тегов и частичным
# сравнением NBT (`NbtUtils.compareNbt`), которое используют селекторы и
# условия (`/execute if data`, `/data get|modify|remove`).
#
# Tag/TagType переиспользуются из quadrix/world/nbt.py. Компаунд в Rust —
# BTreeMap<JavaString, Tag>; в Python это dict с обычными str-ключами.
# В Rust Node — enum; здесь каждый вариант представлен dataclass'ом.
#
# ВАЖНО: синтаксис пути повторён как в Rust — wildcard это `[]`, а не `*`.
# Звёздочка `*` — обычный символ имени поля (Rust её не выделяет).

from __future__ import annotations

import copy
import math
import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from quadrix.core.snbt import parse_snbt, to_snbt
from quadrix.world.nbt import Tag, TagType

__all__ = [
    "PathError",
    "Node",
    "Child",
    "MatchChild",
    "AllElements",
    "Index",
    "MatchElement",
    "MatchRoot",
    "NbtPath",
    "CollectionError",
    "compare_nbt",
    "elements",
    "int_value",
    "too_deep",
    "get",
    "set",
    "remove",
]


# ── ошибка пути ──────────────────────────────────────────────────────────
class PathError(Exception):
    """Ошибка с ключом перевода и аргументами (как в Rust `PathError`).

    Поле `args` переопределено свойством, потому что у `Exception` уже есть
    атрибут `args` (кортеж), а нам нужен список строк перевода.
    """

    def __init__(self, key: str, args: Optional[List[str]] = None, cursor: int = 0) -> None:
        self.key = key
        self.cursor = cursor
        self._args: List[str] = list(args) if args else []

    @property
    def args(self) -> List[str]:  # type: ignore[override]
        return self._args

    @args.setter
    def args(self, value: List[str]) -> None:
        self._args = list(value) if value else []

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, PathError)
            and self.key == other.key
            and self._args == other._args
            and self.cursor == other.cursor
        )

    def __repr__(self) -> str:
        return "PathError(key={!r}, args={!r}, cursor={})".format(
            self.key, self._args, self.cursor
        )


# ── узлы пути (Rust enum Node) ───────────────────────────────────────────
@dataclass
class Node:
    """Базовый узел пути; конкретные варианты — ниже."""


@dataclass
class Child(Node):
    """`name`."""
    name: str


@dataclass
class MatchChild(Node):
    """`name{pattern}`."""
    name: str
    pattern: Tag


@dataclass
class AllElements(Node):
    """`[]`."""


@dataclass
class Index(Node):
    """`[n]`."""
    value: int


@dataclass
class MatchElement(Node):
    """`[{pattern}]`."""
    pattern: Tag


@dataclass
class MatchRoot(Node):
    """`{pattern}` в начале."""
    pattern: Tag


@dataclass
class NbtPath:
    """Разобранный NBT-путь. Поля как в Rust: original/nodes/ends."""

    original: str
    nodes: List[Node] = field(default_factory=list)
    # Байтовое смещение сразу после каждого узла в `original`.
    ends: List[int] = field(default_factory=list)

    # ── разбор ───────────────────────────────────────────────────────────
    @classmethod
    def parse_prefix(cls, text: str) -> Tuple["NbtPath", int]:
        """`NbtPathArgument.parse` от начала `text`; возвращает путь и число
        использованных символов (останавливается на пробеле)."""
        i = 0
        n = len(text)
        nodes: List[Node] = []
        ends: List[int] = []
        first = True
        while i < n and text[i] != " ":
            node, nxt = _parse_node(text, i, first)
            nodes.append(node)
            i = nxt
            ends.append(i)
            first = False
            if i < n and text[i] not in (" ", "[", "{"):
                if text[i] != ".":
                    raise PathError("parsing.expected", ["."], i)
                i += 1
        return cls(text[:i], nodes, ends), i

    @classmethod
    def parse(cls, text: str) -> "NbtPath":
        """`NbtPathArgument.parse`: разобрать путь целиком."""
        p, used = cls.parse_prefix(text)
        if used != len(text):
            raise PathError("arguments.nbtpath.node.invalid", [], used)
        return p

    def as_str(self) -> str:
        return self.original

    def to_string(self) -> str:
        """Исходный текст пути (аналог round-trip через `as_str`)."""
        return self.original

    def __str__(self) -> str:
        return self.original

    def is_empty(self) -> bool:
        return len(self.nodes) == 0

    def is_field_path(self, fields: List[str]) -> bool:
        """Является ли путь цепочкой полей компаунда (включая фильтры и
        кавычки). MatchRoot не потребляет поле."""
        it = iter(fields)
        for node in self.nodes:
            if isinstance(node, MatchRoot):
                continue
            if isinstance(node, (Child, MatchChild)):
                nxt = next(it, None)
                if nxt != node.name:
                    return False
            else:
                return False
        return next(it, None) is None

    def _not_found(self, node: int) -> PathError:
        end = self.ends[node]
        return PathError(
            "arguments.nbtpath.nothing_found",
            [self.original[: min(end, len(self.original))]],
            0,
        )

    # ── чтение ───────────────────────────────────────────────────────────
    @staticmethod
    def _step(node: Node, parent: Tag, out: List[Tag]) -> None:
        if isinstance(node, Child):
            if parent.is_compound:
                t = _get_child(parent, node.name)
                if t is not None:
                    out.append(t)
        elif isinstance(node, MatchChild):
            if parent.is_compound:
                t = _get_child(parent, node.name)
                if t is not None and compare_nbt(node.pattern, t):
                    out.append(t)
        elif isinstance(node, AllElements):
            if parent.is_list:
                out.extend(parent.list_val or [])
        elif isinstance(node, Index):
            if parent.is_list:
                lst = parent.list_val or []
                total = len(lst)
                idx = total + node.value if node.value < 0 else node.value
                if 0 <= idx < total:
                    out.append(lst[idx])
        elif isinstance(node, MatchElement):
            if parent.is_list:
                out.extend(
                    t for t in (parent.list_val or []) if compare_nbt(node.pattern, t)
                )
        elif isinstance(node, MatchRoot):
            if parent.is_compound and compare_nbt(node.pattern, parent):
                out.append(parent)

    def _read_steps(self, root: Tag) -> List[Tag]:
        """Массивные теги читаются как списки их элементов."""
        current: List[Tag] = [root]
        for i, node in enumerate(self.nodes):
            nxt: List[Tag] = []
            for parent in current:
                # Массивы отдают элементы узлам-элементам.
                p = parent
                if isinstance(node, (AllElements, Index)):
                    els = elements(parent)
                    if els is not None and not parent.is_list:
                        p = Tag(TagType.List, list_val=els)
                out: List[Tag] = []
                self._step(node, p, out)
                nxt.extend(out)
            if not nxt:
                raise self._not_found(i)
            current = nxt
        return [copy.deepcopy(t) for t in current]

    def get(self, root: Tag) -> List[Tag]:
        """`get`: все совпавшие теги (ошибка, если ничего не совпало)."""
        return self._read_steps(root)

    def count(self, root: Tag) -> int:
        """`countMatching`."""
        try:
            return len(self._read_steps(root))
        except PathError:
            return 0

    # ── запись ───────────────────────────────────────────────────────────
    def _visit_parents(
        self,
        root: Tag,
        create: bool,
        f: Callable[[Tag], None],
    ) -> None:
        """Родители последнего узла; недостающие создаются
        (`getOrCreateParents`)."""
        self._descend(0, len(self.nodes) - 1, root, create, None, f)

    def _descend(
        self,
        frm: int,
        to: int,
        tag: Tag,
        create: bool,
        last_value: Optional[Callable[[], Tag]],
        f: Callable[[Tag], None],
    ) -> None:
        """Пройти узлы `nodes[frm..to]` от `tag`, вызывая `f` на каждом
        достигнутом теге."""
        if frm >= to:
            f(tag)
            return
        node = self.nodes[frm]

        def default_child() -> Tag:
            nxt = self.nodes[frm + 1] if frm + 1 < len(self.nodes) else None
            if nxt is not None and frm + 1 < to:
                return _preferred_parent(nxt)
            if last_value is not None:
                return last_value()
            if nxt is not None:
                return _preferred_parent(nxt)
            return Tag(TagType.Compound, compound_val={})

        state = {"found": False, "error": None}

        def visit(child: Tag) -> None:
            state["found"] = True
            if state["error"] is None:
                try:
                    self._descend(frm + 1, to, child, create, last_value, f)
                except PathError as e:
                    state["error"] = e

        _step_mut(node, tag, default_child if create else None, visit)
        if state["error"] is not None:
            raise state["error"]
        if not state["found"]:
            raise self._not_found(frm)

    def get_or_create(
        self,
        root: Tag,
        new_value: Callable[[], Tag],
        f: Callable[[Tag], None],
    ) -> None:
        """`getOrCreate`: теги по пути, недостающие создаются как
        `new_value` (для последнего узла)."""
        self._descend(0, len(self.nodes), root, True, new_value, f)

    def set(self, root: Tag, value: Tag) -> int:
        """`set`: сколько тегов изменено."""
        if too_deep(value, len(self.nodes)):
            raise PathError("arguments.nbtpath.too_deep", [], 0)
        if not self.nodes:
            return 0
        last = self.nodes[-1]
        changed = [0]

        def f(parent: Tag) -> None:
            changed[0] += _set_tag(last, parent, value)

        self._visit_parents(root, True, f)
        return changed[0]

    def remove(self, root: Tag) -> int:
        """`remove`: сколько тегов удалено."""
        if not self.nodes:
            return 0
        last = self.nodes[-1]
        removed = [0]

        def f(parent: Tag) -> None:
            removed[0] += _remove_tag(last, parent)

        try:
            self._visit_parents(root, False, f)
        except PathError:
            pass
        return removed[0]

    def insert(self, index: int, root: Tag, values: List[Tag]) -> int:
        """`NbtPathArgument.NbtPath.insert`: вставить принятые теги во все
        достигнутые коллекции."""
        for v in values:
            if too_deep(v, len(self.nodes)):
                raise CollectionError(
                    "path", PathError("arguments.nbtpath.too_deep", [], 0)
                )
        modified = [0]
        error = [None]

        def target(t: Tag) -> None:
            if error[0] is not None:
                return
            shown = to_snbt(t)

            def body(lst: List[Tag], kind: "_ElementKind") -> bool:
                start = len(lst) + index + 1 if index < 0 else index
                any_ = False
                at = start
                for v in values:
                    if not kind.accepts(v):
                        continue
                    if at < 0 or at > len(lst):
                        raise _InvalidIndex(at)
                    lst.insert(at, copy.deepcopy(v))
                    at += 1
                    any_ = True
                return any_

            try:
                result = _with_elements(t, body)
            except _InvalidIndex as e:
                error[0] = CollectionError("invalid_index", e.at)
                return
            if result is None:
                error[0] = CollectionError("expected_list", shown)
            elif result:
                modified[0] += 1

        try:
            self.get_or_create(root, lambda: Tag(TagType.List, list_val=[]), target)
        except PathError as e:
            raise CollectionError("path", e)
        if error[0] is not None:
            raise error[0]
        return modified[0]


# ── ошибка модификации коллекции (Rust enum CollectionError) ─────────────
@dataclass
class CollectionError(Exception):
    """`CollectionError`: `path` | `expected_list` | `invalid_index`."""

    kind: str
    payload: object = None


class _InvalidIndex(Exception):
    def __init__(self, at: int) -> None:
        super().__init__(at)
        self.at = at


# ── частичное сравнение NBT (`NbtUtils.compareNbt(expected, actual, true)`) ─
def compare_nbt(expected: Tag, actual: Optional[Tag]) -> bool:
    """`NbtUtils.compareNbt`: частичное совпадение (ожидаемое — подмножество)."""
    if actual is None:
        return False
    if expected.tag_type != actual.tag_type:
        return False
    if expected.is_compound and actual.is_compound:
        e = expected.compound_val or {}
        a = actual.compound_val or {}
        return len(a) >= len(e) and all(compare_nbt(v, a.get(k)) for k, v in e.items())
    if expected.is_list and actual.is_list:
        e = expected.list_val or []
        a = actual.list_val or []
        if not e:
            return not a
        return len(a) >= len(e) and all(
            any(compare_nbt(x, y) for y in a) for x in e
        )
    return _tag_eq(expected, actual)


# ── спископодобные теги ──────────────────────────────────────────────────
def elements(tag: Tag) -> Optional[List[Tag]]:
    """Элементы List или числового массива (иначе None)."""
    if tag.is_list:
        return list(tag.list_val or [])
    if tag.is_bytearray:
        return [Tag(TagType.Byte, byte_val=_byte_signed(b)) for b in (tag.bytes_val or b"")]
    if tag.is_intarray:
        return [Tag(TagType.Int, int_val=v) for v in (tag.intarray_val or [])]
    if tag.is_longarray:
        return [Tag(TagType.Long, long_val=v) for v in (tag.longarray_val or [])]
    return None


def _byte_signed(b: int) -> int:
    """`Tag::Byte(*b as i8)`."""
    return b if b < 128 else b - 256


def _to_i32(v: int) -> int:
    """Rust `v as i32`: усечение до 32 бит со знаком."""
    return struct.unpack(">i", struct.pack(">I", v & 0xFFFFFFFF))[0]


def _f64_to_i32_sat(v: float) -> int:
    """Rust `f32/f64 as i32`: насыщение на границах, NaN → 0."""
    if math.isnan(v):
        return 0
    if v >= 2147483648.0:
        return 2147483647
    if v <= -2147483648.0:
        return -2147483648
    return int(v)


def _f64_to_i64_sat(v: float) -> int:
    """Rust `f32/f64 as i64`: насыщение на границах, NaN → 0."""
    if math.isnan(v):
        return 0
    if v >= 9223372036854775808.0:
        return 9223372036854775807
    if v <= -9223372036854775808.0:
        return -9223372036854775808
    return int(v)


def _floor_value(v: float) -> float:
    if math.isnan(v) or math.isinf(v):
        return v
    return float(math.floor(v))


def int_value(t: Tag) -> Optional[int]:
    """`DoubleTag.intValue`/`FloatTag.intValue` — floor перед i32; целые
    сужаются своим intValue. Как в Rust `int_value`."""
    tt = t.tag_type
    if tt == TagType.Byte:
        return int(t.byte_val or 0)
    if tt == TagType.Short:
        return int(t.short_val or 0)
    if tt == TagType.Int:
        return int(t.int_val or 0)
    if tt == TagType.Long:
        return _to_i32(int(t.long_val or 0))
    if tt == TagType.Float:
        return _f64_to_i32_sat(_floor_value(t.float_val or 0.0))
    if tt == TagType.Double:
        return _f64_to_i32_sat(_floor_value(t.double_val or 0.0))
    return None


def _long_value(t: Tag) -> Optional[int]:
    """`FloatTag.longValue` усекает; `DoubleTag.longValue` сперва floor."""
    tt = t.tag_type
    if tt == TagType.Byte:
        return int(t.byte_val or 0)
    if tt == TagType.Short:
        return int(t.short_val or 0)
    if tt == TagType.Int:
        return int(t.int_val or 0)
    if tt == TagType.Long:
        return int(t.long_val or 0)
    if tt == TagType.Float:
        return _f64_to_i64_sat(t.float_val or 0.0)
    if tt == TagType.Double:
        return _f64_to_i64_sat(_floor_value(t.double_val or 0.0))
    return None


class _ElementKind:
    """Вид коллекции: List принимает любой тег, массивы — только числовые."""

    List = "list"
    NumericArray = "numeric_array"

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def accepts(self, value: Tag) -> bool:
        if self.kind == _ElementKind.List:
            return True
        return value.tag_type in (
            TagType.Byte,
            TagType.Short,
            TagType.Int,
            TagType.Long,
            TagType.Float,
            TagType.Double,
        )


_KIND_LIST = _ElementKind(_ElementKind.List)
_KIND_NUMERIC = _ElementKind(_ElementKind.NumericArray)


def _with_elements(tag: Tag, f: Callable[[List[Tag], _ElementKind], object]):
    """Адаптер как в Rust `with_elements`: пройти `f` по элементам, затем
    записать массивы через их числовой аксессор. None, если тег не список."""
    if tag.is_list:
        if tag.list_val is None:
            tag.list_val = []
        return f(tag.list_val, _KIND_LIST)
    if tag.is_bytearray:
        v = elements(tag) or []
        r = f(v, _KIND_NUMERIC)
        tag.bytes_val = bytes(
            (int_value(x) & 0xFF) for x in v if int_value(x) is not None
        )
        return r
    if tag.is_intarray:
        v = elements(tag) or []
        r = f(v, _KIND_NUMERIC)
        tag.intarray_val = [int_value(x) for x in v if int_value(x) is not None]
        return r
    if tag.is_longarray:
        v = elements(tag) or []
        r = f(v, _KIND_NUMERIC)
        tag.longarray_val = [_long_value(x) for x in v if _long_value(x) is not None]
        return r
    return None


# ── глубина ──────────────────────────────────────────────────────────────
def too_deep(tag: Tag, depth: int) -> bool:
    """`isTooDeep`."""
    if depth >= 512:
        return True
    if tag.is_compound:
        return any(too_deep(t, depth + 1) for t in (tag.compound_val or {}).values())
    if tag.is_list:
        return any(too_deep(t, depth + 1) for t in (tag.list_val or []))
    return False


def _preferred_parent(node: Node) -> Tag:
    if isinstance(node, (AllElements, Index, MatchElement)):
        return Tag(TagType.List, list_val=[])
    return Tag(TagType.Compound, compound_val={})


def _get_child(compound: Tag, name: str) -> Optional[Tag]:
    return (compound.compound_val or {}).get(name)


# ── мутирующий шаг (Rust step_mut) ───────────────────────────────────────
def _step_mut(
    node: Node,
    parent: Tag,
    create: Optional[Callable[[], Tag]],
    out: Callable[[Tag], None],
) -> None:
    if isinstance(node, Child):
        if parent.is_compound:
            c = parent.compound_val
            if c is None:
                return
            if node.name not in c:
                if create is None:
                    return
                c[node.name] = create()
            out(c[node.name])
    elif isinstance(node, MatchChild):
        if parent.is_compound:
            c = parent.compound_val
            if c is None:
                return
            if node.name not in c:
                if create is None:
                    return
                c[node.name] = copy.deepcopy(node.pattern)
                out(c[node.name])
            else:
                t = c[node.name]
                if compare_nbt(node.pattern, t):
                    out(t)
    elif isinstance(node, AllElements):
        make = create

        def body(lst: List[Tag], kind: _ElementKind) -> None:
            if len(lst) == 0:
                if make is not None:
                    value = make()
                    if kind.accepts(value):
                        lst.append(value)
                        out(lst[0])
            else:
                for t in lst:
                    out(t)

        _with_elements(parent, body)
    elif isinstance(node, Index):
        def body(lst: List[Tag], kind: _ElementKind) -> None:
            total = len(lst)
            idx = total + node.value if node.value < 0 else node.value
            if 0 <= idx < total:
                out(lst[idx])

        _with_elements(parent, body)
    elif isinstance(node, MatchElement):
        if parent.is_list:
            lst = parent.list_val or []
            any_ = False
            for t in lst:
                if compare_nbt(node.pattern, t):
                    any_ = True
                    out(t)
            if not any_ and create is not None:
                lst.append(copy.deepcopy(node.pattern))
                out(lst[-1])
    elif isinstance(node, MatchRoot):
        if parent.is_compound and compare_nbt(node.pattern, parent):
            out(parent)


# ── установка значения (Rust set_tag) ────────────────────────────────────
def _set_tag(node: Node, parent: Tag, value: Tag) -> int:
    if isinstance(node, Child):
        if parent.is_compound:
            c = parent.compound_val
            if c is None:
                return 0
            prev = c.get(node.name)
            c[node.name] = copy.deepcopy(value)
            return int(not _tag_eq(prev, value))
        return 0
    if isinstance(node, MatchChild):
        if parent.is_compound:
            c = parent.compound_val
            if c is None:
                return 0
            cur = c.get(node.name)
            if compare_nbt(node.pattern, cur) and not _tag_eq(cur, value):
                c[node.name] = copy.deepcopy(value)
                return 1
        return 0
    if isinstance(node, AllElements):
        def body(lst: List[Tag], kind: _ElementKind) -> int:
            total = len(lst)
            if total == 0:
                if kind.accepts(value):
                    lst.append(copy.deepcopy(value))
                # AllElementsNode здесь возвращает 1, даже если addTag отклонил.
                return 1
            changed = sum(1 for t in lst if not _tag_eq(t, value))
            if changed == 0:
                return 0
            lst.clear()
            if not kind.accepts(value):
                return 0
            lst.extend(copy.deepcopy(value) for _ in range(total))
            return changed

        r = _with_elements(parent, body)
        return 0 if r is None else r
    if isinstance(node, Index):
        def body(lst: List[Tag], kind: _ElementKind) -> int:
            total = len(lst)
            idx = total + node.value if node.value < 0 else node.value
            if 0 <= idx < total and not _tag_eq(lst[idx], value) and kind.accepts(value):
                lst[idx] = copy.deepcopy(value)
                return 1
            return 0

        r = _with_elements(parent, body)
        return 0 if r is None else r
    if isinstance(node, MatchElement):
        if not parent.is_list:
            return 0
        lst = parent.list_val or []
        if len(lst) == 0:
            lst.append(copy.deepcopy(value))
            return 1
        changed = 0
        for j, t in enumerate(lst):
            if compare_nbt(node.pattern, t) and not _tag_eq(t, value):
                lst[j] = copy.deepcopy(value)
                changed += 1
        return changed
    if isinstance(node, MatchRoot):
        return 0
    return 0


# ── удаление (Rust remove_tag) ───────────────────────────────────────────
def _remove_tag(node: Node, parent: Tag) -> int:
    if isinstance(node, Child):
        if parent.is_compound:
            c = parent.compound_val
            if c is not None and node.name in c:
                del c[node.name]
                return 1
        return 0
    if isinstance(node, MatchChild):
        if parent.is_compound:
            c = parent.compound_val
            if c is not None and compare_nbt(node.pattern, c.get(node.name)):
                if node.name in c:
                    del c[node.name]
                    return 1
        return 0
    if isinstance(node, AllElements):
        def body(lst: List[Tag], kind: _ElementKind) -> int:
            total = len(lst)
            lst.clear()
            return total

        r = _with_elements(parent, body)
        return 0 if r is None else r
    if isinstance(node, Index):
        def body(lst: List[Tag], kind: _ElementKind) -> int:
            total = len(lst)
            idx = total + node.value if node.value < 0 else node.value
            if 0 <= idx < total:
                lst.pop(idx)
                return 1
            return 0

        r = _with_elements(parent, body)
        return 0 if r is None else r
    if isinstance(node, MatchElement):
        if parent.is_list:
            lst = parent.list_val or []
            before = len(lst)
            lst[:] = [t for t in lst if not compare_nbt(node.pattern, t)]
            return before - len(lst)
        return 0
    if isinstance(node, MatchRoot):
        return 0
    return 0


# ── равенство тегов (Rust derived PartialEq) ─────────────────────────────
def _f32_bits(v: float) -> int:
    return struct.unpack(">I", struct.pack(">f", v))[0]


def _f64_bits(v: float) -> int:
    return struct.unpack(">Q", struct.pack(">d", v))[0]


def _tag_eq(a: Optional[Tag], b: Optional[Tag]) -> bool:
    """Равенство как у Rust `Tag` (enum derive PartialEq). Float/Double
    сравниваются по битам, поэтому NaN == NaN при совпадающих битах."""
    if a is None or b is None:
        return a is b
    if a.tag_type != b.tag_type:
        return False
    tt = a.tag_type
    if tt == TagType.End:
        return True
    if tt == TagType.Byte:
        return a.byte_val == b.byte_val
    if tt == TagType.Short:
        return a.short_val == b.short_val
    if tt == TagType.Int:
        return a.int_val == b.int_val
    if tt == TagType.Long:
        return a.long_val == b.long_val
    if tt == TagType.Float:
        return _f32_bits(a.float_val or 0.0) == _f32_bits(b.float_val or 0.0)
    if tt == TagType.Double:
        return _f64_bits(a.double_val or 0.0) == _f64_bits(b.double_val or 0.0)
    if tt == TagType.String:
        return a.str_val == b.str_val
    if tt == TagType.ByteArray:
        return (a.bytes_val or b"") == (b.bytes_val or b"")
    if tt == TagType.IntArray:
        return (a.intarray_val or []) == (b.intarray_val or [])
    if tt == TagType.LongArray:
        return (a.longarray_val or []) == (b.longarray_val or [])
    if tt == TagType.List:
        la = a.list_val or []
        lb = b.list_val or []
        return len(la) == len(lb) and all(_tag_eq(x, y) for x, y in zip(la, lb))
    if tt == TagType.Compound:
        ca = a.compound_val or {}
        cb = b.compound_val or {}
        return len(ca) == len(cb) and all(
            k in cb and _tag_eq(v, cb[k]) for k, v in ca.items()
        )
    return False


# ── разбор узлов (Rust parse_node и помощники) ───────────────────────────
def _parse_node(text: str, i: int, first: bool) -> Tuple[Node, int]:
    b = text
    n = len(b)

    def invalid(at: int) -> PathError:
        return PathError("arguments.nbtpath.node.invalid", [], at)

    c = b[i]
    if c == '"' or c == "'":
        name, nxt = _read_quoted(text, i)
        return _read_object_node(text, name, nxt)
    if c == "[":
        j = i + 1
        if j < n and b[j] == "{":
            pattern, nxt = _parse_compound(text, j)
            j = nxt
            _expect(text, j, "]")
            return MatchElement(pattern), j + 1
        if j < n and b[j] == "]":
            return AllElements(), j + 1
        start = j
        if j < n and b[j] == "-":
            j += 1
        while j < n and b[j] in "0123456789":
            j += 1
        seg = text[start:j]
        try:
            num = int(seg)
        except ValueError:
            raise PathError("parsing.int.invalid", [seg], start)
        if not (-2147483648 <= num <= 2147483647):
            raise PathError("parsing.int.invalid", [seg], start)
        _expect(text, j, "]")
        return Index(num), j + 1
    if c == "{":
        if not first:
            raise invalid(i)
        pattern, nxt = _parse_compound(text, i)
        return MatchRoot(pattern), nxt
    # голое имя
    j = i
    while j < n and b[j] not in " \"'[].{}":
        j += 1
    if j == i:
        raise invalid(i)
    return _read_object_node(text, text[i:j], j)


def _read_object_node(text: str, name: str, i: int) -> Tuple[Node, int]:
    if name == "":
        raise PathError("arguments.nbtpath.node.invalid", [], i)
    if i < len(text) and text[i] == "{":
        pattern, nxt = _parse_compound(text, i)
        return MatchChild(name, pattern), nxt
    return Child(name), i


def _expect(text: str, i: int, c: str) -> None:
    if i < len(text) and text[i] == c:
        return
    raise PathError("parsing.expected", [c], i)


def _read_quoted(text: str, i: int) -> Tuple[str, int]:
    quote = text[i]
    out: List[str] = []
    escaped = False
    o = 0
    for ch in text[i + 1:]:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == quote:
            return "".join(out), i + 1 + o + 1
        else:
            out.append(ch)
        o += 1
    raise PathError("parsing.quote.expected.end", [], len(text))


def _parse_compound(text: str, i: int) -> Tuple[Tag, int]:
    """Найти сбалансированный конец скобок, затем разобрать SNBT внутри."""
    n = len(text)
    depth = 0
    quote: Optional[str] = None
    j = i
    while j < n:
        c = text[j]
        if quote is not None:
            if c == "\\":
                j += 1
            elif c == quote:
                quote = None
        elif c == '"' or c == "'":
            quote = c
        elif c == "{" or c == "[":
            depth += 1
        elif c == "}" or c == "]":
            depth -= 1
            if depth == 0:
                try:
                    tag, _ = parse_snbt(text[i:j + 1])
                except Exception as e:  # noqa: BLE001 — как Rust map_err
                    raise PathError("argument.nbt.invalid", [str(e)], i)
                return tag, j + 1
        j += 1
    raise PathError("argument.nbt.expected.compound", [], i)


# ── удобные обёртки (parse + операция) ───────────────────────────────────
def get(tag: Tag, path: str) -> List[Tag]:
    """Разобрать путь и вернуть все совпавшие теги."""
    return NbtPath.parse(path).get(tag)


def set(tag: Tag, path: str, value: Tag) -> int:
    """Разобрать путь и установить значение; вернуть число изменений."""
    return NbtPath.parse(path).set(tag, value)


def remove(tag: Tag, path: str) -> int:
    """Разобрать путь и удалить совпадения; вернуть число удалённых."""
    return NbtPath.parse(path).remove(tag)
