# Порт horizon-client-core/src/component.rs (Minecraft 26.3).
#
# Текстовые компоненты из команд: `ComponentArgument` (`parse_snbt`) читает
# SNBT-значение (или JSON-объект), `ComponentSerialization` (`to_text`/
# `to_text_with`) превращает его в стилизованный текст с цветом, тенями,
# click/hover-событиями и встроенными объектами (`InlineObject`).
#
# ВАЖНО: это НЕ data components предметов (те живут в horizon-items/
# item_data.rs). Здесь общий слой текстовых компонентов, который команды
# (tellraw, title, ...) и CustomName используют для разбора/рендера.
#
# Компаунд в этом парсере — serde_json `Value`, то есть обычные Python
# dict/list/str/bool/int/float (не `Tag`). `Tag` используется только в
# `name_text` и в payload'е custom click-события.
#
# FALLBACK: не портированы зависимости: scoreboard.rs (`json_to_tag`/
# `tag_to_json`/`comp_text`), identifier.rs (`parse_identifier`),
# key_display.rs (`display_name`). Ниже они повторены локально в объёме,
# нужном этому файлу, и помечены `# FALLBACK`.

from __future__ import annotations

import copy
import math
import re
import struct
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from quadrix.core.text import (
    ClickEvent,
    InlineObject,
    Span,
    Style,
    Text,
    font_id as _text_font_id,
    named_color,
)
from quadrix.world.nbt import Tag, TagType

__all__ = [
    "SNBT_MAX_DEPTH",
    "parse_snbt",
    "untrusted_http_url",
    "style_event_object",
    "style_flag",
    "parse_click_event",
    "object_style",
    "hex_color",
    "shadow_color",
    "to_text",
    "to_text_with",
    "inline_object",
    "name_text",
    # FALLBACK-зависимости (см. docstring)
    "json_to_tag",
    "tag_to_json",
    "comp_text",
    "parse_identifier",
    "display_name",
]

# NbtAccounter предел: глубже — ошибка, а не переполнение стека.
SNBT_MAX_DEPTH = 512

# Символ, которым Text кодирует встроенный объект (ObjectContents).
OBJECT_MARKER = "\ufffc"


