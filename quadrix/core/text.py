# Порт horizon-client-core/src/text.rs (Minecraft 26.3).
#
# Стилизованный текст: набор Span (текст + Style) с кодами ChatFormatting
# (цвета и декорации), переводимые сообщения как TranslatableContents
# (`%s`, `%1$s`, `%%`) и legacy-коды `§`.
#
# Text хранит последовательность span'ов и, если он построен через
# конструкторы ниже, исходный `Component` (его JSON-форму) — чтобы отправить
# vanilla-клиенту. Сравнение (==) учитывает только span'ы.
#
# FALLBACK: lang.rs ещё не портирован (quadrix/core/lang.py). Пока язык не
# загружен, `ClientLanguage.getOrDefault` возвращает сам ключ — это поведение
# и повторено в `_lang_get`/`_lang_get_or`. Когда lang портят, достаточно
# выставить `_CURRENT_LANG`.

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "COLORS",
    "BLACK",
    "GRAY",
    "DARK_GRAY",
    "GREEN",
    "AQUA",
    "RED",
    "YELLOW",
    "GOLD",
    "WHITE",
    "LIGHT_PURPLE",
    "DARK_PURPLE",
    "STYLE_KEYS",
    "named_color",
    "font_id",
    "ClickEvent",
    "HoverEvent",
    "InlineObject",
    "Style",
    "Span",
    "Text",
    "legacy_format",
    "format_translation",
]

# ── Цвета ChatFormatting по индексу legacy-кода 0..=15 ────────────────────
COLORS: List[Tuple[str, str, int]] = [
    ("0", "black", 0x000000),
    ("1", "dark_blue", 0x0000AA),
    ("2", "dark_green", 0x00AA00),
    ("3", "dark_aqua", 0x00AAAA),
    ("4", "dark_red", 0xAA0000),
    ("5", "dark_purple", 0xAA00AA),
    ("6", "gold", 0xFFAA00),
    ("7", "gray", 0xAAAAAA),
    ("8", "dark_gray", 0x555555),
    ("9", "blue", 0x5555FF),
    ("a", "green", 0x55FF55),
    ("b", "aqua", 0x55FFFF),
    ("c", "red", 0xFF5555),
    ("d", "light_purple", 0xFF55FF),
    ("e", "yellow", 0xFFFF55),
    ("f", "white", 0xFFFFFF),
]
BLACK = 0x000000
GRAY = 0xAAAAAA
DARK_GRAY = 0x555555
GREEN = 0x55FF55
AQUA = 0x55FFFF
RED = 0xFF5555
YELLOW = 0xFFFF55
GOLD = 0xFFAA00
WHITE = 0xFFFFFF
LIGHT_PURPLE = 0xFF55FF
DARK_PURPLE = 0xAA00AA


def named_color(name: str) -> Optional[int]:
    """`ChatFormatting.getByName`: имя → RGB, либо None."""
    for _code, n, v in COLORS:
        if n == name:
            return v
    return None


def font_id(v: Any) -> Optional[str]:
    """Поле `font` стиля: идентификатор (`alt` это `minecraft:alt`)."""
    if not isinstance(v, str):
        return None
    if ":" not in v:
        return "minecraft:" + v
    return v


# ── Стиль языка (язык ещё не портирован) ──────────────────────────────────
_CURRENT_LANG: Any = None


def _lang_get(key: str) -> Optional[str]:
    """`lang::current().get(key)` — None, если язык не загружен."""
    if _CURRENT_LANG is None:
        return None
    return _CURRENT_LANG.get(key)


def _lang_get_or_key(key: str) -> str:
    """`lang::get`: перевод, иначе сам ключ."""
    v = _lang_get(key)
    return v if v is not None else key


