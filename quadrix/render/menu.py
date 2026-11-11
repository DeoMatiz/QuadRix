"""Меню, настройки и язык QuadRix (GUI PART 2).

Строится поверх примитивов PART 1 (``quadrix/render/ui.py``: ``Font``,
``Quad``, ``Batch``, ``Button``, ``Slider``). PART 2 добавляет экранную
модель (``Screen`` + стек), главное меню, экран настроек с категориями и
экран выбора языка, а также виджеты ``Checkbox`` / ``TextInput`` /
``ScrollableList`` и хранение настроек.

Порт Horizon (Rust → Python), читаем только нужное:
    * ``horizon-client/src/title.rs``        — расположение кнопок
      главного меню (``Title::buttons``, ``Mode::Main``): ``cx = floor(w/2)``,
      ``y = floor(h/4) + 48``, ширина 200, шаг 24, Options/Quit по 98.
    * ``horizon-client-render/src/options_ui.rs`` — главный экран
      настроек (``Page::Main``): категории ``options.skinCustomisation``,
      ``options.sounds``, ``options.video``, ``options.controls``,
      ``options.language``, ``options.chat``, ``options.resourcepack``,
      ``options.accessibility``; сетка 2 столбца; FOV-слайдер. Экран языка
      (``Page::Language``): строки 220x18 с шагом 18, кнопка Done.
    * ``horizon-client-render/src/settings.rs`` — ``struct Settings``:
      значения по умолчанию (fov 70, render_distance 12, ...), диапазоны,
      кодировка ``options.txt`` и список источников звука.

FALLBACK: спрайтовый атлас ванильных виджетов (nine-slice, логотип, фон
из «земли») в PART 2 не подключён — фон и виджеты заливаются цветом
(см. ``Button``/``Slider`` из PART 1). Панорама/загрузка текстур — PART 3.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from quadrix.core import lang
from quadrix.core.lang import Language, LanguageInfo, PathSource
from quadrix.core.text import Text
from quadrix.render.ui import (
    Batch,
    Button,
    Font,
    Quad,
    Slider,
    rgba,
)

# ---------------------------------------------------------------------------
# константы (точно как в Rust; не менять)
# ---------------------------------------------------------------------------

# settings.rs::Settings::default — диапазоны и значения по умолчанию.
FOV_MIN = 30.0
FOV_MAX = 110.0
FOV_DEFAULT = 70.0

RENDER_DISTANCE_MIN = 2
RENDER_DISTANCE_MAX = 32
RENDER_DISTANCE_DEFAULT = 12

SIMULATION_DISTANCE_MIN = 5
SIMULATION_DISTANCE_MAX = 32
SIMULATION_DISTANCE_DEFAULT = 12

SENSITIVITY_DEFAULT = 0.5
MASTER_VOLUME_DEFAULT = 1.0
GAMMA_DEFAULT = 0.5
MAX_FPS_DEFAULT = 120
GUI_SCALE_DEFAULT = 0
MENU_BLUR_DEFAULT = 5
LANGUAGE_DEFAULT = lang.DEFAULT  # "en_us"

# title.rs::Title::buttons — геометрия главного меню.
MAIN_MENU_BUTTON_WIDTH = 200.0
MAIN_MENU_BUTTON_HEIGHT = 20.0
MAIN_MENU_BUTTON_STEP = 24.0
MAIN_MENU_HALF_WIDTH = 98.0

# options_ui.rs::Page::Language — строки списка языков.
LANGUAGE_ROW_WIDTH = 220.0
LANGUAGE_ROW_HEIGHT = 18.0
LANGUAGE_ROW_STEP = 18.0

# options_ui.rs::Page::Main — сетка категорий.
OPTIONS_COLUMN_STEP = 158.0
OPTIONS_BUTTON_WIDTH = 150.0
OPTIONS_ROW_STEP = 24.0
OPTIONS_TITLE = "options.title"

# Цвета (совпадают по духу с ванильными; текстурный атлас — PART 3).
BACKGROUND = rgba(0, 0, 0, 255)
TITLE_COLOR = rgba(255, 255, 255, 255)
LABEL_COLOR = rgba(255, 255, 255, 255)
SELECTION_COLOR = rgba(90, 90, 90, 255)
ENTRY_COLOR = rgba(24, 24, 24, 255)
BOX_BORDER = rgba(160, 160, 160, 255)
BOX_FILL = rgba(0, 0, 0, 255)
CHECK_COLOR = rgba(255, 255, 255, 255)

# options_ui.rs::Page::Main — категории в ванильном порядке (i18n-ключ, экран).
OPTION_CATEGORIES: list[tuple[str, str]] = [
    ("options.skinCustomisation", "skin"),
    ("options.sounds", "sound"),
    ("options.video", "graphics"),
    ("options.controls", "controls"),
    ("options.language", "language"),
    ("options.chat", "chat"),
    ("options.resourcepack", "packs"),
    ("options.accessibility", "accessibility"),
]

# Корень ресурсов для загрузки языков (FIXED, см. AGENTS.md).
PACK_ROOT = Path(".local/horizon-client/26.3")


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] menu: " + message)


def solid(
    batch: Batch,
    font: Optional[Font],
    x: float,
    y: float,
    w: float,
    h: float,
    color: int,
) -> None:
    """Сплошной прямоугольник: белый пиксель атласа шрифта или полный UV."""
    if font is not None:
        r = font.white
        batch.add_quad(Quad(x, y, w, h, r.u0, r.v0, r.u1, r.v1, color))
    else:
        batch.add_quad(Quad(x, y, w, h, 0.0, 0.0, 1.0, 1.0, color))


def _in_rect(x: float, y: float, w: float, h: float, mx: float, my: float) -> bool:
    """Точка внутри прямоугольника (левый верхний угол + размер)."""
    return x <= mx < x + w and y <= my < y + h


def draw_text(
    batch: Batch,
    font: Optional[Font],
    text: str,
    x: float,
    y: float,
    color: int = LABEL_COLOR,
    shadow: bool = True,
) -> float:
    """Нарисовать строку, вернуть её ширину (0 без шрифта)."""
    if font is None or not text:
        return 0.0
    if shadow:
        batch.add_quads(font.render(text, x + 1.0, y + 1.0, rgba(0, 0, 0, 160)))
    batch.add_quads(font.render(text, x, y, color))
    return float(font.width(text))


# ---------------------------------------------------------------------------
# список доступных языков (quadrix/core/lang.py поверх pack.mcmeta)
# ---------------------------------------------------------------------------

def available_languages(root: Path | str = PACK_ROOT) -> list[LanguageInfo]:
    """Языки из ``assets/pack.mcmeta`` (доступен — значит есть lang-файл)."""
    return lang.available([PathSource(Path(root))])


def load_language(code: str, root: Path | str = PACK_ROOT) -> Language:
    """Загрузить язык ``code`` из корня ресурсов (en_us + code)."""
    return Language.load([PathSource(Path(root))], code)


# ---------------------------------------------------------------------------
# настройки: struct Settings + options.txt / options.json
# ---------------------------------------------------------------------------

# Простые (не требующие кавычек) значения в options.txt.
_BARE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _encode_value(value: Any) -> str:
    """Значение options.txt как строка (vanilla: bool/int/double/строка)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Краткая запись, как Java Double.toString для типичных значений.
        text = repr(float(value))
        return text
    text = str(value)
    if text and all(ch in _BARE for ch in text):
        return text
    return json.dumps(text)