# ── парсер SNBT → JSON-значение (ComponentArgument) ───────────────────────
class _Parser:
    """`SnbtGrammar`, достаточная для компонентов."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.n = len(text)
        self.depth = 0

    def ws(self) -> None:
        while self.i < self.n and self.s[self.i] in " \t\n\r\x0b\x0c":
            self.i += 1

    def peek(self) -> Optional[str]:
        return self.s[self.i] if self.i < self.n else None

    def expect(self, c: str) -> None:
        self.ws()
        if self.peek() == c:
            self.i += 1
        else:
            raise ValueError("expected '{}'".format(c))

    def value(self) -> Any:
        self.ws()
        c = self.peek()
        if c == "{":
            if self.depth >= SNBT_MAX_DEPTH:
                raise ValueError("tag nesting too deep at {}".format(self.i))
            self.depth += 1
            v = self.object()
            self.depth -= 1
            return v
        if c == "[":
            if self.depth >= SNBT_MAX_DEPTH:
                raise ValueError("tag nesting too deep at {}".format(self.i))
            self.depth += 1
            v = self.array()
            self.depth -= 1
            return v
        if c is not None and c in "\"'":
            return self.string()
        word = self.unquoted()
        if word == "":
            raise ValueError("expected a value")
        if word == "true":
            return True
        if word == "false":
            return False
        # Хвостовые суффиксы b/s/l/f/d (в любом регистре).
        digits = word.rstrip("bBsSlLfFdD")
        # Числом считается только цифровая запись (и экспонента): `nan`
        # или `Infinity`, которые взял бы Rust-парс, остаются строкой.
        if any(
            (ch.isascii() and ch.isalpha() and ch not in "eE") for ch in digits
        ):
            return word
        # `digits.len() + 1 >= word.len()`: снят максимум один суффикс.
        if len(digits) + 1 >= len(word):
            if _I64_RE.match(digits):
                return int(digits)
            if _F64_RE.match(digits):
                return float(digits)
        return word

    def object(self) -> Dict[str, Any]:
        self.i += 1  # '{'
        m: Dict[str, Any] = {}
        self.ws()
        if self.peek() == "}":
            self.i += 1
            return m
        while True:
            self.ws()
            key = self.string()
            self.expect(":")
            m[key] = self.value()
            self.ws()
            p = self.peek()
            if p == ",":
                self.i += 1
            elif p == "}":
                self.i += 1
                return m
            else:
                raise ValueError("expected ',' or '}'")

    def array(self) -> List[Any]:
        self.i += 1  # '['
        out: List[Any] = []
        self.ws()
        # Типизированные массивы [B;...], [I;...], [L;...].
        if self.i + 1 < self.n and self.s[self.i] in "BIL" and self.s[self.i + 1] == ";":
            self.i += 2
        self.ws()
        if self.peek() == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value())
            self.ws()
            p = self.peek()
            if p == ",":
                self.i += 1
            elif p == "]":
                self.i += 1
                return out
            else:
                raise ValueError("expected ',' or ']'")

    def unquoted(self) -> str:
        start = self.i
        while self.i < self.n:
            c = self.s[self.i]
            if (c.isascii() and c.isalnum()) or c in "_-+.":
                self.i += 1
            else:
                break
        return self.s[start:self.i]

    def string(self) -> str:
        self.ws()
        q = self.peek()
        if q is None or q not in "\"'":
            return self.unquoted()
        self.i += 1
        out: List[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            self.i += 1
            if c == "\\":
                if self.i >= self.n:
                    break
                e = self.s[self.i]
                self.i += 1
                out.append({"n": "\n", "t": "\t"}.get(e, e))
            elif c == q:
                return "".join(out)
            else:
                out.append(c)
        raise ValueError("unterminated string")


# Rust `i64::from_str` / `f64::from_str` (без Python-подчёркиваний).
_I64_RE = re.compile(r"[+-]?[0-9]+\Z")
_F64_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def parse_snbt(input: str) -> Tuple[Any, int]:
    """`ComponentArgument`: разобрать SNBT/JSON, вернуть (значение, позиция)."""
    old = sys.getrecursionlimit()
    if old < 4096:
        sys.setrecursionlimit(4096)
    try:
        p = _Parser(input)
        value = p.value()
        return value, p.i
    finally:
        sys.setrecursionlimit(old)


# ── URL-фильтр (ExtraCodecs.UNTRUSTED_URI) ────────────────────────────────
def untrusted_http_url(url: str) -> bool:
    """Только http/https (регистр не важен). Всё прочее (`file:`, UNC,
    кастомная схема) отклоняется: `open_url` от сервера не должен запускать
    программы через системный обработчик URL."""
    scheme, sep, _rest = url.partition(":")
    if sep == "":
        return False
    return scheme.lower() == "http" or scheme.lower() == "https"


# ── click/hover события ───────────────────────────────────────────────────
def style_event_object(
    o: Dict[str, Any], modern: str, legacy: str
) -> Optional[Dict[str, Any]]:
    """`click_event`/`hover_event`, либо до-datafixer имена `clickEvent`/
    `hoverEvent`, которые ещё используют SNBT и старый чат-JSON."""
    v = o.get(modern)
    if v is None:
        v = o.get(legacy)
    return v if isinstance(v, dict) else None


def style_flag(v: Any) -> Optional[bool]:
    """Флаги стиля из JSON-булевых или SNBT `1b`/`0b` (число)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v != 0
    return None


def _event_str(e: Dict[str, Any], key: str) -> Optional[str]:
    v = e.get(key)
    return v if isinstance(v, str) else None


def _i32(value: int) -> Optional[int]:
    return value if -2147483648 <= value <= 2147483647 else None


def parse_click_event(e: Dict[str, Any]) -> Optional[ClickEvent]:
    """`ClickEvent.CODEC` плюс legacy-поле `value`, которое
    TextComponentHoverAndClickEventFix переименовывает в `url`/`command`/`page`."""
    action = e.get("action")
    if action == "open_url":
        u = _event_str(e, "url")
        if u is None:
            u = _event_str(e, "value")
        if u is None or not untrusted_http_url(u):
            return None
        return ClickEvent.open_url(u)
    if action == "change_page":
        page: Optional[int] = None
        p = e.get("page")
        if isinstance(p, int) and not isinstance(p, bool):
            page = p
        else:
            v = e.get("value")
            if isinstance(v, int) and not isinstance(v, bool):
                page = v
            elif isinstance(v, str):
                try:
                    page = int(v)
                except ValueError:
                    page = None
        if page is None:
            return None
        page = _i32(page)
        if page is None or page < 1:
            return None
        return ClickEvent.change_page(page)
    if action == "suggest_command":
        c = _event_str(e, "command")
        if c is None:
            c = _event_str(e, "value")
        if c is None:
            return None
        return ClickEvent.suggest_command(c)
    if action == "run_command":
        c = _event_str(e, "command")
        if c is None:
            c = _event_str(e, "value")
        if c is None:
            return None
        return ClickEvent.run_command(c)
    if action == "copy_to_clipboard":
        v = _event_str(e, "value")
        if v is None:
            return None
        return ClickEvent.copy_to_clipboard(v)
    # ClickEvent.ShowDialog: id диалога в реестре `minecraft:dialog` или сам
    # диалог; сервер может его прислать (isAllowedFromServer).
    if action == "show_dialog":
        if "dialog" not in e:
            return None
        return ClickEvent.show_dialog(json_to_tag(e["dialog"]))
    if action == "custom":
        raw_id = _event_str(e, "id")
        if raw_id is None:
            return None
        ident = parse_identifier(raw_id)
        if ident is None:
            return None
        payload = None
        if "payload" in e and e["payload"] is not None:
            payload = json_to_tag(e["payload"])
        return ClickEvent.custom(ident, payload)
    return None


