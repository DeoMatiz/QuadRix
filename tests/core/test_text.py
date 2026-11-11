# !Tests for quadrix.core.text (port of horizon-client-core/src/text.rs).
#
# Проверяем поведение: стили, legacy §, переводы, click/hover события,
# JSON round-trip и ANSI. Тексты не зависят от .local (lang.rs ещё не портирован).

from __future__ import annotations

import pytest

from quadrix.core.text import (
    COLORS,
    AQUA,
    GOLD,
    GREEN,
    RED,
    WHITE,
    ClickEvent,
    HoverEvent,
    Style,
    Text,
    format_translation,
    legacy_format,
    named_color,
)


# ── literal / plain ────────────────────────────────────────────────────
def test_literal_plain():
    assert Text.literal("hello").to_plain_string() == "hello"


def test_bold_not_in_plain():
    t = Text.literal("hello")
    t.style.bold = True
    assert t.to_plain_string() == "hello"
    assert t.style.bold is True


def test_empty_literal():
    assert Text.literal("").to_plain_string() == ""
    assert Text.empty().is_empty() is True


def test_bold_method_serializes():
    t = Text.literal("hi").bold()
    assert t.to_plain_string() == "hi"
    assert t.component()["bold"] is True


# ── ANSI ───────────────────────────────────────────────────────────────
def test_to_ansi_has_bold_code():
    s = Text.literal("hello").bold().to_ansi()
    assert "\x1b[1m" in s
    assert s.endswith("\x1b[0m")


def test_to_ansi_truecolor():
    s = Text.colored("x", RED).to_ansi()
    assert "38;2;255;85;85" in s


# ── translation ────────────────────────────────────────────────────────
def test_translatable_falls_back_to_key():
    # FALLBACK: lang не загружен — ключ выводится как есть.
    t = Text.translatable("key", args=[Text.literal("x")])
    assert t.to_plain_string() == "key"
    assert t.translation_key() == "key"


def test_translate_with_fallback_template():
    t = Text.translate_with_fallback("k", "%s has %s", [Text.literal("A"), Text.literal("B")])
    assert t.to_plain_string() == "A has B"
    assert t.component()["fallback"] == "%s has %s"


def test_format_translation_numbered_and_percent():
    a = [Text.literal("Steve"), Text.colored("Zombie", RED)]
    assert format_translation("%s was slain by %s", a).plain() == "Steve was slain by Zombie"
    assert format_translation("%2$s then %1$s", a).plain() == "Zombie then Steve"
    assert format_translation("100%% sure %s", a).plain() == "100% sure Steve"
    assert format_translation("%s %s %s", a).plain() == "%s %s %s"
    assert format_translation("%d", a).plain() == "%d"
    assert format_translation("50% off %s", a).plain() == "50% off Steve"


# ── legacy § ───────────────────────────────────────────────────────────
def test_from_legacy_green():
    t = Text.from_legacy("§aGreen§r")
    assert t.to_plain_string() == "Green"
    assert t.spans[0].style.color == GREEN


def test_from_legacy_bold():
    t = Text.from_legacy("§lBold")
    assert t.to_plain_string() == "Bold"
    assert t.spans[0].style.is_bold() is True


def test_legacy_color_resets_decorations():
    t = Text.legacy("§aGreen §lbold§r plain")
    assert t.plain() == "Green bold plain"
    assert t.spans[0].style.color == GREEN
    assert t.spans[1].style.is_bold() is True
    assert t.spans[2].style == Style()


def test_strip_legacy():
    t = Text.legacy("§aHi §lth§rere")
    assert t.strip_legacy().plain() == "Hi there"


def test_resolve_legacy_restyles_and_clears():
    styled = Text.styled("§cSteve", Style(bold=True))
    resolved = styled.resolved()
    assert resolved.plain() == "Steve"
    assert resolved.spans[0].style.color == RED
    assert resolved.spans[0].style.bold is False


# ── children / append ──────────────────────────────────────────────────
def test_append_children():
    t = Text.literal("a").append(Text.literal("b"))
    assert t.to_plain_string() == "ab"
    assert [s.text for s in t.spans] == ["a", "b"]


def test_append_str():
    assert Text.literal("x").append("y").to_plain_string() == "xy"


def test_slice_keeps_styles():
    t = Text.literal("x").append(Text.colored("y", GOLD)).with_color(RED)
    assert t.spans[0].style.color == RED
    assert t.spans[1].style.color == GOLD
    assert t.slice(1, 2).plain() == "y"