def _decode_value(text: str) -> Any:
    """Разобрать значение options.txt (bool/int/double/строка)."""
    if text in ("true", "false"):
        return text == "true"
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            return json.loads(text)
        except ValueError:
            return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


@dataclass
class Settings:
    """Порт ``settings.rs::Settings`` (только поля, нужные меню PART 2)."""

    fov: float = FOV_DEFAULT
    render_distance: int = RENDER_DISTANCE_DEFAULT
    simulation_distance: int = SIMULATION_DISTANCE_DEFAULT
    sensitivity: float = SENSITIVITY_DEFAULT
    master_volume: float = MASTER_VOLUME_DEFAULT
    gamma: float = GAMMA_DEFAULT
    max_fps: int = MAX_FPS_DEFAULT
    vsync: bool = True
    view_bobbing: bool = True
    gui_scale: int = GUI_SCALE_DEFAULT
    menu_blur: int = MENU_BLUR_DEFAULT
    language: str = LANGUAGE_DEFAULT
    # Полный набор значений файла (typed-поля выше — его проекция).
    file: dict[str, Any] = field(default_factory=dict)

    # -- чтение / запись (vanilla options.txt) ---------------------------

    @classmethod
    def from_file(cls, f: dict[str, Any]) -> "Settings":
        """Порт ``Settings::from_file`` — типизированный вид словаря опций."""
        def num(key: str, default: Any) -> Any:
            return f.get(key, default)

        return cls(
            fov=float(num("fov", FOV_DEFAULT)),
            render_distance=int(num("renderDistance", RENDER_DISTANCE_DEFAULT)),
            simulation_distance=int(
                num("simulationDistance", SIMULATION_DISTANCE_DEFAULT)
            ),
            sensitivity=float(num("mouseSensitivity", SENSITIVITY_DEFAULT)),
            master_volume=float(num("soundCategory_master", MASTER_VOLUME_DEFAULT)),
            gamma=float(num("gamma", GAMMA_DEFAULT)),
            max_fps=int(num("maxFps", MAX_FPS_DEFAULT)),
            vsync=bool(num("enableVsync", True)),
            view_bobbing=bool(num("bobView", True)),
            gui_scale=max(0, int(num("guiScale", GUI_SCALE_DEFAULT))),
            menu_blur=int(num("menuBackgroundBlurriness", MENU_BLUR_DEFAULT)),
            language=str(num("lang", LANGUAGE_DEFAULT)),
            file=dict(f),
        )

    @classmethod
    def parse(cls, text: str) -> "Settings":
        """Порт ``Settings::parse`` — ``options.txt`` как ``key:value`` строки."""
        values: dict[str, Any] = {}
        for line in text.splitlines():
            key, sep, raw = line.partition(":")
            if not sep:
                continue
            key = key.strip()
            if not key:
                continue
            values[key] = _decode_value(raw)
        return cls.from_file(values)

    def to_file(self) -> dict[str, Any]:
        """Порт ``Settings::to_file`` — словарь из типизированных полей."""
        f = dict(self.file)
        f["fov"] = int(self.fov)
        f["renderDistance"] = int(self.render_distance)
        f["simulationDistance"] = int(self.simulation_distance)
        f["mouseSensitivity"] = float(self.sensitivity)
        f["soundCategory_master"] = float(self.master_volume)
        f["gamma"] = float(self.gamma)
        f["maxFps"] = int(self.max_fps)
        f["enableVsync"] = bool(self.vsync)
        f["bobView"] = bool(self.view_bobbing)
        f["guiScale"] = int(self.gui_scale)
        f["menuBackgroundBlurriness"] = int(self.menu_blur)
        f["lang"] = str(self.language)
        return f

    def serialize(self) -> str:
        """Порт ``Settings::serialize`` — текст ``options.txt``."""
        lines = ["version:4000"]
        for key, value in self.to_file().items():
            if key == "version":
                continue
            lines.append(f"{key}:{_encode_value(value)}")
        return "\n".join(lines) + "\n"

    # -- файл на диске ---------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> "Settings":
        """Загрузить настройки. ``.json`` → JSON-словарь, иначе options.txt."""
        p = Path(path)
        if not p.exists():
            return cls()
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() == ".json":
            try:
                data = json.loads(text)
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            return cls.from_file(data)
        return cls.parse(text)

    def save(self, path: Path | str) -> None:
        """Сохранить настройки (``.json`` → JSON, иначе options.txt)."""
        p = Path(path)
        if p.suffix.lower() == ".json":
            p.write_text(json.dumps(self.to_file(), indent=2, sort_keys=True), encoding="utf-8")
        else:
            p.write_text(self.serialize(), encoding="utf-8")