# ── разбор стиля ──────────────────────────────────────────────────────────
def object_style(o: Dict[str, Any]) -> Style:
    """Поля стиля компонента-объекта."""
    style = Style()
    c = o.get("color")
    if isinstance(c, str):
        style.color = named_color(c)
        if style.color is None:
            style.color = hex_color(c)
    if "shadow_color" in o:
        style.shadow_color = shadow_color(o["shadow_color"])
    style.bold = style_flag(o.get("bold"))
    style.italic = style_flag(o.get("italic"))
    style.underlined = style_flag(o.get("underlined"))
    style.strikethrough = style_flag(o.get("strikethrough"))
    style.obfuscated = style_flag(o.get("obfuscated"))
    if "font" in o:
        style.font = _font_id(o["font"])
    # ClickEvent.CODEC: действия строки чата. Компонент от сервера никогда
    # не открывает файл.
    e = style_event_object(o, "click_event", "clickEvent")
    if e is not None:
        style.click = parse_click_event(e)
    # HoverEvent.ShowText, ShowItem и ShowEntity.
    e = style_event_object(o, "hover_event", "hoverEvent")
    if e is not None:
        action = e.get("action")
        if action == "show_text":
            # Современное `value`, либо старые `contents`/вложенный `text`.
            value = e.get("value")
            if value is None:
                value = e.get("contents")
            if value is None:
                value = e.get("text")
            if value is not None:
                style.hover = to_text(value, lambda s: Text.literal(s))
        elif action == "show_item" and isinstance(e.get("id"), str):
            style.hover_item = dict(e)
        elif action == "show_entity" and isinstance(e.get("id"), str):
            style.hover_entity = dict(e)
    insertion = o.get("insertion")
    if isinstance(insertion, str):
        style.insertion = insertion
    return style


def hex_color(c: str) -> Optional[int]:
    """`TextColor.parseColor` для `#...`: `Integer.parseInt(rest, 16)`, и
    только в диапазоне `0..=0xFFFFFF`."""
    if not isinstance(c, str) or not c.startswith("#"):
        return None
    body = c[1:]
    try:
        value = int(body, 16)
    except ValueError:
        return None
    if 0 <= value <= 0xFFFFFF:
        return value
    return None


def _to_f32(x: float) -> float:
    return struct.unpack(">f", struct.pack(">f", x))[0]


def shadow_color(value: Any) -> Optional[int]:
    """`Style.shadow_color`: упакованный ARGB int или нормализованный RGBA-массив."""
    if isinstance(value, int) and not isinstance(value, bool):
        v = _i32(value)
        return (v & 0xFFFFFFFF) if v is not None else None
    if not isinstance(value, list):
        return None
    if len(value) != 4:
        return None
    channels: List[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, (int, float)):
            return None
        # ExtraCodecs.ARGB_COLOR_CODEC читает float; ARGB.as8BitChannel
        # округляет вниз нормализованный канал, умноженный на 255.
        f = _to_f32(float(channel))
        if not math.isfinite(f) or not (0.0 <= f <= 1.0):
            return None
        channels.append(int(math.floor(f * 255.0)))
    return (channels[3] << 24) | (channels[0] << 16) | (channels[1] << 8) | channels[2]


# ── serde_json Value → Text (ComponentSerialization) ──────────────────────
def _number_to_string(n: Any) -> str:
    """`Value::Number(n).to_string()` из serde_json."""
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    return repr(n)


def _no_contents(_o: Dict[str, Any]) -> Optional[Text]:
    return None


def _empty_resolve(_s: str) -> Text:
    return Text.empty()


def to_text(v: Any, resolve: Optional[Callable[[str], Text]] = None) -> Text:
    """`ComponentSerialization.CODEC` в текст. `selector`-компоненты
    разрешает `resolve` (ComponentUtils.updateForEntity)."""
    if resolve is None:
        resolve = _empty_resolve
    return to_text_with(v, resolve, _no_contents)


