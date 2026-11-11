# Тесты порта SNBT (horizon-client-core/src/snbt.rs +
# horizon-world/src/snbt_text.rs + parse_snbt) → quadrix/core/snbt.py.
#
# Проверяем парсер (числа с суффиксами, строки, массивы, булевы, вложенность),
# писатель (канонический, сортировка ключей по UTF-16), Java-числа и
# экранирование. Tag переиспользуется из quadrix/world/nbt.py.

from __future__ import annotations

import math

import pytest

from quadrix.core.snbt import (
    MAX_DEPTH,
    Tag,
    TagType,
    Tag as SnbtTag,
    java_double,
    java_float,
    parse,
    parse_snbt,
    quote_and_escape,
    to_snbt,
)


# ── короткие конструкторы тегов ──────────────────────────────────────────
def b(v: int) -> Tag:
    return Tag(TagType.Byte, byte_val=v)


def s(v: int) -> Tag:
    return Tag(TagType.Short, short_val=v)


def i(v: int) -> Tag:
    return Tag(TagType.Int, int_val=v)


def L(v: int) -> Tag:
    return Tag(TagType.Long, long_val=v)


def f(v: float) -> Tag:
    return Tag(TagType.Float, float_val=v)


def d(v: float) -> Tag:
    return Tag(TagType.Double, double_val=v)


def st(v: str) -> Tag:
    return Tag(TagType.String, str_val=v)


def compound(m: dict) -> Tag:
    return Tag(TagType.Compound, compound_val=m)


def lst(items: list) -> Tag:
    return Tag(TagType.List, list_val=items)


# ── парсер ───────────────────────────────────────────────────────────────
def test_parse_compound_int() -> None:
    assert parse("{a:1}") == compound({"a": i(1)})


def test_parse_all_number_types() -> None:
    tag = parse("{a:1b, b:2s, c:3, d:4L, e:1.5f, f:2.5d}")
    assert tag == compound({
        "a": b(1), "b": s(2), "c": i(3), "d": L(4), "e": f(1.5), "f": d(2.5),
    })
    assert tag.compound_val["e"].tag_type == TagType.Float
    assert tag.compound_val["f"].tag_type == TagType.Double


def test_parse_double_quoted_string() -> None:
    assert parse('{s:"hello"}') == compound({"s": st("hello")})


def test_parse_single_quoted_string() -> None:
    assert parse("{s:'hello'}") == compound({"s": st("hello")})


def test_parse_string_with_escape() -> None:
    tag = parse('{s:"a\\nb\\tc"}')
    assert tag == compound({"s": st("a\nb\tc")})


def test_parse_list_of_ints() -> None:
    assert parse("[1, 2, 3]") == lst([i(1), i(2), i(3)])


def test_parse_byte_array() -> None:
    tag = parse("[B;1b, 2b]")
    assert tag.tag_type == TagType.ByteArray
    assert bytes(tag.bytes_val) == bytes([1, 2])


def test_parse_int_and_long_array() -> None:
    ia = parse("[I;1, 2, 3]")
    assert ia.tag_type == TagType.IntArray
    assert ia.intarray_val == [1, 2, 3]
    la = parse("[L;1L, 2L]")
    assert la.tag_type == TagType.LongArray
    assert la.longarray_val == [1, 2]


def test_parse_booleans_as_bytes() -> None:
    assert parse("{a:true, b:false}") == compound({"a": b(1), "b": b(0)})


def test_parse_unquoted_underscore_key() -> None:
    assert parse("{a_b:1}") == compound({"a_b": i(1)})


def test_parse_mixed_nesting() -> None:
    tag = parse("{pos:[1.5d,2.0d], id:\"minecraft:pig\", n:3b}")
    assert tag.compound_val["n"] == b(3)
    assert tag.compound_val["id"] == st("minecraft:pig")
    assert tag.compound_val["pos"] == lst([d(1.5), d(2.0)])


