# Тесты порта NBT-путей (horizon-client-core/src/nbt_path.rs) →
# quadrix/core/nbt_path.py.
#
# Проверяем разбор пути (Child/Index/AllElements/MatchChild/MatchElement/
# MatchRoot), get/set/remove/insert/count, частичное сравнение NBT
# (`compare_nbt`), работу с числовыми массивами, round-trip и реальные
# данные из `.local`.

from __future__ import annotations

from pathlib import Path

import pytest

from quadrix.core.nbt_path import (
    AllElements,
    Child,
    CollectionError,
    Index,
    MatchChild,
    MatchElement,
    MatchRoot,
    NbtPath,
    PathError,
    compare_nbt,
    get,
    int_value,
    remove,
    set,
    too_deep,
)
from quadrix.core.snbt import parse_snbt, to_snbt
from quadrix.world.nbt import Tag, TagType, read_nbt

REPO = Path(__file__).resolve().parents[2]


# ── конструкторы ─────────────────────────────────────────────────────────
def tag(s: str) -> Tag:
    return parse_snbt(s)[0]


def path(s: str) -> NbtPath:
    return NbtPath.parse(s)


def show(v: list) -> list:
    return [to_snbt(t) for t in v]


def b(v: int) -> Tag:
    return Tag(TagType.Byte, byte_val=v)


def i(v: int) -> Tag:
    return Tag(TagType.Int, int_val=v)


# ── разбор ───────────────────────────────────────────────────────────────
def test_parse_named_chain_has_three_child_nodes() -> None:
    p = path("a.b.c")
    assert len(p.nodes) == 3
    assert all(isinstance(n, Child) for n in p.nodes)
    assert [n.name for n in p.nodes] == ["a", "b", "c"]
    assert p.ends == [1, 3, 5]
    assert not p.is_empty()


def test_parse_index_node() -> None:
    p = path("a[0]")
    assert isinstance(p.nodes[0], Child) and p.nodes[0].name == "a"
    assert isinstance(p.nodes[1], Index) and p.nodes[1].value == 0
    assert path("a[-3]").nodes[1].value == -3


def test_parse_all_elements_is_the_wildcard() -> None:
    p = path("a[]")
    assert isinstance(p.nodes[0], Child)
    assert isinstance(p.nodes[1], AllElements)
    # `*` в Horizon не wildcard, а обычный символ имени поля.
    star = path("a.*.b")
    assert [n.name for n in star.nodes] == ["a", "*", "b"]


def test_parse_match_child_with_compound_predicate() -> None:
    p = path("a{key:1}")
    assert isinstance(p.nodes[0], MatchChild)
    assert p.nodes[0].name == "a"
    assert p.nodes[0].pattern.is_compound
    assert show([p.nodes[0].pattern]) == ["{key:1}"]


def test_parse_match_root_and_match_element() -> None:
    root = path("{source:1b}.a")
    assert isinstance(root.nodes[0], MatchRoot)
    assert show([root.nodes[0].pattern]) == ["{source:1b}"]
    assert isinstance(root.nodes[1], Child)
    elem = path("l[{id:2}].n")
    assert isinstance(elem.nodes[1], MatchElement)
    assert show([elem.nodes[1].pattern]) == ["{id:2}"]


def test_parse_errors_and_prefix() -> None:
    with pytest.raises(PathError) as e1:
        NbtPath.parse("a..b")
    assert e1.value.key == "arguments.nbtpath.node.invalid"
    with pytest.raises(PathError) as e2:
        NbtPath.parse("a.{b:1}")
    assert e2.value.key == "arguments.nbtpath.node.invalid"
    with pytest.raises(PathError) as e3:
        NbtPath.parse("a[1")
    assert e3.value.key == "parsing.expected"
    with pytest.raises(PathError) as e4:
        NbtPath.parse("a]")
    assert e4.value.key == "parsing.expected"
    p, used = NbtPath.parse_prefix("a.b[0] rest")
    assert (p.as_str(), used) == ("a.b[0]", 6)


def test_is_field_path() -> None:
    for text in [
        "blockState.properties",
        '"blockState"."properties"',
        "{source:1b}.blockState.properties",
        'blockState{id:"minecraft:piston_head"}.properties',
    ]:
        p = path(text)
        assert p.is_field_path(["blockState", "properties"])
        assert not p.is_field_path(["blockState"])
    assert path("{source:1b}").is_field_path([])
    assert not path("blockState[].properties").is_field_path(
        ["blockState", "properties"]
    )


# ── чтение ───────────────────────────────────────────────────────────────
def test_get_follows_the_path() -> None:
    root = tag('{a:{b:[{id:1,n:"x"},{id:2,n:"y"},{id:3}]},c:5,"d e":7}')
    assert show(path("c").get(root)) == ["5"]
    assert show(path('"d e"').get(root)) == ["7"]
    assert show(path("a.b[0].n").get(root)) == ['"x"']
    assert show(path("a.b[-1]").get(root)) == ["{id:3}"]
    assert show(path("a.b[].id").get(root)) == ["1", "2", "3"]
    assert show(path("a.b[{id:2}].n").get(root)) == ['"y"']
    assert show(path("a{b:[{id:1}]}.b[0].id").get(root)) == ["1"]
    assert show(path("{c:5}.c").get(root)) == ["5"]
    with pytest.raises(PathError):
        path("{c:6}.c").get(root)
    e = None
    try:
        path("a.zzz.q").get(root)
    except PathError as ex:
        e = ex
    assert e is not None and e.key == "arguments.nbtpath.nothing_found"
    assert e.args == ["a.zzz"]