# ---------------------------------------------------------------------------
# виджеты PART 2: Checkbox, TextInput, ScrollableList, Label
# ---------------------------------------------------------------------------

@dataclass
class Label:
    """Простая текстовая метка (без взаимодействия)."""

    x: float
    y: float
    text: Any = ""
    color: int = LABEL_COLOR
    centered_w: float = 0.0  # если задано — центрировать в этой ширине

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        text = self.text.plain() if isinstance(self.text, Text) else str(self.text)
        if font is None or not text:
            return
        x = self.x
        if self.centered_w:
            x = self.x + (self.centered_w - font.width(text)) / 2.0
        draw_text(batch, font, text, x, self.y, self.color)


@dataclass
class Checkbox:
    """Флажок (порт ванильного ``Checkbox``): квадрат 20x20 + подпись."""

    x: float
    y: float
    label: Any = ""
    value: bool = False
    on_change: Optional[Callable[[bool], None]] = None
    active: bool = True
    hovered: bool = False
    box: float = 20.0
    # Ширина зоны клика помимо квадрата (ванильный Checkbox включает подпись).
    hit_width: float = 0.0

    def label_plain(self) -> str:
        if isinstance(self.label, Text):
            return self.label.plain()
        return str(self.label)

    def contains(self, mx: float, my: float) -> bool:
        if not (self.x <= mx < self.x + self.box + self.hit_width):
            return False
        return self.y <= my < self.y + self.box

    def toggle(self) -> bool:
        """Переключить значение; ``on_change`` зовётся только при изменении."""
        if not self.active:
            return False
        self.value = not self.value
        if self.on_change is not None:
            self.on_change(self.value)
        return True

    def handle_click(self, mx: float, my: float) -> bool:
        if self.contains(mx, my):
            return self.toggle()
        return False

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, self.x, self.y, self.box, self.box, BOX_BORDER)
        solid(batch, font, self.x + 1.0, self.y + 1.0, self.box - 2.0, self.box - 2.0, BOX_FILL)
        if self.value:
            # «галочка»: два наклонных штриха аппроксимированы квадратами.
            solid(batch, font, self.x + 4.0, self.y + 9.0, 4.0, 4.0, CHECK_COLOR)
            solid(batch, font, self.x + 7.0, self.y + 5.0, 4.0, 4.0, CHECK_COLOR)
            solid(batch, font, self.x + 10.0, self.y + 8.0, 4.0, 4.0, CHECK_COLOR)
        label = self.label_plain()
        if font is not None and label:
            draw_text(batch, font, label, self.x + self.box + 4.0, self.y + 6.0)