def test_parse_snbt_returns_used_count() -> None:
    text = "{a:1b,b:[I;1,2],c:'x y',d:[{e:2.5f}],f:true,g:id}"
    tag, used = parse_snbt(text + "rest")
    assert used == len(text)
    assert tag.compound_val["g"] == st("id")
    assert tag.compound_val["c"] == st("x y")
    assert tag.compound_val["d"].list_val[0].compound_val["e"] == f(2.5)


def test_trailing_comma_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse("{a:1,}")
    with pytest.raises(ValueError):
        parse("[1,2,]")


# ── голые слова и числа ──────────────────────────────────────────────────
def test_bare_words_stay_strings() -> None:
    for word in ["nan", "NaN", "inf", "infd", "NaNf", "Infinityd", "nand"]:
        assert parse(word) == st(word), word


def test_bare_number_forms() -> None:
    assert parse("1e5") == d(100000.0)
    assert parse("1.5f") == f(1.5)
    assert parse("3b") == b(3)
    assert parse("-2L") == L(-2)
    assert parse("42") == i(42)


def test_out_of_range_suffix_becomes_string() -> None:
    assert parse("200b") == st("200b")  # 200 не влезает в i8


# ── писатель ─────────────────────────────────────────────────────────────
def test_to_snbt_canonical_sorted() -> None:
    text = rt('{b:1b,a:"x",c:[1,2],d:1.5f,e:2d,f:3L,g:4s}')
    assert text == '{a:"x",b:1b,c:[1,2],d:1.5f,e:2.0d,f:3L,g:4s}'


def test_to_snbt_quotes_keys_and_arrays() -> None:
    assert rt('{"a b":1}') == '{"a b":1}'
    assert rt("{true:1}") == '{"true":1}'
    assert rt("[B;1b,2b]") == "[B;1B,2B]"
    assert rt("[I;1,2]") == "[I;1,2]"
    assert rt("[L;1L]") == "[L;1L]"


def test_round_trip_compound() -> None:
    for text in [
        '{a:1,b:2b}',
        '{s:"hi",l:[1,2,3],arr:[I;4,5]}',
        '{nested:{x:1.5d,flag:false}}',
    ]:
        tag = parse(text)
        assert parse(to_snbt(tag)) == tag


def test_simple_to_snbt() -> None:
    assert to_snbt(parse("{a:1}")) == "{a:1}"


# ── экранирование ────────────────────────────────────────────────────────
def test_quote_and_escape() -> None:
    assert quote_and_escape('say "hi"') == "'say \"hi\"'"
    assert quote_and_escape('it\'s "x"') == '"it\'s \\"x\\""'
    assert quote_and_escape("a\nb\\") == '"a\\nb\\\\"'


# ── Java-числа ───────────────────────────────────────────────────────────
def test_java_double_text() -> None:
    assert java_double(1.0) == "1.0"
    assert java_double(0.1) == "0.1"
    assert java_double(1.0e7) == "1.0E7"
    assert java_double(12345678.9) == "1.23456789E7"
    assert java_double(0.0001) == "1.0E-4"
    assert java_double(-3.5) == "-3.5"
    assert java_double(math.nan) == "NaN"


def test_java_float_text() -> None:
    assert java_float(0.3) == "0.3"
    assert java_float(100.0) == "100.0"


# ── вложенность ──────────────────────────────────────────────────────────
def test_nesting_is_bounded() -> None:
    ok = "[" * MAX_DEPTH + "1" + "]" * MAX_DEPTH
    assert parse(ok) is not None
    deep = "[" * (MAX_DEPTH + 1) + "1" + "]" * (MAX_DEPTH + 1)
    with pytest.raises(ValueError):
        parse(deep)


def test_snbt_tag_alias() -> None:
    assert SnbtTag is Tag


def rt(text: str) -> str:
    return to_snbt(parse(text))