def to_text_with(
    v: Any,
    resolve: Callable[[str], Text],
    contents: Optional[Callable[[Dict[str, Any]], Optional[Text]]] = None,
) -> Text:
    """`to_text` с хуком `contents`, разрешающим прочее содержимое (`nbt`)."""
    if contents is None:
        contents = _no_contents
    if v is None:
        return Text.empty()
    if isinstance(v, bool):
        return Text.literal("true" if v else "false")
    if isinstance(v, (int, float)):
        return Text.literal(_number_to_string(v))
    if isinstance(v, str):
        return Text.literal(v)
    # Список — это первый элемент, остальные становятся сиблингами.
    if isinstance(v, list):
        if not v:
            return Text.empty()
        first = v[0]
        rest = v[1:]
        base = to_text_with(first, resolve, contents)
        # Сиблинги берут собственный стиль первого компонента, даже если его
        # текст пуст.
        if isinstance(first, dict):
            style = object_style(first)
        elif base.spans:
            style = copy.copy(base.spans[0].style)
        else:
            style = Style()
        for sibling in rest:
            base.push(to_text_with(sibling, resolve, contents).with_style(style))
        return base
    if not isinstance(v, dict):
        return Text.literal(str(v))

    o = v
    style = object_style(o)
    resolved = contents(o)
    if resolved is not None:
        content = resolved
    else:
        inline = inline_object(o, resolve, contents)
        if inline is not None:
            content = Text.literal(OBJECT_MARKER)
            content.spans[0].style.inline_object = inline
        elif "text" in o:
            t = o["text"]
            content = Text.literal(t if isinstance(t, str) else _number_to_string(t))
        elif isinstance(o.get("translate"), str):
            key = o["translate"]
            with_list = o.get("with")
            args: List[Text] = []
            if isinstance(with_list, list):
                args = [to_text_with(x, resolve, contents) for x in with_list]
            translated = Text.translate(key, args)
            fallback = o.get("fallback")
            if isinstance(fallback, str) and translated.plain() == key:
                content = Text.translate(fallback, args)
            else:
                content = translated
        elif isinstance(o.get("selector"), str):
            content = resolve(o["selector"])
        elif isinstance(o.get("keybind"), str):
            # FALLBACK: key_display.rs не портирован — ключ выводится как есть.
            content = display_name(o["keybind"])
        else:
            content = Text.empty()

    out = content.with_style(style)
    extra = o.get("extra")
    if isinstance(extra, list):
        for child in extra:
            out.push(to_text_with(child, resolve, contents).with_style(style))
    if "object" in o or "player" in o or "sprite" in o:
        out.with_component(dict(o))
    return out


def _short_id(id: str) -> str:
    ns, sep, path = id.partition(":")
    if sep and ns == "minecraft":
        return path
    return id


def inline_object(
    object: Dict[str, Any],
    resolve: Callable[[str], Text],
    contents: Optional[Callable[[Dict[str, Any]], Optional[Text]]] = None,
) -> Optional[InlineObject]:
    """`minecraft:object` (PlayerSprite/AtlasSprite) внутри компонента."""
    if contents is None:
        contents = _no_contents
    kind = object.get("object")
    if not isinstance(kind, str):
        kind = None
    fallback: Optional[str] = None
    if "fallback" in object and object["fallback"] is not None:
        fallback = to_text_with(object["fallback"], resolve, contents).plain()

    player_kind = kind == "player" or kind is None
    if player_kind and "player" in object:
        profile = object["player"]
        # PlayerSprite.defaultFallback.
        if fallback is None:
            name: Optional[str] = None
            if isinstance(profile, str):
                name = profile
            elif isinstance(profile, dict) and isinstance(profile.get("name"), str):
                name = profile["name"]
            fallback = "[{} head]".format(name) if name is not None else "[unknown player head]"
        hat = object.get("hat")
        hat_bool = hat if isinstance(hat, bool) else True
        return InlineObject.player(profile, hat_bool, fallback)

    atlas_kind = kind == "atlas" or kind is None
    if atlas_kind and "sprite" in object:
        atlas_v = object.get("atlas")
        atlas = atlas_v if isinstance(atlas_v, str) else "minecraft:blocks"
        sprite_v = object.get("sprite")
        if not isinstance(sprite_v, str):
            return None
        sprite = sprite_v
        # AtlasSprite.defaultFallback: короткие имена, атлас кроме blocks.
        if fallback is None:
            if _short_id(atlas) == "blocks":
                fallback = "[{}]".format(_short_id(sprite))
            else:
                fallback = "[{}@{}]".format(_short_id(sprite), _short_id(atlas))
        return InlineObject.atlas_obj(atlas, sprite, fallback)
    return None