# ── ClickEvent / HoverEvent / InlineObject ────────────────────────────────
@dataclass
class ClickEvent:
    """Действие клика компонента текста (ClickEvent)."""

    action: str
    url: Optional[str] = None
    page: Optional[int] = None
    command: Optional[str] = None
    value: Optional[str] = None
    dialog: Any = None
    id: Optional[str] = None
    payload: Any = None
    path: Optional[str] = None

    @staticmethod
    def open_url(url: str) -> "ClickEvent":
        return ClickEvent("open_url", url=url)

    @staticmethod
    def change_page(page: int) -> "ClickEvent":
        return ClickEvent("change_page", page=page)

    @staticmethod
    def suggest_command(command: str) -> "ClickEvent":
        return ClickEvent("suggest_command", command=command)

    @staticmethod
    def run_command(command: str) -> "ClickEvent":
        return ClickEvent("run_command", command=command)

    @staticmethod
    def copy_to_clipboard(value: str) -> "ClickEvent":
        return ClickEvent("copy_to_clipboard", value=value)

    @staticmethod
    def show_dialog(dialog: Any) -> "ClickEvent":
        return ClickEvent("show_dialog", dialog=dialog)

    @staticmethod
    def custom(id: str, payload: Any = None) -> "ClickEvent":
        return ClickEvent("custom", id=id, payload=payload)

    @staticmethod
    def open_file(path: str) -> "ClickEvent":
        return ClickEvent("open_file", path=path)


@dataclass
class HoverEvent:
    """Событие наведения (HoverEvent.ShowText/ShowItem/ShowEntity)."""

    action: str
    value: Any

    @staticmethod
    def show_text(text: "Text") -> "HoverEvent":
        return HoverEvent("show_text", text)

    @staticmethod
    def show_item(item: Dict[str, Any]) -> "HoverEvent":
        return HoverEvent("show_item", item)

    @staticmethod
    def show_entity(entity: Dict[str, Any]) -> "HoverEvent":
        return HoverEvent("show_entity", entity)


@dataclass
class InlineObject:
    """Непроизвольный `minecraft:object`, встроенный в компонент текста."""

    kind: str
    fallback: str
    profile: Any = None
    hat: bool = False
    atlas: Optional[str] = None
    sprite: Optional[str] = None

    @staticmethod
    def player(profile: Any, hat: bool, fallback: str) -> "InlineObject":
        return InlineObject("player", fallback, profile=profile, hat=hat)

    @staticmethod
    def atlas_obj(atlas: str, sprite: str, fallback: str) -> "InlineObject":
        return InlineObject("atlas", fallback, atlas=atlas, sprite=sprite)

    def get_fallback(self) -> str:
        return self.fallback


# ── Style ─────────────────────────────────────────────────────────────────
@dataclass
class Style:
    """Стиль текста; поля None наследуются от объемлющего стиля."""

    color: Optional[int] = None
    # `shadow_color` как упакованный ARGB. Ноль подавляет тени.
    shadow_color: Optional[int] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underlined: Optional[bool] = None
    strikethrough: Optional[bool] = None
    obfuscated: Optional[bool] = None
    click: Optional[ClickEvent] = None
    # Текст подсказки (HoverEvent.ShowText).
    hover: Optional["Text"] = None
    # `HoverEvent.ShowItem`: объект события `{id, count?, components?}`.
    hover_item: Optional[Dict[str, Any]] = None
    # `HoverEvent.ShowEntity`: объект события `{id, uuid, name?}`.
    hover_entity: Optional[Dict[str, Any]] = None
    # `Style.insertion`: текст, который Shift-клик кладёт в чат.
    insertion: Optional[str] = None
    # Шрифт (`FontDescription.Resource`), полный id вроде `minecraft:alt`.
    font: Optional[str] = None
    # Метаданные одного span'а U+FFFC; никогда не наследуется.
    inline_object: Optional[InlineObject] = None

    @staticmethod
    def color_style(c: int) -> "Style":
        """Rust `Style::color(c)` — вспомогательный конструктор."""
        return Style(color=c)

    def inherit(self, base: "Style") -> None:
        """Style.applyTo: заполнить незаданные поля из `base`."""
        if self.color is None:
            self.color = base.color
        if self.shadow_color is None:
            self.shadow_color = base.shadow_color
        if self.bold is None:
            self.bold = base.bold
        if self.italic is None:
            self.italic = base.italic
        if self.underlined is None:
            self.underlined = base.underlined
        if self.strikethrough is None:
            self.strikethrough = base.strikethrough
        if self.obfuscated is None:
            self.obfuscated = base.obfuscated
        if self.click is None:
            self.click = base.click
        # Один HoverEvent: три его вида наследуются вместе, поэтому стиль со
        # своим событием не подхватывает другой вид из `base`.
        if self.hover is None and self.hover_item is None and self.hover_entity is None:
            self.hover = base.hover
            self.hover_item = base.hover_item
            self.hover_entity = base.hover_entity
        if self.insertion is None:
            self.insertion = base.insertion
        if self.font is None:
            self.font = base.font

    def is_bold(self) -> bool:
        return self.bold is True

    def is_italic(self) -> bool:
        return self.italic is True

    def with_hover_event(self, event: "HoverEvent") -> "Style":
        """Удобный помощник: разложить HoverEvent по трём полям стиля."""
        if event.action == "show_text":
            self.hover = event.value if isinstance(event.value, Text) else Text.literal(str(event.value))
        elif event.action == "show_item":
            self.hover_item = event.value
        elif event.action == "show_entity":
            self.hover_entity = event.value
        return self


