# Тесты порта horizon-client-core/src/component.rs → quadrix/core/component.py.
#
# Проверяем реальное поведение файла: SNBT-парсер компонентов, цвета и тени,
# click/hover-события, URL-фильтр, встроенные объекты (head/atlas) и
# `name_text`. Зависимости scoreboard/identifier/key_display не портированы и
# повторены локально в component.py как FALLBACK.

from __future__ import annotations

import pytest

from quadrix.core.component import (
    SNBT_MAX_DEPTH,
    comp_text,
    hex_color,
    inline_object,
    name_text,
    object_style,
    parse_click_event,
    parse_identifier,
    parse_snbt,
    shadow_color,
    style_flag,
    to_text,
    untrusted_http_url,
)
from quadrix.core.text import ClickEvent, InlineObject, Text, named_color
from quadrix.world.nbt import Tag, TagType


def _int(v: int) -> Tag:
    return Tag(TagType.Int, int_val=v)


def _str(v: str) -> Tag:
    return Tag(TagType.String, str_val=v)


def _empty(_s: str) -> Text:
    return Text.empty()


# ── SNBT-парсер ──────────────────────────────────────────────────────────
def test_parse_snbt_returns_value_and_used() -> None:
    text = "{text:'Hi ',color:red,extra:[{text:\"there\",bold:1b}]}"
    v, used = parse_snbt(text + " rest")
    assert used == len(text)
    assert v["text"] == "Hi "
    assert v["color"] == "red"
    assert v["extra"][0] == {"text": "there", "bold": 1}


def test_parse_snbt_number_forms_and_suffixes() -> None:
    assert parse_snbt("3b")[0] == 3
    assert parse_snbt("200b")[0] == 200  # компонентный парсер без диапазона i8
    assert parse_snbt("-2L")[0] == -2
    assert parse_snbt("1.5f")[0] == 1.5
    assert parse_snbt("1e5")[0] == 100000.0
    assert isinstance(parse_snbt("1e5")[0], float)
    assert parse_snbt("42")[0] == 42
    assert parse_snbt("true")[0] is True
    assert parse_snbt("false")[0] is False


def test_parse_snbt_bare_numeric_words_stay_strings() -> None:
    assert parse_snbt("{text:nan}")[0]["text"] == "nan"
    assert parse_snbt("{text:Infinity}")[0]["text"] == "Infinity"
    assert parse_snbt("3bb")[0] == "3bb"
    assert parse_snbt("{n:1.5}")[0]["n"] == 1.5


def test_parse_snbt_typed_arrays_and_nesting_bound() -> None:
    assert parse_snbt("[B;1b,2b]")[0] == [1, 2]
    assert parse_snbt("[I;1,2,3]")[0] == [1, 2, 3]
    ok = "[" * SNBT_MAX_DEPTH + "1" + "]" * SNBT_MAX_DEPTH
    assert parse_snbt(ok)[0] is not None
    deep = "[" * (SNBT_MAX_DEPTH + 1) + "1" + "]" * (SNBT_MAX_DEPTH + 1)
    with pytest.raises(ValueError):
        parse_snbt(deep)


# ── цвета и тени ─────────────────────────────────────────────────────────
def test_hex_color_follows_text_color_parse_color() -> None:
    for bad in ["#1000000", "#FFFFFFFF", "#-FF", "#", "#zz", "FFFFFF", "#99999999999"]:
        assert hex_color(bad) is None, bad
    for good, want in [
        ("#FFFFFF", 0xFFFFFF),
        ("#000000", 0),
        ("#F", 15),
        ("#+FF", 255),
        ("#-0", 0),
    ]:
        assert hex_color(good) == want, good


def test_out_of_range_hex_color_is_dropped() -> None:
    text = to_text({"text": "A", "color": "#1000000"})
    assert text.spans[0].style.color is None