@dataclass
class TextInput:
    """Простое однострочное поле ввода (порт ``EditBox`` для меню)."""

    x: float
    y: float
    w: float
    h: float = 18.0
    value: str = ""
    max_length: int = 32
    on_change: Optional[Callable[[str], None]] = None
    active: bool = True
    focused: bool = False
    cursor: int = 0

    def contains(self, mx: float, my: float) -> bool:
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def handle_click(self, mx: float, my: float) -> bool:
        """Клик: поле получает фокус (курсор — в конец)."""
        if self.contains(mx, my):
            self.focused = True
            self.cursor = len(self.value)
            return True
        self.focused = False
        return False

    def insert(self, ch: str) -> bool:
        """Вставить символ у курсора (порт ``EditBox.insertText``)."""
        if not self.active or not self.focused:
            return False
        if len(self.value) >= self.max_length:
            return False
        self.value = self.value[: self.cursor] + ch + self.value[self.cursor:]
        self.cursor += len(ch)
        if self.on_change is not None:
            self.on_change(self.value)
        return True

    def delete(self, count: int = 1) -> bool:
        """Удалить символ(ы) до курсора (Backspace)."""
        if not self.active or not self.focused or self.cursor == 0:
            return False
        start = max(0, self.cursor - count)
        self.value = self.value[:start] + self.value[self.cursor:]
        self.cursor = start
        if self.on_change is not None:
            self.on_change(self.value)
        return True

    def handle_char(self, ch: str) -> bool:
        """Символ от клавиатуры: печатные + Backspace/Delete по-простому."""
        if ch == "\b":
            return self.delete()
        if ch in ("\n", "\r", "\t"):
            return False
        if ch.isprintable() and len(ch) == 1:
            return self.insert(ch)
        return False

    def handle_key(self, key: str) -> bool:
        """Специальные клавиши: Backspace/Delete/Home/End/Left/Right."""
        if not self.focused:
            return False
        if key == "backspace":
            return self.delete()
        if key == "delete":
            if self.cursor < len(self.value):
                self.value = self.value[: self.cursor] + self.value[self.cursor + 1:]
                if self.on_change is not None:
                    self.on_change(self.value)
                return True
            return False
        if key == "left":
            self.cursor = max(0, self.cursor - 1)
            return True
        if key == "right":
            self.cursor = min(len(self.value), self.cursor + 1)
            return True
        if key == "home":
            self.cursor = 0
            return True
        if key == "end":
            self.cursor = len(self.value)
            return True
        return False

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, self.x, self.y, self.w, self.h, BOX_BORDER)
        solid(batch, font, self.x + 1.0, self.y + 1.0, self.w - 2.0, self.h - 2.0, BOX_FILL)
        if font is None:
            return
        draw_text(batch, font, self.value, self.x + 4.0, self.y + 5.0)
        if self.focused:
            caret = font.width(self.value[: self.cursor])
            solid(batch, font, self.x + 4.0 + caret, self.y + 3.0, 1.0, self.h - 6.0, LABEL_COLOR)