@dataclass
class Span:
    """Прогон стилизованного текста."""

    text: str
    style: Style = field(default_factory=Style)


# Ключи JSON-стиля компонента (Rust `STYLE_KEYS`).
STYLE_KEYS: List[str] = [
    "color",
    "shadow_color",
    "bold",
    "italic",
    "underlined",
    "strikethrough",
    "obfuscated",
    "click_event",
    "hover_event",
    "insertion",
    "font",
]


def _style_json(style: Style) -> List[Tuple[str, Any]]:
    """`Style.Serializer`: поля, которые задаёт стиль."""
    out: List[Tuple[str, Any]] = []
    if style.color is not None:
        name = None
        for _code, n, v in COLORS:
            if v == style.color:
                name = n
                break
        out.append(("color", name if name is not None else "#{:06X}".format(style.color)))
    if style.shadow_color is not None:
        shadow = style.shadow_color
        signed = shadow - (1 << 32) if shadow >= (1 << 31) else shadow
        out.append(("shadow_color", signed))
    for key, flag in (
        ("bold", style.bold),
        ("italic", style.italic),
        ("underlined", style.underlined),
        ("strikethrough", style.strikethrough),
        ("obfuscated", style.obfuscated),
    ):
        if flag is not None:
            out.append((key, flag))
    if style.click is not None:
        out.append(("click_event", _click_json(style.click)))
    if style.hover is not None:
        out.append(("hover_event", {"action": "show_text", "value": style.hover.component()}))
    elif style.hover_item is not None:
        event = dict(style.hover_item)
        event["action"] = "show_item"
        out.append(("hover_event", event))
    elif style.hover_entity is not None:
        event = dict(style.hover_entity)
        event["action"] = "show_entity"
        out.append(("hover_event", event))
    if style.insertion is not None:
        out.append(("insertion", style.insertion))
    if style.font is not None:
        out.append(("font", style.font))
    return out


def _click_json(click: ClickEvent) -> Dict[str, Any]:
    if click.action == "open_url":
        return {"action": "open_url", "url": click.url}
    if click.action == "change_page":
        return {"action": "change_page", "page": click.page}
    if click.action == "suggest_command":
        return {"action": "suggest_command", "command": click.command}
    if click.action == "copy_to_clipboard":
        return {"action": "copy_to_clipboard", "value": click.value}
    if click.action == "run_command":
        return {"action": "run_command", "command": click.command}
    if click.action == "show_dialog":
        # FALLBACK: scoreboard::tag_to_json ещё не портирован — Tag → JSON.
        return {"action": "show_dialog", "dialog": _tag_to_json(click.dialog)}
    if click.action == "custom":
        event: Dict[str, Any] = {"action": "custom", "id": click.id}
        if click.payload is not None:
            event["payload"] = _tag_to_json(click.payload)
        return event
    if click.action == "open_file":
        return {"action": "open_file", "path": click.path}
    return {"action": click.action}