def test_get_index_and_all_elements() -> None:
    root = tag("{l:[10,20,30]}")
    assert show(path("l[1]").get(root)) == ["20"]
    assert show(path("l[-1]").get(root)) == ["30"]
    assert show(path("l[]").get(root)) == ["10", "20", "30"]
    # Индекс вне диапазона — ошибка not_found.
    with pytest.raises(PathError):
        path("l[7]").get(root)


def test_get_wildcard_over_list_of_compounds() -> None:
    root = tag('{l:[{id:1,n:"x"},{id:2,n:"y"}]}')
    assert show(path("l[].id").get(root)) == ["1", "2"]
    assert show(path("l[].n").get(root)) == ['"x"', '"y"']


def test_get_match_filter_selects_only_matching() -> None:
    root = tag('{e:{source:1,id:"x"},f:{source:2}}')
    assert show(path("e{source:1}").get(root)) == ['{id:"x",source:1}']
    with pytest.raises(PathError):
        path("f{source:1}").get(root)
    # MatchElement по списку.
    lst = tag('{l:[{id:1},{id:2},{id:2}]}')
    assert show(path("l[{id:2}]").get(lst)) == ["{id:2}", "{id:2}"]


def test_count() -> None:
    root = tag('{a:{b:[{id:1},{id:2},{id:3}]}}')
    assert path("a.b[].id").count(root) == 3
    assert path("a.nope").count(root) == 0


def test_numeric_arrays_act_like_lists_on_read() -> None:
    arr = tag("{v:[I;4,5,6]}")
    assert show(path("v[1]").get(arr)) == ["5"]
    assert show(path("v[]").get(arr)) == ["4", "5", "6"]


# ── запись ───────────────────────────────────────────────────────────────
def test_set_creates_and_reports_changes() -> None:
    root = tag("{a:{x:1}}")
    assert path("a.x").set(root, i(2)) == 1
    assert path("a.x").set(root, i(2)) == 0
    assert path("b.c.d").set(root, tag('"deep"')) == 1
    assert to_snbt(root) == '{a:{x:2},b:{c:{d:"deep"}}}'

    root2 = tag("{l:[1,2,3]}")
    assert path("l[1]").set(root2, i(9)) == 1
    assert path("l[7]").set(root2, i(9)) == 0
    assert path("l[]").set(root2, i(0)) == 3
    assert to_snbt(root2) == "{l:[0,0,0]}"

    root3 = tag("{}")
    assert path("x[].y").set(root3, i(1)) == 1
    assert to_snbt(root3) == "{x:[{y:1}]}"


def test_set_on_scalar_parent_returns_zero() -> None:
    root = tag("{a:5}")
    # `a` — не компаунд, поэтому записать `a.b` некуда.
    assert set(root, "a.b", i(1)) == 0
    assert to_snbt(root) == "{a:5}"


def test_set_match_creates_missing_from_pattern() -> None:
    root = tag("{l:[{id:1,v:0},{id:2,v:0}]}")
    assert path("l[{id:2}].v").set(root, i(5)) == 1
    assert to_snbt(root) == "{l:[{id:1,v:0},{id:2,v:5}]}"
    assert path("l[{id:3}].v").set(root, i(1)) == 1
    assert path("l[{id:3}].v").count(root) == 1


def test_remove_counts() -> None:
    root = tag("{a:1,l:[1,2,3,2],c:{d:1}}")
    assert path("a").remove(root) == 1
    assert path("a").remove(root) == 0
    assert path("l[1]").remove(root) == 1
    assert path("c.d").remove(root) == 1
    assert to_snbt(root) == "{c:{},l:[1,3,2]}"
    root2 = tag("{l:[{k:1},{k:2},{k:1}]}")
    assert path("l[{k:1}]").remove(root2) == 2
    assert to_snbt(root2) == "{l:[{k:2}]}"
    assert path("l[]").remove(root2) == 1


def test_insert_positions_and_errors() -> None:
    root = tag("{l:[1,2]}")
    assert path("l").insert(0, root, [i(0)]) == 1
    assert path("l").insert(-1, root, [i(9)]) == 1
    assert path("l").insert(1, root, [i(5), i(6)]) == 1
    assert to_snbt(root) == "{l:[0,5,6,1,2,9]}"
    with pytest.raises(CollectionError) as e:
        path("l").insert(99, root, [i(1)])
    assert e.value.kind == "invalid_index" and e.value.payload == 99
    # Отсутствующий список создаётся.
    assert path("n").insert(-1, root, [i(1)]) == 1
    with pytest.raises(CollectionError) as e2:
        path("l[0]").insert(0, root, [i(1)])
    assert e2.value.kind == "expected_list"