def test_shadow_color_accepts_packed_and_rgba_styles() -> None:
    packed = to_text({"text": "A", "shadow_color": -16711936})
    assert packed.spans[0].style.shadow_color == 0xFF00FF00
    assert packed.component()["shadow_color"] == -16711936

    rgba = to_text({"text": "A", "shadow_color": [1, 0, 0.5, 1]})
    assert rgba.spans[0].style.shadow_color == 0xFFFF007F

    translucent = to_text({"text": "A", "shadow_color": [1, 0, 0.5, 0.5]})
    assert translucent.spans[0].style.shadow_color == 0x7FFF007F

    zero = to_text({"text": "A", "shadow_color": 0})
    assert zero.spans[0].style.shadow_color == 0

    assert shadow_color([1, 0, 0.5]) is None
    assert shadow_color([1, 0, 0.5, 2]) is None


def test_style_flag_reads_bools_and_snbt_bytes() -> None:
    assert style_flag(True) is True
    assert style_flag(False) is False
    assert style_flag(1) is True
    assert style_flag(0) is False
    assert style_flag(1.0) is None
    assert style_flag(None) is None

    text = to_text({"text": "x", "bold": 1, "italic": 0, "underlined": True})
    assert text.spans[0].style.bold is True
    assert text.spans[0].style.italic is False
    assert text.spans[0].style.underlined is True


# ── URL-фильтр ───────────────────────────────────────────────────────────
def test_untrusted_http_url_only_http_and_https() -> None:
    assert untrusted_http_url("http://example.com") is True
    assert untrusted_http_url("HTTPS://example.com") is True
    assert untrusted_http_url("ftp://example.com") is False
    assert untrusted_http_url("file:/etc/passwd") is False
    assert untrusted_http_url("javascript:alert(1)") is False
    assert untrusted_http_url("https") is False


# ── текст из компонента ──────────────────────────────────────────────────
def test_to_text_builds_styled_spans() -> None:
    text, _ = parse_snbt("{text:'Hi ',color:red,extra:[{text:\"there\",bold:1b}]}")
    t = to_text(text)
    assert t.plain() == "Hi there"
    assert t.spans[1].style.color == named_color("red")
    assert t.spans[1].style.bold is True


def test_list_is_first_element_with_siblings() -> None:
    v, _ = parse_snbt('["a",{"text":"b"}]')
    assert to_text(v).plain() == "ab"


def test_player_object_keeps_siblings_and_fallback() -> None:
    component = {
        "text": "<",
        "extra": [
            {"object": "player", "player": {"name": "elyapluggin"}, "hat": False,
             "fallback": "[head]"},
            {"text": " >", "color": "gold"},
        ],
    }
    t = to_text(component)
    assert t.plain() == "<[head] >"
    obj = t.spans[1].style.inline_object
    assert isinstance(obj, InlineObject)
    assert obj.kind == "player" and obj.hat is False
    assert t.spans[2].style.inline_object is None


def test_atlas_object_default_fallbacks() -> None:
    sprite = to_text({"object": "atlas", "sprite": "minecraft:item/porkchop"})
    assert isinstance(sprite.spans[0].style.inline_object, InlineObject)
    assert sprite.spans[0].style.inline_object.sprite == "minecraft:item/porkchop"
    assert sprite.plain() == "[item/porkchop]"

    head = to_text({"object": "player", "player": {"name": "Steve"}})
    assert head.plain() == "[Steve head]"

    gui = to_text({"atlas": "gui", "sprite": "hud/heart/full"})
    assert gui.plain() == "[hud/heart/full@gui]"

    unknown = to_text({"object": "player", "player": None})
    assert unknown.plain() == "[unknown player head]"


# ── click-события ────────────────────────────────────────────────────────
def test_legacy_click_event_open_url_uses_value_field() -> None:
    modern = {
        "text": "site",
        "click_event": {"action": "open_url", "url": "https://example.com"},
        "underlined": True,
    }
    legacy = {
        "text": "site",
        "clickEvent": {"action": "open_url", "value": "https://example.com"},
        "underlined": 1,
    }
    for component in (modern, legacy):
        t = to_text(component)
        assert t.spans[0].style.click == ClickEvent.open_url("https://example.com")
        assert t.spans[0].style.underlined is True


def test_open_url_rejects_untrusted_schemes() -> None:
    t = to_text({
        "text": "x",
        "click_event": {"action": "open_url", "url": "file:/etc/passwd"},
    })
    assert t.spans[0].style.click is None