def _tag_to_json(tag: Any) -> Any:
    # FALLBACK: scoreboard::tag_to_json pending. Примитивы/контейнеры Python
    # возвращаются как есть, `Tag` из quadrix.world.nbt — по его payload.
    if tag is None or isinstance(tag, (str, int, float, bool)):
        return tag
    if isinstance(tag, (list, tuple)):
        return [_tag_to_json(t) for t in tag]
    if isinstance(tag, dict):
        return {k: _tag_to_json(v) for k, v in tag.items()}
    compound = getattr(tag, "compound_val", None)
    if compound is not None:
        return {k: _tag_to_json(v) for k, v in compound.items()}
    lst = getattr(tag, "list_val", None)
    if lst is not None:
        return [_tag_to_json(t) for t in lst]
    for attr in ("str_val", "int_val", "long_val", "short_val", "byte_val",
                 "float_val", "double_val"):
        val = getattr(tag, attr, None)
        if val is not None:
            return val
    return str(tag)


def legacy_format(style: Style, code: str, reset: Style) -> Style:
    """`Style.applyLegacyFormat` для кода после `§`; `§r` возвращает к `reset`."""
    code = code.lower()
    for c, _name, v in COLORS:
        if c == code:
            # Цвет сбрасывает декорации.
            s = Style(
                color=v,
                bold=False,
                italic=False,
                underlined=False,
                strikethrough=False,
                obfuscated=False,
            )
            s.shadow_color = style.shadow_color
            s.click = style.click
            s.hover = style.hover
            s.hover_item = style.hover_item
            s.hover_entity = style.hover_entity
            s.insertion = style.insertion
            s.font = style.font
            s.inline_object = style.inline_object
            return s
    s = copy.copy(style)
    if code == "k":
        s.obfuscated = True
    elif code == "l":
        s.bold = True
    elif code == "m":
        s.strikethrough = True
    elif code == "n":
        s.underlined = True
    elif code == "o":
        s.italic = True
    elif code == "r":
        s = copy.copy(reset)
    return s


def format_translation(template: str, args: Sequence["Text"]) -> "Text":
    """TranslatableContents.decomposeTemplate: `%s` берёт следующий аргумент,
    `%n$s` — нумерованный, `%%` — знак процента. Некорректные шаблоны
    показываются дословно."""
    out = Text()
    literal: List[str] = []
    next_index = 0
    chars = list(template)
    i = 0
    while i < len(chars):
        if chars[i] != "%":
            literal.append(chars[i])
            i += 1
            continue
        # %(?:(\d+)\$)?([A-Za-z%]|$)
        j = i + 1
        number: Optional[int] = None
        digits_start = j
        while j < len(chars) and "0" <= chars[j] <= "9":
            j += 1
        if j > digits_start and j < len(chars) and chars[j] == "$":
            try:
                number = int("".join(chars[digits_start:j]))
            except ValueError:
                number = None
            j += 1
        else:
            j = digits_start
        conversion = chars[j] if j < len(chars) else None
        if conversion == "%" and number is None:
            literal.append("%")
            i = j + 1
        elif conversion is not None and not ("A" <= conversion <= "Z" or "a" <= conversion <= "z") \
                and conversion != "%":
            # Не спецификатор вовсе: знак процента литеральный.
            literal.append("%")
            i += 1
        elif conversion == "s":
            if number is not None:
                index = number - 1
            else:
                next_index += 1
                index = next_index - 1
            if index < 0 or index >= len(args):
                return Text.literal(template)
            if literal:
                out.spans.append(Span("".join(literal), Style()))
                literal = []
            for s in args[index].spans:
                out.spans.append(Span(s.text, copy.copy(s.style)))
            i = j + 1
        else:
            return Text.literal(template)
    if literal:
        out.spans.append(Span("".join(literal), Style()))
    return out