# ── click events ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "event,expected",
    [
        (ClickEvent.open_url("https://example.com"), {"action": "open_url", "url": "https://example.com"}),
        (ClickEvent.run_command("/help"), {"action": "run_command", "command": "/help"}),
        (ClickEvent.suggest_command("/seed"), {"action": "suggest_command", "command": "/seed"}),
        (ClickEvent.copy_to_clipboard("42"), {"action": "copy_to_clipboard", "value": "42"}),
        (ClickEvent.change_page(3), {"action": "change_page", "page": 3}),
        (ClickEvent.open_file("/tmp/a.png"), {"action": "open_file", "path": "/tmp/a.png"}),
    ],
)
def test_click_event_serialization(event, expected):
    t = Text.literal("link").with_style(Style(click=event))
    assert t.component()["click_event"] == expected


def test_click_custom_payload():
    t = Text.literal("x").with_style(Style(click=ClickEvent.custom("mine:id", {"a": 1})))
    assert t.component()["click_event"] == {"action": "custom", "id": "mine:id", "payload": {"a": 1}}


# ── hover events ───────────────────────────────────────────────────────
def test_hover_show_text():
    st = Style().with_hover_event(HoverEvent.show_text(Text.literal("tip")))
    t = Text.literal("x").with_style(st)
    assert t.component()["hover_event"] == {"action": "show_text", "value": {"text": "tip"}}


def test_hover_show_item():
    item = {"id": "minecraft:stone", "count": 1}
    st = Style().with_hover_event(HoverEvent.show_item(item))
    t = Text.literal("x").with_style(st)
    assert t.component()["hover_event"] == {"action": "show_item", "id": "minecraft:stone", "count": 1}


def test_hover_show_entity():
    entity = {"id": "minecraft:pig", "uuid": "0-0-0-0-0"}
    st = Style().with_hover_event(HoverEvent.show_entity(entity))
    t = Text.literal("x").with_style(st)
    assert t.component()["hover_event"] == {
        "action": "show_entity",
        "id": "minecraft:pig",
        "uuid": "0-0-0-0-0",
    }


# ── colors ─────────────────────────────────────────────────────────────
def test_named_color():
    assert named_color("red") == RED
    assert named_color("gold") == GOLD
    assert named_color("white") == WHITE
    assert named_color("nope") is None
    assert len(COLORS) == 16


def test_color_hex_in_json():
    t = Text.from_json({"text": "x", "color": "#FF0000"})
    assert t.spans[0].style.color == 0xFF0000


def test_color_name_in_json():
    t = Text.from_json({"text": "x", "color": "aqua"})
    assert t.spans[0].style.color == AQUA


# ── JSON round-trip ────────────────────────────────────────────────────
def test_json_roundtrip_children():
    t = Text.literal("a").append(Text.literal("b"))
    assert t.to_json() == {"text": "a", "extra": [{"text": "b"}]}
    back = Text.from_json(t.to_json())
    assert back.to_plain_string() == "ab"
    assert back == t


def test_json_roundtrip_style():
    t = Text.literal("x").with_style(Style(color=RED, bold=True, click=ClickEvent.run_command("/a")))
    j = t.to_json()
    back = Text.from_json(j)
    assert back.to_plain_string() == "x"
    assert back.spans[0].style.color == RED
    assert back.spans[0].style.bold is True
    assert back.spans[0].style.click == ClickEvent.run_command("/a")


# ── score / selector / keybind fallbacks ───────────────────────────────
def test_score_plain_fallback():
    # FALLBACK: без scoreboard строка пуста.
    t = Text.from_json({"score": {"name": "a", "objective": "b"}})
    assert t.to_plain_string() == ""


def test_selector_plain_fallback():
    # FALLBACK: без контекста селектор выводится шаблоном.
    t = Text.from_json({"selector": "@a"})
    assert t.to_plain_string() == "@a"


def test_keybind_plain_fallback():
    # FALLBACK: без биндов ключ выводится как есть.
    t = Text.from_json({"keybind": "key.jump"})
    assert t.to_plain_string() == "key.jump"


# ── style inheritance ──────────────────────────────────────────────────
def test_style_inherit():
    base = Style(color=RED, bold=True)
    child = Style(italic=True)
    child.inherit(base)
    assert child.color == RED
    assert child.bold is True
    assert child.italic is True


def test_legacy_format_color_clears_decorations():
    reset = Style(color=GOLD)
    styled = Style(color=GOLD, bold=True)
    out = legacy_format(styled, "c", reset)
    assert out.color == RED
    assert out.bold is False


def test_legacy_format_reset():
    reset = Style(color=GOLD)
    out = legacy_format(Style(bold=True, italic=True), "r", reset)
    assert out == reset


# ── copyable / translate helpers ───────────────────────────────────────
def test_copyable_structure():
    t = Text.copyable("42")
    assert t.plain() == "[42]"
    assert t.spans[1].style.click == ClickEvent.copy_to_clipboard("42")
    assert t.spans[1].style.color == GREEN