@dataclass
class ScrollableList:
    """Прокручиваемый список строк (порт ``AbstractSelectionList``).

    Строки фиксированной высоты; клик выбирает элемент; колесо/``scroll``
    двигают окно. Выбор помечается цветом (как ``LanguageRow.selected``).
    """

    x: float
    y: float
    w: float
    h: float
    items: list[Any] = field(default_factory=list)
    item_height: float = LANGUAGE_ROW_HEIGHT
    selected: Optional[int] = None
    scroll: float = 0.0
    on_select: Optional[Callable[[int, Any], None]] = None
    label_of: Optional[Callable[[Any], str]] = None

    # -- геометрия -------------------------------------------------------

    def max_scroll(self) -> float:
        return max(0.0, len(self.items) * self.item_height - self.h)

    def first_visible(self) -> int:
        if self.item_height <= 0.0:
            return 0
        return max(0, int(self.scroll // self.item_height))

    def visible_count(self) -> int:
        if self.item_height <= 0.0:
            return 0
        return int(math.ceil(self.h / self.item_height))

    def visible_items(self) -> list[tuple[int, Any]]:
        """Пары (индекс, элемент) в окне прокрутки."""
        start = self.first_visible()
        end = min(len(self.items), start + self.visible_count() + 1)
        return list(enumerate(self.items[start:end], start=start))

    def row_y(self, index: int) -> float:
        return self.y + index * self.item_height - self.scroll

    # -- взаимодействие --------------------------------------------------

    def contains(self, mx: float, my: float) -> bool:
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def index_at(self, mx: float, my: float) -> Optional[int]:
        if not self.contains(mx, my):
            return None
        idx = int((my - self.y + self.scroll) // self.item_height)
        if 0 <= idx < len(self.items):
            return idx
        return None

    def handle_click(self, mx: float, my: float) -> bool:
        idx = self.index_at(mx, my)
        if idx is None:
            return False
        self.selected = idx
        if self.on_select is not None:
            self.on_select(idx, self.items[idx])
        return True

    def handle_scroll(self, dy: float) -> bool:
        """Прокрутка колесом: ``dy`` — шаг (обычно ±1)."""
        before = self.scroll
        self.scroll = min(self.max_scroll(), max(0.0, self.scroll + dy * self.item_height))
        return self.scroll != before

    def scroll_to(self, index: int) -> None:
        """Показать элемент (``centerScrollOn`` не реализован — просто видно)."""
        target = index * self.item_height
        target = min(target, self.max_scroll())
        self.scroll = max(0.0, target)

    def label(self, index: int) -> str:
        """Подпись строки: ``label_of`` или ``str``."""
        item = self.items[index]
        if self.label_of is not None:
            return self.label_of(item)
        if isinstance(item, LanguageInfo):
            return item.label()
        if isinstance(item, Text):
            return item.plain()
        return str(item)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, self.x, self.y, self.w, self.h, ENTRY_COLOR)
        if font is None:
            return
        for index, _item in self.visible_items():
            ry = self.row_y(index)
            if ry + self.item_height < self.y or ry > self.y + self.h:
                continue
            if index == self.selected:
                solid(batch, font, self.x + 1.0, ry, self.w - 2.0, self.item_height, SELECTION_COLOR)
            draw_text(batch, font, self.label(index), self.x + 3.0, ry + 5.0)


# ---------------------------------------------------------------------------
# экраны: Screen + стек
# ---------------------------------------------------------------------------

class Screen:
    """Базовый экран QuadRix (порт ``Screen``/``ScreenDraw``).

    Подклассы переопределяют ``render`` / ``handle_click`` / ``handle_key``.
    Навигация — через :class:`ScreenStack` (push/pop); сам экран её не держит.
    """

    def __init__(self, width: float = 854.0, height: float = 480.0) -> None:
        self.width = float(width)
        self.height = float(height)

    def on_resize(self, width: float, height: float) -> None:
        """Экран изменил размер (порт ``Screen.resize``)."""
        self.width = float(width)
        self.height = float(height)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        """Нарисовать экран в батч PART 1 (по умолчанию — фон)."""
        solid(batch, font, 0.0, 0.0, self.width, self.height, BACKGROUND)

    def handle_click(self, mx: float, my: float) -> bool:
        """Клик мышью. ``True``, если экран его принял."""
        return False

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        """Клавиша. ``True``, если экран её принял."""
        return False

    def handle_scroll(self, dy: float) -> bool:
        """Колесо мыши."""
        return False


class ScreenStack:
    """Стек экранов (порт навигации Horizon: ``push``/``pop``)."""

    def __init__(self, screen: Screen) -> None:
        self._stack: list[Screen] = [screen]

    @property
    def current(self) -> Screen:
        return self._stack[-1]

    def push(self, screen: Screen) -> Screen:
        """Открыть новый экран поверх текущего."""
        screen.on_resize(self.current.width, self.current.height)
        self._stack.append(screen)
        return screen

    def pop(self) -> Optional[Screen]:
        """Закрыть верхний экран; корневой не закрывается."""
        if len(self._stack) <= 1:
            return None
        return self._stack.pop()

    def depth(self) -> int:
        return len(self._stack)

    def on_resize(self, width: float, height: float) -> None:
        for screen in self._stack:
            screen.on_resize(width, height)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        self.current.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        return self.current.handle_click(mx, my)

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        return self.current.handle_key(key, ch)

    def handle_scroll(self, dy: float) -> bool:
        return self.current.handle_scroll(dy)


# ---------------------------------------------------------------------------
# главное меню
# ---------------------------------------------------------------------------

class MainMenu(Screen):
    """Главный экран (порт ``title.rs::Mode::Main``)."""

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        on_quit: Optional[Callable[[], None]] = None,
        on_singleplayer: Optional[Callable[[], None]] = None,
        on_multiplayer: Optional[Callable[[], None]] = None,
        on_options: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.on_quit = on_quit
        self.on_singleplayer = on_singleplayer
        self.on_multiplayer = on_multiplayer
        self.on_options = on_options
        self.buttons: list[Button] = []
        self.build()

    def build(self) -> None:
        """Собрать кнопки по геометрии Rust (``Title::buttons``)."""
        self.buttons = []
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        cx = math.floor(w / 2.0)
        y = math.floor(h / 4.0) + 48.0
        bw = MAIN_MENU_BUTTON_WIDTH
        step = MAIN_MENU_BUTTON_STEP
        hw = MAIN_MENU_HALF_WIDTH

        self.buttons.append(Button(
            cx - 100.0, y, bw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.singleplayer", "Singleplayer"),
            on_click=self._click_singleplayer,
        ))
        self.buttons.append(Button(
            cx - 100.0, y + step, bw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.multiplayer", "Multiplayer"),
            on_click=self._click_multiplayer,
        ))
        self.buttons.append(Button(
            cx - 100.0, y + 4.0 * step, hw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.options", "Options..."),
            on_click=self._click_options,
        ))
        self.buttons.append(Button(
            cx + 2.0, y + 4.0 * step, hw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.quit", "Quit Game"),
            on_click=self._click_quit,
        ))

    def on_resize(self, width: float, height: float) -> None:
        super().on_resize(width, height)
        self.build()

    # -- действия --------------------------------------------------------

    def _click_singleplayer(self) -> None:
        if self.on_singleplayer is not None:
            self.on_singleplayer()

    def _click_multiplayer(self) -> None:
        if self.on_multiplayer is not None:
            self.on_multiplayer()

    def _click_options(self) -> None:
        if self.on_options is not None:
            self.on_options()

    def _click_quit(self) -> None:
        if self.on_quit is not None:
            self.on_quit()

    def title(self) -> str:
        """Заголовок: ванильное лого через спрайты — PART 3, сейчас текст."""
        return lang.get_or("menu.title", "Minecraft")

    # -- рендер / ввод ---------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, 0.0, 0.0, self.width, self.height, BACKGROUND)
        if font is not None:
            text = self.title()
            tx = (self.width - font.width(text)) / 2.0
            ty = math.floor(self.height / 4.0) - 20.0
            draw_text(batch, font, text, tx, ty, TITLE_COLOR)
        for button in self.buttons:
            button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        return False


# ---------------------------------------------------------------------------
# экран настроек (главный + подстраницы)
# ---------------------------------------------------------------------------

class OptionsScreen(Screen):
    """Экран настроек (порт ``options_ui.rs::Page::Main``).

    Сверху — FOV-слайдер (как в Rust), ниже — сетка категорий 2 столбца,
    снизу — Done. Категории открывают подстраницы через ``stack``.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        stack: Optional[ScreenStack] = None,
        width: float = 854.0,
        height: float = 480.0,
    ) -> None:
        super().__init__(width, height)
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        self.buttons: list[Button] = []
        self.fov_slider: Optional[Slider] = None
        self.done_button: Optional[Button] = None
        self.build()

    def build(self) -> None:
        """Построить виджеты по геометрии Rust (``Page::Main``)."""
        self.buttons = []
        w = self.width
        h = self.height
        cx = (w / 2.0)
        # FOV-слайдер: option_widget(Opt::Fov, cx-154, 29, 150).
        self.fov_slider = Slider(
            x=cx - 154.0,
            y=29.0,
            w=150.0,
            h=MAIN_MENU_BUTTON_HEIGHT,
            value=float(self.settings.fov),
            min=FOV_MIN,
            max=FOV_MAX,
            label=lang.get_or("options.fov", "FOV: %s"),
            on_change=self._on_fov,
        )
        # Сетка категорий: x = cx-158+4+(i%2)*158, y = gy + (i/2)*24.
        entries = OPTION_CATEGORIES
        rows = (len(entries) + 1) // 2
        gy = min(61.0 + 30.0, h - 33.0 - rows * OPTIONS_ROW_STEP)
        for i, (key, page) in enumerate(entries):
            bx = cx - 158.0 + 4.0 + (i % 2) * OPTIONS_COLUMN_STEP
            by = gy + (i // 2) * OPTIONS_ROW_STEP
            label = lang.get_or(key, key)
            self.buttons.append(
                Button(bx, by, OPTIONS_BUTTON_WIDTH, MAIN_MENU_BUTTON_HEIGHT,
                       label, on_click=self._make_open(page))
            )
        self.done_button = Button(
            cx - 100.0, h - 27.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.done", "Done"), on_click=self._done,
        )

    def _make_open(self, page: str) -> Callable[[], None]:
        def _open() -> None:
            self.open_page(page)
        return _open

    def _on_fov(self, value: float) -> None:
        self.settings.fov = float(value)

    def _done(self) -> None:
        if self.stack is not None:
            self.stack.pop()

    def open_page(self, page: str) -> Optional[Screen]:
        """Открыть подстраницу настроек (``Act::Push(Page)``)."""
        if self.stack is None:
            return None
        screen: Screen
        if page == "language":
            screen = LanguageScreen(settings=self.settings, stack=self.stack,
                                    width=self.width, height=self.height)
        elif page == "graphics":
            screen = GraphicsScreen(settings=self.settings, stack=self.stack,
                                    width=self.width, height=self.height)
        elif page == "sound":
            screen = SoundScreen(settings=self.settings, stack=self.stack,
                                 width=self.width, height=self.height)
        elif page == "controls":
            screen = ControlsScreen(settings=self.settings, stack=self.stack,
                                    width=self.width, height=self.height)
        else:
            screen = OptionsSubScreen(page, self.settings, self.stack,
                                      self.width, self.height)
        return self.stack.push(screen)

    def on_resize(self, width: float, height: float) -> None:
        super().on_resize(width, height)
        self.build()

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, 0.0, 0.0, self.width, self.height, BACKGROUND)
        if font is not None:
            title = lang.get_or(OPTIONS_TITLE, "Options")
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 12.0, TITLE_COLOR)
        if self.fov_slider is not None:
            self.fov_slider.render(batch, font)
        for button in self.buttons:
            button.render(batch, font)
        if self.done_button is not None:
            self.done_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        if self.fov_slider is not None and _in_rect(
            self.fov_slider.x, self.fov_slider.y, self.fov_slider.w,
            self.fov_slider.h, mx, my,
        ):
            self.fov_slider.click(mx)
            return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        if self.done_button is not None and self.done_button.handle_click(mx, my):
            return True
        return False


class OptionsSubScreen(Screen):
    """Простая подстраница настроек (заготовка без специфичных виджетов)."""

    def __init__(
        self,
        page: str,
        settings: Optional[Settings] = None,
        stack: Optional[ScreenStack] = None,
        width: float = 854.0,
        height: float = 480.0,
    ) -> None:
        super().__init__(width, height)
        self.page = page
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        self.back_button = Button(
            (width / 2.0) - 100.0, height - 27.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.back", "Back"), on_click=self._back,
        )

    def _back(self) -> None:
        if self.stack is not None:
            self.stack.pop()

    def title_key(self) -> str:
        return "options." + self.page

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, 0.0, 0.0, self.width, self.height, BACKGROUND)
        if font is not None:
            title = lang.get_or(self.title_key(), self.page.title())
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 12.0, TITLE_COLOR)
        self.back_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        return self.back_button.handle_click(mx, my)


class GraphicsScreen(OptionsSubScreen):
    """Video/Graphics: FOV, дальности прорисовки и симуляции, VSync, bobbing."""

    def __init__(self, settings=None, stack=None, width=854.0, height=480.0):
        super().__init__("video", settings, stack, width, height)
        self.page = "graphics"
        s = self.settings
        cx = width / 2.0
        top = 29.0
        self.sliders = [
            Slider(cx - 154.0, top, 150.0, 20.0, value=float(s.fov),
                   min=FOV_MIN, max=FOV_MAX,
                   label=lang.get_or("options.fov", "FOV"), on_change=self._set_fov),
            Slider(cx - 154.0, top + 24.0, 150.0, 20.0, value=float(s.render_distance),
                   min=RENDER_DISTANCE_MIN, max=RENDER_DISTANCE_MAX,
                   label=lang.get_or("options.renderDistance", "Render Distance"),
                   on_change=self._set_render_distance),
            Slider(cx - 154.0, top + 48.0, 150.0, 20.0, value=float(s.simulation_distance),
                   min=SIMULATION_DISTANCE_MIN, max=SIMULATION_DISTANCE_MAX,
                   label=lang.get_or("options.simulationDistance", "Simulation Distance"),
                   on_change=self._set_simulation_distance),
        ]
        self.checkboxes = [
            Checkbox(cx + 4.0, top, lang.get_or("options.vsync", "VSync"),
                     value=bool(s.vsync), on_change=self._set_vsync, hit_width=100.0),
            Checkbox(cx + 4.0, top + 24.0, lang.get_or("options.viewBobbing", "View Bobbing"),
                     value=bool(s.view_bobbing), on_change=self._set_bobbing, hit_width=100.0),
        ]

    def _set_fov(self, v): self.settings.fov = float(v)
    def _set_render_distance(self, v): self.settings.render_distance = int(round(v))
    def _set_simulation_distance(self, v): self.settings.simulation_distance = int(round(v))
    def _set_vsync(self, v): self.settings.vsync = bool(v)
    def _set_bobbing(self, v): self.settings.view_bobbing = bool(v)

    def title_key(self) -> str:
        return "options.video"

    def render(self, batch, font=None):
        super().render(batch, font)
        for s in self.sliders:
            s.render(batch, font)
        for c in self.checkboxes:
            c.render(batch, font)

    def handle_click(self, mx, my):
        for s in self.sliders:
            if _in_rect(s.x, s.y, s.w, s.h, mx, my):
                s.click(mx)
                return True
        for c in self.checkboxes:
            if c.handle_click(mx, my):
                return True
        return self.back_button.handle_click(mx, my)


class SoundScreen(OptionsSubScreen):
    """Music & Sounds: громкость мастера."""

    def __init__(self, settings=None, stack=None, width=854.0, height=480.0):
        super().__init__("sounds", settings, stack, width, height)
        self.page = "sound"
        cx = width / 2.0
        self.slider = Slider(
            cx - 154.0, 29.0, 150.0, 20.0, value=float(settings.master_volume if settings else MASTER_VOLUME_DEFAULT),
            min=0.0, max=1.0,
            label=lang.get_or("soundCategory_master", "Master Volume"),
            on_change=self._set_master,
        )

    def _set_master(self, v):
        self.settings.master_volume = float(v)

    def title_key(self) -> str:
        return "options.sounds"

    def render(self, batch, font=None):
        super().render(batch, font)
        self.slider.render(batch, font)

    def handle_click(self, mx, my):
        if _in_rect(self.slider.x, self.slider.y, self.slider.w, self.slider.h, mx, my):
            self.slider.click(mx)
            return True
        return self.back_button.handle_click(mx, my)


class ControlsScreen(OptionsSubScreen):
    """Controls: чувствительность и переключатели (toggle sprint и т.п.)."""

    def __init__(self, settings=None, stack=None, width=854.0, height=480.0):
        super().__init__("controls", settings, stack, width, height)
        self.page = "controls"
        s = self.settings
        cx = width / 2.0
        self.slider = Slider(
            cx - 154.0, 29.0, 150.0, 20.0, value=float(s.sensitivity),
            min=0.0, max=1.0,
            label=lang.get_or("options.sensitivity", "Sensitivity"),
            on_change=self._set_sensitivity,
        )
        self.checkboxes = [
            Checkbox(cx + 4.0, 29.0, lang.get_or("options.toggleSprint", "Toggle Sprint"),
                     value=False, on_change=self._set_toggle_sprint, hit_width=120.0),
            Checkbox(cx + 4.0, 53.0, lang.get_or("options.autoJump", "Auto-Jump"),
                     value=False, on_change=self._set_auto_jump, hit_width=120.0),
        ]
        self.toggle_sprint = False
        self.auto_jump = False

    def _set_sensitivity(self, v):
        self.settings.sensitivity = float(v)

    def _set_toggle_sprint(self, v):
        self.toggle_sprint = bool(v)

    def _set_auto_jump(self, v):
        self.auto_jump = bool(v)

    def title_key(self) -> str:
        return "options.controls"

    def render(self, batch, font=None):
        super().render(batch, font)
        self.slider.render(batch, font)
        for c in self.checkboxes:
            c.render(batch, font)

    def handle_click(self, mx, my):
        if _in_rect(self.slider.x, self.slider.y, self.slider.w, self.slider.h, mx, my):
            self.slider.click(mx)
            return True
        for c in self.checkboxes:
            if c.handle_click(mx, my):
                return True
        return self.back_button.handle_click(mx, my)


# ---------------------------------------------------------------------------
# экран языка
# ---------------------------------------------------------------------------

class LanguageScreen(Screen):
    """Выбор языка (порт ``options_ui.rs::Page::Language``).

    Список — из ``assets/pack.mcmeta`` и ``assets/minecraft/lang/*.json``
    в ``.local``. Клик по строке — временный выбор; Done применяет язык
    (``lang.set``) и записывает код в настройки.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        stack: Optional[ScreenStack] = None,
        root: Path | str = PACK_ROOT,
        width: float = 854.0,
        height: float = 480.0,
        languages: Optional[list[LanguageInfo]] = None,
    ) -> None:
        super().__init__(width, height)
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        self.root = Path(root)
        self.languages: list[LanguageInfo] = (
            languages if languages is not None else available_languages(self.root)
        )
        self.choice: str = self.settings.language
        cx = width / 2.0
        self.list = ScrollableList(
            x=cx - 110.0,
            y=36.0,
            w=LANGUAGE_ROW_WIDTH,
            h=height - 53.0 - 36.0,
            items=list(self.languages),
            item_height=LANGUAGE_ROW_STEP,
            label_of=lambda info: info.label(),
            on_select=self._on_select,
        )
        self.list.selected = self._index_of(self.choice)
        self.done_button = Button(
            cx - 100.0, height - 45.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.done", "Done"), on_click=self.apply,
        )

    def _index_of(self, code: str) -> Optional[int]:
        for i, info in enumerate(self.languages):
            if info.code == code:
                return i
        return None

    def _on_select(self, index: int, info: LanguageInfo) -> None:
        self.choice = info.code

    def set_language(self, code: str) -> Language:
        """Загрузить и сделать текущим язык ``code``; вернуть объект языка."""
        language = load_language(code, self.root)
        lang.set(language)
        self.choice = code
        self.settings.language = code
        return language

    def apply(self) -> Language:
        """Кнопка Done: применить выбранный язык (``lang.set``)."""
        selected = self.list.selected
        if selected is not None and 0 <= selected < len(self.languages):
            self.choice = self.languages[selected].code
        return self.set_language(self.choice)

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if key == "escape":
            return self.apply() is not None
        return False

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        solid(batch, font, 0.0, 0.0, self.width, self.height, BACKGROUND)
        if font is not None:
            title = lang.get_or("options.language.title", "Select Language")
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 4.0, TITLE_COLOR)
        self.list.render(batch, font)
        self.done_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        if self.list.handle_click(mx, my):
            return True
        if self.done_button.handle_click(mx, my):
            return True
        return False

    def handle_scroll(self, dy: float) -> bool:
        return self.list.handle_scroll(dy)


__all__ = [
    "BACKGROUND",
    "Checkbox",
    "ControlsScreen",
    "FOV_DEFAULT",
    "FOV_MAX",
    "FOV_MIN",
    "GraphicsScreen",
    "Label",
    "LANGUAGE_ROW_HEIGHT",
    "LANGUAGE_ROW_STEP",
    "LANGUAGE_ROW_WIDTH",
    "LanguageScreen",
    "MAIN_MENU_BUTTON_HEIGHT",
    "MAIN_MENU_BUTTON_STEP",
    "MAIN_MENU_BUTTON_WIDTH",
    "MAIN_MENU_HALF_WIDTH",
    "MainMenu",
    "OPTION_CATEGORIES",
    "OptionsScreen",
    "OptionsSubScreen",
    "PACK_ROOT",
    "RENDER_DISTANCE_DEFAULT",
    "RENDER_DISTANCE_MAX",
    "RENDER_DISTANCE_MIN",
    "SIMULATION_DISTANCE_DEFAULT",
    "SIMULATION_DISTANCE_MAX",
    "SIMULATION_DISTANCE_MIN",
    "Screen",
    "ScreenStack",
    "ScrollableList",
    "Settings",
    "SoundScreen",
    "TextInput",
    "available_languages",
    "draw_text",
    "load_language",
    "solid",
]