# ── Text ──────────────────────────────────────────────────────────────────
@dataclass(eq=False)
class Text:
    """Прогон стилизованных span'ов и `Component`, из которого они пришли
    (его JSON-форма) для отправки vanilla-клиентам. Равенство — по span'ам."""

    spans: List[Span] = field(default_factory=list)
    source: Optional[Any] = None

    # ── сравнение ─────────────────────────────────────────────────────
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Text):
            return NotImplemented
        return self.spans == other.spans

    def __ne__(self, other: object) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self) -> str:
        return "Text({!r})".format(self.plain())

    # ── удобные свойства ──────────────────────────────────────────────
    @property
    def style(self) -> Style:
        """Стиль первого span'а (создаётся при необходимости)."""
        if not self.spans:
            self.spans.append(Span("", Style()))
        return self.spans[0].style

    # ── конструкторы ──────────────────────────────────────────────────
    @staticmethod
    def empty() -> "Text":
        return Text()

    @staticmethod
    def literal(s: Any) -> "Text":
        text = s if isinstance(s, str) else str(s)
        if text == "":
            return Text()
        return Text(spans=[Span(text, Style())], source={"text": text})

    @staticmethod
    def styled(s: Any, style: Style) -> "Text":
        return Text.literal(s).with_style(style)

    @staticmethod
    def colored(s: Any, color: int) -> "Text":
        return Text.styled(s, Style(color=color))

    @staticmethod
    def copyable(s: Any) -> "Text":
        """ComponentUtils.copyOnClickText: зелёная ссылка на буфер обмена."""
        s = s if isinstance(s, str) else str(s)
        return (
            Text.literal("[")
            .append(Text.styled(
                s,
                Style(
                    color=GREEN,
                    click=ClickEvent.copy_to_clipboard(s),
                    hover=Text.translate("chat.copy.click", []),
                ),
            ))
            .append("]")
        )

    @staticmethod
    def teleport_link(x: int, y: Optional[int], z: int) -> "Text":
        """Ссылка координат LocateCommand: предложить телепорт без выполнения."""
        ys = "~" if y is None else str(y)
        coords = Text.tr("chat.coordinates", [x, ys, z])
        style = Style(
            color=GREEN,
            click=ClickEvent.suggest_command("/tp @s {} {} {}".format(x, ys, z)),
            hover=Text.translate("chat.coordinates.tooltip", []),
        )
        return Text.literal("[").append(coords).append("]").with_style(style)

    @staticmethod
    def translate(key: str, args: Optional[Sequence["Text"]] = None) -> "Text":
        """Component.translatable(key, args) на текущем языке."""
        args = list(args) if args else []
        t = format_translation(_lang_get_or_key(key), args)
        c: Dict[str, Any] = {"translate": key}
        if args:
            c["with"] = [a.argument() for a in args]
        t.source = c
        return t

    # удобный алиас для тестов/вызывающих
    translatable = translate

    @staticmethod
    def translate_with_fallback(key: str, fallback: str, args: Optional[Sequence["Text"]] = None) -> "Text":
        """Component.translatableWithFallback: `translate` с `fallback`, если в
        языке нет `key`."""
        args = list(args) if args else []
        template = _lang_get(key)
        if template is None:
            template = fallback
        t = format_translation(template, args)
        c: Dict[str, Any] = {"translate": key, "fallback": fallback}
        if args:
            c["with"] = [a.argument() for a in args]
        t.source = c
        return t

    @staticmethod
    def option_name_value(caption: "Text", value: "Text") -> "Text":
        """CommonComponents.optionNameValue: "Caption: value"."""
        return Text.translate_with_fallback("options.generic_value", "%s: %s", [caption, value])

    @staticmethod
    def tr(key: str, args: Optional[Sequence[Any]] = None) -> "Text":
        """Переводимое сообщение с простыми строковыми аргументами."""
        texts = [Text.literal(a) for a in (args or [])]
        return Text.translate(key, texts)

    # ── сборка дерева ─────────────────────────────────────────────────
    def append(self, other: Any) -> "Text":
        self.push(other)
        return self

    def push(self, other: Any) -> None:
        """MutableComponent.append: `other` становится сиблингом."""
        other = Text.literal(other) if isinstance(other, str) else other
        sibling = other.component()
        if not self.spans and self.source is None:
            root: Any = {"text": ""}
        else:
            c = self.component()
            if isinstance(c, dict) and any(k in c for k in STYLE_KEYS):
                root = {"text": "", "extra": [c]}
            else:
                root = c
        if isinstance(root, dict):
            extra = root.get("extra")
            if isinstance(extra, list):
                extra.append(sibling)
            else:
                root["extra"] = [sibling]
        self.source = root
        self.spans.extend(other.spans)

    def with_style(self, style: Style) -> "Text":
        """Применить `style` под каждым span'ом (MutableComponent.withStyle)."""
        for span in self.spans:
            span.style.inherit(style)
        c = self.component()
        if isinstance(c, dict):
            for k, v in _style_json(style):
                c.setdefault(k, v)
        self.source = c
        return self

    def with_component_fields(self, fields: Sequence[Tuple[str, Any]]) -> "Text":
        """Поля стиля, которых нет в span'ах (сущность-hover, insertion),
        выставленные только на компоненте для vanilla."""
        c = self.component()
        if isinstance(c, dict):
            for k, v in fields:
                c.setdefault(k, v)
        self.source = c
        return self

    def with_component(self, component: Any) -> "Text":
        """Те же span'ы, отправленные vanilla как `component`."""
        self.source = component
        return self

    def with_color(self, color: int) -> "Text":
        return self.with_style(Style(color=color))

    def italic(self) -> "Text":
        return self.with_style(Style(italic=True))

    def underlined(self) -> "Text":
        return self.with_style(Style(underlined=True))

    def bold(self) -> "Text":
        return self.with_style(Style(bold=True))

    # ── контент / сериализация ────────────────────────────────────────
    def translation_key(self) -> Optional[str]:
        if not isinstance(self.source, dict):
            return None
        v = self.source.get("translate")
        return v if isinstance(v, str) else None

    def component(self) -> Any:
        """`Component` в JSON vanilla (ComponentSerialization)."""
        if self.source is not None:
            return copy.deepcopy(self.source)

        def span_obj(s: Span) -> Dict[str, Any]:
            o: Dict[str, Any] = {"text": s.text}
            for k, v in _style_json(s.style):
                o[k] = v
            return o

        if not self.spans:
            return {"text": ""}
        if len(self.spans) == 1:
            return span_obj(self.spans[0])
        return {"text": "", "extra": [span_obj(s) for s in self.spans]}

    def argument(self) -> Any:
        """Аргумент перевода: vanilla шлёт числа числами."""
        c = self.component()
        if isinstance(c, dict) and len(c) == 1 and isinstance(c.get("text"), str):
            s = c["text"]
            try:
                n = int(s)
            except ValueError:
                return c
            if str(n) == s:
                return n
        return c

    def plain(self) -> str:
        """Component.getString: простые символы."""
        out: List[str] = []
        for s in self.spans:
            if s.style.inline_object is not None and s.text == "\ufffc":
                out.append(s.style.inline_object.get_fallback())
            else:
                out.append(s.text)
        return "".join(out)

    # алиас в терминах задачи
    def to_plain_string(self) -> str:
        return self.plain()

    def to_json(self) -> Any:
        return self.component()

    def is_empty(self) -> bool:
        return all(s.text == "" for s in self.spans)

    # ── legacy § ──────────────────────────────────────────────────────
    @staticmethod
    def legacy(s: str) -> "Text":
        """Разобрать legacy-коды форматирования (`§a`, `§l`, `§r`...)."""
        out = Text()
        style = Style()
        current: List[str] = []
        chars = list(s)
        i = 0
        while i < len(chars):
            c = chars[i]
            if c != "§":
                current.append(c)
                i += 1
                continue
            i += 1
            if i >= len(chars):
                break
            code = chars[i].lower()
            i += 1
            if current:
                out.spans.append(Span("".join(current), style))
                current = []
            matched = False
            for cc, _name, v in COLORS:
                if cc == code:
                    # Коды цвета сбрасывают декорации.
                    style = Style(color=v)
                    matched = True
                    break
            if not matched:
                if code == "k":
                    style.obfuscated = True
                elif code == "l":
                    style.bold = True
                elif code == "m":
                    style.strikethrough = True
                elif code == "n":
                    style.underlined = True
                elif code == "o":
                    style.italic = True
                elif code == "r":
                    style = Style()
        if current:
            out.spans.append(Span("".join(current), style))
        return out

    # алиас в терминах задачи
    from_legacy = legacy

    def resolve_legacy(self) -> "Text":
        """`StringDecomposer.iterateFormatted` по каждому span'у: legacy-коды
        внутри содержимого span'а перестилизуют то, что за ними, и не рисуются."""
        if not any("§" in s.text for s in self.spans):
            return copy.deepcopy(self)
        out = Text()
        for span in self.spans:
            style = copy.copy(span.style)
            current: List[str] = []
            chars = list(span.text)
            i = 0
            while i < len(chars):
                c = chars[i]
                if c != "§":
                    current.append(c)
                    i += 1
                    continue
                i += 1
                if i >= len(chars):
                    break
                code = chars[i]
                i += 1
                nxt = legacy_format(style, code, span.style)
                if nxt != style:
                    if current:
                        out.spans.append(Span("".join(current), style))
                        current = []
                    style = nxt
            if current:
                out.spans.append(Span("".join(current), style))
        return out

    def resolved(self) -> "Text":
        if any("§" in s.text for s in self.spans):
            return self.resolve_legacy()
        return self

    def strip_legacy(self) -> "Text":
        """Текст без legacy-кодов (§ и код `0`-`9`, `a`-`f`, `k`-`o`, `r`)."""
        if not any("§" in s.text for s in self.spans):
            return copy.deepcopy(self)

        def is_code(c: str) -> bool:
            c = c.lower()
            return ("0" <= c <= "9") or ("a" <= c <= "f") or ("k" <= c <= "o") or c == "r"

        out = Text()
        for span in self.spans:
            buf: List[str] = []
            chars = list(span.text)
            i = 0
            while i < len(chars):
                c = chars[i]
                if c == "§" and i + 1 < len(chars) and is_code(chars[i + 1]):
                    i += 2
                else:
                    buf.append(c)
                    i += 1
            if buf:
                out.spans.append(Span("".join(buf), copy.copy(span.style)))
        return out

    def chars(self) -> Iterator[Tuple[str, Style]]:
        """Символы с их эффективными стилями."""
        for s in self.spans:
            for c in s.text:
                yield c, s.style

    def slice(self, frm: int, to: int) -> "Text":
        """Поддиапазон символов [from, to) с сохранением стилей."""
        out = Text()
        index = 0
        for span in self.spans:
            part: List[str] = []
            for c in span.text:
                if frm <= index < to:
                    part.append(c)
                index += 1
            if part:
                out.spans.append(Span("".join(part), copy.copy(span.style)))
        return out

    # ── ANSI (только для консоли; в Rust нет) ─────────────────────────
    def to_ansi(self) -> str:
        """ANSI-представление для консоли (truecolor + декорации)."""
        parts: List[str] = []
        for span in self.spans:
            st = span.style
            codes: List[str] = []
            if st.color is not None:
                c = st.color
                codes.append("38;2;{};{};{}".format((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF))
            if st.bold:
                codes.append("1")
            if st.italic:
                codes.append("3")
            if st.underlined:
                codes.append("4")
            if st.strikethrough:
                codes.append("9")
            if st.obfuscated:
                codes.append("8")
            if codes:
                parts.append("\x1b[" + ";".join(codes) + "m")
            parts.append(span.text)
            if codes:
                parts.append("\x1b[0m")
        return "".join(parts)


# ── Разбор JSON-компонента (расширение поверх Rust) ───────────────────────
def _parse_color(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v & 0xFFFFFF
    if isinstance(v, str):
        if v.startswith("#"):
            h = v[1:]
            try:
                return int(h, 16) & 0xFFFFFF
            except ValueError:
                return None
        return named_color(v)
    return None


def _parse_click(d: Any) -> Optional[ClickEvent]:
    if not isinstance(d, dict):
        return None
    action = d.get("action")
    if action == "open_url":
        return ClickEvent.open_url(d.get("url", ""))
    if action == "change_page":
        return ClickEvent.change_page(int(d.get("page", 1)))
    if action == "suggest_command":
        return ClickEvent.suggest_command(d.get("command", ""))
    if action == "run_command":
        return ClickEvent.run_command(d.get("command", ""))
    if action == "copy_to_clipboard":
        return ClickEvent.copy_to_clipboard(d.get("value", ""))
    if action == "show_dialog":
        return ClickEvent.show_dialog(d.get("dialog"))
    if action == "custom":
        return ClickEvent.custom(d.get("id", ""), d.get("payload"))
    if action == "open_file":
        return ClickEvent.open_file(d.get("path", ""))
    return None


def _parse_hover(style: Style, d: Any) -> None:
    if not isinstance(d, dict):
        return
    action = d.get("action")
    if action == "show_text":
        style.hover = Text.from_json(d.get("value"))
    elif action == "show_item":
        style.hover_item = {k: v for k, v in d.items() if k != "action"}
    elif action == "show_entity":
        style.hover_entity = {k: v for k, v in d.items() if k != "action"}


def _apply_style_json(value: Dict[str, Any]) -> Style:
    style = Style()
    if "color" in value:
        style.color = _parse_color(value["color"])
    if "shadow_color" in value:
        sv = value["shadow_color"]
        style.shadow_color = sv & 0xFFFFFFFF if isinstance(sv, int) else None
    for key in ("bold", "italic", "underlined", "strikethrough", "obfuscated"):
        if key in value:
            setattr(style, key, bool(value[key]))
    if "click_event" in value:
        style.click = _parse_click(value["click_event"])
    if "hover_event" in value:
        _parse_hover(style, value["hover_event"])
    if "insertion" in value:
        style.insertion = value["insertion"]
    if "font" in value:
        style.font = value["font"]
    return style


def _from_json(value: Any) -> "Text":
    if value is None:
        return Text.empty()
    if isinstance(value, str):
        return Text.literal(value)
    if isinstance(value, bool):
        return Text.literal("true" if value else "false")
    if isinstance(value, (int, float)):
        return Text.literal(str(value))
    if isinstance(value, list):
        root = Text.empty()
        for item in value:
            root.push(_from_json(item))
        return root
    if not isinstance(value, dict):
        return Text.literal(str(value))

    style = _apply_style_json(value)

    if "text" in value:
        t = Text.literal(str(value["text"]))
    elif "translate" in value:
        args = [_from_json(x) for x in value.get("with", [])]
        fallback = value.get("fallback")
        if fallback is not None:
            t = Text.translate_with_fallback(str(value["translate"]), str(fallback), args)
        else:
            t = Text.translate(str(value["translate"]), args)
    elif "keybind" in value:
        k = str(value["keybind"])
        # FALLBACK: без загруженных биндов ключ выводится как есть.
        t = Text(spans=[Span(k, Style())], source={"keybind": k})
    elif "selector" in value:
        s = str(value["selector"])
        # FALLBACK: без контекста селектор выводится шаблоном.
        t = Text(spans=[Span(s, Style())], source={"selector": s})
    elif "score" in value:
        # FALLBACK: нужен scoreboard — без него строка пуста.
        t = Text(source={"score": value["score"]})
    elif "nbt" in value:
        # FALLBACK: нужен контекст NBT — строка пуста.
        t = Text(source={"nbt": value["nbt"]})
    else:
        t = Text.empty()

    t = t.with_style(style)
    for child in value.get("extra", []):
        t.push(_from_json(child))
    return t


def _text_from_json(value: Any) -> "Text":
    return _from_json(value)


Text.from_json = staticmethod(_from_json)  # type: ignore[attr-defined]