def test_numeric_array_edits_use_destination_accessor() -> None:
    cases = [
        ("{v:[B;1b,2b]}", "-3.5f", "{v:[B;1b,-4b,2b]}", "{v:[B;-4b,2b]}", "{v:[B;-4b,-4b]}"),
        ("{v:[B;1b,2b]}", "-3.5d", "{v:[B;1b,-4b,2b]}", "{v:[B;-4b,2b]}", "{v:[B;-4b,-4b]}"),
        ("{v:[I;1,2]}", "-3.5f", "{v:[I;1,-4,2]}", "{v:[I;-4,2]}", "{v:[I;-4,-4]}"),
        ("{v:[I;1,2]}", "-3.5d", "{v:[I;1,-4,2]}", "{v:[I;-4,2]}", "{v:[I;-4,-4]}"),
        ("{v:[L;1L,2L]}", "-3.5f", "{v:[L;1L,-3L,2L]}", "{v:[L;-3L,2L]}", "{v:[L;-3L,-3L]}"),
        ("{v:[L;1L,2L]}", "-3.5d", "{v:[L;1L,-4L,2L]}", "{v:[L;-4L,2L]}", "{v:[L;-4L,-4L]}"),
    ]
    for initial, value, inserted, indexed, allv in cases:
        val = tag(value)
        r = tag(initial)
        assert path("v").insert(1, r, [val]) == 1
        assert r == tag(inserted)
        r = tag(initial)
        assert path("v[0]").set(r, val) == 1
        assert r == tag(indexed)
        r = tag(initial)
        assert path("v[]").set(r, val) == 2
        assert r == tag(allv)


def test_numeric_arrays_reject_nonnumeric() -> None:
    for initial in ["{v:[B;1b,2b]}", "{v:[I;1,2]}", "{v:[L;1L,2L]}"]:
        original = tag(initial)
        bad = tag('"bad"')
        for index in [0, 99, -99]:
            r = tag(initial)
            assert path("v").insert(index, r, [bad]) == 0
            assert r == original
        r = tag(initial)
        assert path("v[0]").set(r, bad) == 0
        assert r == original
    # Пустой массив: count сохраняется при отклонении.
    for initial in ["{v:[B;]}", "{v:[I;]}", "{v:[L;]}"]:
        r = tag(initial)
        assert path("v[]").set(r, tag('"bad"')) == 1
        assert r == tag(initial)


# ── сравнение / глубина / round-trip ─────────────────────────────────────
def test_partial_comparison() -> None:
    actual = tag('{a:1,b:{c:[1,2,3],d:"x"},e:2}')
    assert compare_nbt(tag("{b:{c:[2]}}"), actual)
    assert compare_nbt(tag("{a:1}"), actual)
    assert not compare_nbt(tag("{a:2}"), actual)
    assert not compare_nbt(tag("{a:1L}"), actual)
    assert not compare_nbt(tag("{z:1}"), actual)
    assert compare_nbt(tag("{b:{c:[]}}"), tag("{b:{c:[]}}"))
    assert not compare_nbt(tag("{b:{c:[]}}"), actual)
    assert not compare_nbt(tag("{a:1}"), None)


def test_int_value_and_too_deep() -> None:
    assert int_value(b(7)) == 7
    assert int_value(Tag(TagType.Float, float_val=-3.5)) == -4
    assert int_value(Tag(TagType.Double, double_val=-3.5)) == -4
    assert int_value(Tag(TagType.String, str_val="x")) is None
    deep = tag("{a:{b:{c:1}}}")
    assert not too_deep(deep, 0)
    assert too_deep(deep, 512)


def test_round_trip_parse_to_string() -> None:
    for text in [
        "a.b.c",
        "a[0]",
        "a[]",
        "a{key:1}",
        "{k:1}.a.b",
        '"d e".f',
        "a[-1]",
        "l[{id:2}].n",
        "{source:1b}.blockState.properties",
        "x[].y",
    ]:
        p = path(text)
        assert NbtPath.parse(p.to_string()) == p
        assert p.to_string() == text


def test_module_level_helpers() -> None:
    root = tag("{a:{b:1}}")
    assert show(get(root, "a.b")) == ["1"]
    assert set(root, "a.b", i(9)) == 1
    assert to_snbt(root) == "{a:{b:9}}"
    assert remove(root, "a.b") == 1
    assert to_snbt(root) == "{a:{}}"


# ── реальные данные из .local ────────────────────────────────────────────
def test_real_movement_properties_nbt() -> None:
    f = REPO / ".local" / "horizon-client-motion" / "movement-properties.nbt"
    if not f.is_file():
        pytest.skip("нет movement-properties.nbt в .local")
    root = Tag(TagType.Compound, compound_val=read_nbt(f.read_bytes()))
    assert show(path("DataVersion").get(root)) == ["5023"]
    assert show(path("states[0].id").get(root)) == ['"minecraft:air"']
    assert path("states[].id").count(root) == 35723
    # players-подобная проверка фильтра на реальном списке.
    assert path("states[0]").count(root) == 1