# ── CustomName как текст ──────────────────────────────────────────────────
def name_text(tag: Tag) -> Text:
    """`CustomName`: строка сохраняет legacy-коды, всё прочее — компонент."""
    if isinstance(tag, Tag) and tag.tag_type == TagType.String:
        return Text.legacy(tag.str_val if tag.str_val is not None else "")
    return comp_text(tag_to_json(tag))


# ── FALLBACK-зависимости (см. docstring модуля) ───────────────────────────
# FALLBACK: identifier.rs не портирован — локальная проверка resource location.
_NS_RE = re.compile(r"[a-z0-9_.-]+\Z")
_PATH_RE = re.compile(r"[a-z0-9/._-]+\Z")


def parse_identifier(s: Any) -> Optional[str]:
    """`ResourceLocation.tryParse`: `namespace:path`, namespace по умолчанию
    `minecraft`. Валидны только `[a-z0-9_.-]` и `[a-z0-9/._-]`."""
    if not isinstance(s, str):
        return None
    if ":" in s:
        ns, _, path = s.partition(":")
    else:
        ns, path = "minecraft", s
    if not _NS_RE.match(ns):
        return None
    if not _PATH_RE.match(path):
        return None
    return ns + ":" + path


def _font_id(v: Any) -> Optional[str]:
    """Rust `text::font_id` валидирует идентификатор; `text.font_id` из
    quadrix/core/text.py — нет, поэтому дополнительно проверяем."""
    if not isinstance(v, str):
        return None
    if ":" in v:
        return _text_font_id(v) if parse_identifier(v) is not None else None
    return parse_identifier(v)


def display_name(key: str) -> Text:
    """FALLBACK: key_display.rs не портирован — ключ бинда выводится как есть."""
    return Text(spans=[Span(key, Style())], source={"keybind": key})


# FALLBACK: scoreboard.rs не портирован — Tag ↔ JSON и текстовые хелперы.
def json_to_tag(value: Any) -> Optional[Tag]:
    """JSON-значение → `Tag` (как `scoreboard::json_to_tag`)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return Tag(TagType.Byte, byte_val=1 if value else 0)
    if isinstance(value, int):
        if -2147483648 <= value <= 2147483647:
            return Tag(TagType.Int, int_val=value)
        if -(2 ** 63) <= value <= 2 ** 63 - 1:
            return Tag(TagType.Long, long_val=value)
        return Tag(TagType.Double, double_val=float(value))
    if isinstance(value, float):
        return Tag(TagType.Double, double_val=value)
    if isinstance(value, str):
        return Tag(TagType.String, str_val=value)
    if isinstance(value, list):
        return Tag(TagType.List, list_val=[json_to_tag(v) for v in value])
    if isinstance(value, dict):
        return Tag(
            TagType.Compound,
            compound_val={k: json_to_tag(v) for k, v in value.items()},
        )
    return Tag(TagType.String, str_val=str(value))


def tag_to_json(tag: Any) -> Any:
    """`Tag` → JSON-значение (как `scoreboard::tag_to_json`)."""
    if not isinstance(tag, Tag):
        return tag
    tt = tag.tag_type
    if tt == TagType.Byte:
        return int(tag.byte_val or 0)
    if tt == TagType.Short:
        return int(tag.short_val or 0)
    if tt == TagType.Int:
        return int(tag.int_val or 0)
    if tt == TagType.Long:
        return int(tag.long_val or 0)
    if tt == TagType.Float:
        return float(tag.float_val or 0.0)
    if tt == TagType.Double:
        return float(tag.double_val or 0.0)
    if tt == TagType.String:
        return tag.str_val if tag.str_val is not None else ""
    if tt == TagType.ByteArray:
        return [b if b < 128 else b - 256 for b in (tag.bytes_val or b"")]
    if tt == TagType.IntArray:
        return list(tag.intarray_val or [])
    if tt == TagType.LongArray:
        return list(tag.longarray_val or [])
    if tt == TagType.List:
        return [tag_to_json(t) for t in (tag.list_val or [])]
    if tt == TagType.Compound:
        return {k: tag_to_json(v) for k, v in (tag.compound_val or {}).items()}
    return None


def comp_text(value: Any) -> Text:
    """`scoreboard::comp_text`: JSON-компонент → текст (`ComponentSerialization`)."""
    return to_text(value, _empty_resolve)