def test_custom_click_events_keep_payloads_and_inherit_to_inline_objects() -> None:
    compound = Tag(TagType.Compound, compound_val={
        "amount": _int(3),
        "shop": _str("potions"),
    })
    for payload, expected in [
        (None, None),  # key absent
        (42, _int(42)),
        ({"shop": "potions", "amount": 3}, compound),
    ]:
        event = {"action": "custom", "id": "test:shop"}
        if payload is not None:
            event["payload"] = payload
        component = {
            "text": "",
            "click_event": event,
            "extra": [
                {"object": "atlas", "sprite": "minecraft:item/potion"},
                "Shop",
            ],
        }
        t = to_text(component)
        for _c, style in t.chars():
            assert style.click == ClickEvent.custom("test:shop", expected)


def test_custom_click_with_null_payload_has_no_payload() -> None:
    component = {
        "text": "Shop",
        "click_event": {"action": "custom", "id": "test:shop", "payload": None},
    }
    t = to_text(component)
    assert t.spans[0].style.click == ClickEvent.custom("test:shop", None)
    assert "payload" not in t.component()


def test_bad_custom_ids_are_rejected() -> None:
    for bad in ["Bad ID", "Uppercase:shop"]:
        t = to_text({"text": "Shop", "click_event": {"action": "custom", "id": bad}})
        assert t.spans[0].style.click is None


def test_parse_identifier_accepts_and_rejects_resource_locations() -> None:
    assert parse_identifier("alt") == "minecraft:alt"
    assert parse_identifier("test:shop") == "test:shop"
    assert parse_identifier("Bad ID") is None
    assert parse_identifier("Uppercase:shop") is None
    assert parse_identifier("minecraft:") is None


# ── шрифт ────────────────────────────────────────────────────────────────
def test_the_font_is_inherited_and_kept() -> None:
    v, _ = parse_snbt(
        '{text:"a",font:"alt",extra:["b",{text:"c",font:"minecraft:uniform"}]}'
    )
    t = to_text(v)
    fonts = [style.font for _c, style in t.chars()]
    assert fonts == ["minecraft:alt", "minecraft:alt", "minecraft:uniform"]

    bad = to_text(parse_snbt('{text:"a",font:"Bad Font"}')[0])
    assert bad.spans[0].style.font is None


# ── name_text ────────────────────────────────────────────────────────────
def test_name_text_preserves_legacy_and_decodes_components() -> None:
    legacy = name_text(_str("\u00a76Golden Name"))
    assert legacy.plain() == "Golden Name"

    comp = name_text(Tag(TagType.Compound, compound_val={"text": _str("Custom Name")}))
    assert comp.plain() == "Custom Name"


# ── прямые проверки хелперов ─────────────────────────────────────────────
def test_object_style_and_hover_helpers() -> None:
    style = object_style({
        "color": "red",
        "bold": 1,
        "hover_event": {"action": "show_text", "value": "tip"},
    })
    assert style.color == named_color("red")
    assert style.bold is True
    assert style.hover is not None and style.hover.plain() == "tip"

    item = object_style({
        "hover_event": {"action": "show_item", "id": "minecraft:stone", "count": 1},
    })
    assert item.hover_item == {"action": "show_item", "id": "minecraft:stone", "count": 1}

    assert parse_click_event({"action": "suggest_command", "command": "/help"}) == \
        ClickEvent.suggest_command("/help")
    assert parse_click_event({"action": "copy_to_clipboard", "value": "hi"}) == \
        ClickEvent.copy_to_clipboard("hi")
    assert parse_click_event({"action": "change_page", "page": 2}) == \
        ClickEvent.change_page(2)
    assert parse_click_event({"action": "change_page", "page": 0}) is None


def test_inline_object_returns_none_for_unknown_shapes() -> None:
    assert inline_object({"object": "player"}, _empty) is None
    assert inline_object({"object": "atlas"}, _empty) is None
    assert inline_object({"object": "whatever", "player": "x"}, _empty) is None


def test_comp_text_round_trips_a_component() -> None:
    t = comp_text({"text": "hi", "color": "green"})
    assert t.plain() == "hi"
    assert t.spans[0].style.color == named_color("green")
