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
      (``Page::Language``): строки 220x18 с шагом 18, кнопка Done; выбор
      языка применяется сразу, Done/back закрывает экран. GUI Scale
      (``Page::Video``, ``Opt::GuiScale``) циклится Auto → 1..max, а
      ``window.rs::calculate_scale``/``gui_scaled_size`` задают логический
      размер интерфейса (см. ``App._sync_gui_scale``).
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
from quadrix.render.graphics import Extras, HorizonGraphics
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
# options_ui.rs L3369: warning languageAccuracyWarning — rgba(0xBA,0xBA,0xBA,255).
LANGUAGE_WARNING_COLOR = rgba(0xBA, 0xBA, 0xBA, 255)

# options_ui.rs::Page::Main — категории в ванильном порядке (i18n-ключ, экран).
# Ровно 11 слотов из Rust (options_ui.rs L3075-3098), включая Horizon settings и mods.
OPTION_CATEGORIES: list[tuple[str, Optional[str]]] = [
    ("options.skinCustomisation", "skin"),
    ("options.sounds", "sound"),
    ("options.video", "graphics"),
    ("options.controls", "controls"),
    ("options.language", "language"),
    ("options.chat", "chat"),
    ("options.resourcepack", "packs"),
    ("options.accessibility", "accessibility"),
    ("horizon.pages.open.horizon_settings", "horizon_settings"),
    ("horizon.pages.open.mods", "mods"),
    ("options.credits_and_attribution", "credits"),
]

# options_ui.rs::OptionsUi::title — ключ заголовка подстраницы.
PAGE_TITLES: dict[str, str] = {
    "skin": "options.skinCustomisation.title",
    "sound": "options.sounds.title",
    "graphics": "options.videoTitle",
    "controls": "controls.title",
    "language": "options.language.title",
    "chat": "options.chat.title",
    "packs": "resourcePack.title",
    "accessibility": "options.accessibility.title",
    "online": "options.online.title",
    "horizon_settings": "horizon.pages.settings",
    "mods": "horizon.pages.mods",
    "credits": "credits_and_attribution.screen.title",
    "font": "options.font.title",
}

# title.rs (L1824-1847) — иконки-кнопки главного меню: (i18n-ключ, фолбэк, спрайт).
MAIN_MENU_ICONS: list[tuple[str, str, str]] = [
    ("gui.friends.open", "Friends", "gui/sprites/friends/friends"),
    ("options.language", "Language...", "gui/sprites/icon/language"),
    ("options.accessibility", "Accessibility Settings...", "gui/sprites/icon/accessibility"),
]

# ui.rs::menu_background / SoundManager: плитка «земли» 32 GUI-пикселя.
MENU_BACKGROUND_TILE = 32.0
MENU_BACKGROUND_SPRITE = "gui/menu_background"

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


def draw_menu_background(
    batch: Batch, font: Optional[Font], w: float, h: float
) -> None:
    """Фон экрана настроек: ``ui.rs::menu_background`` (плитка 32), иначе чёрный.

    Заголовочный экран (MainMenu) фон НЕ рисует — за ним панорама (см. App).
    """
    atlas = getattr(batch, "atlas", None)
    if atlas is not None and atlas.tiled(
        batch, MENU_BACKGROUND_SPRITE, 0.0, 0.0, w, h, MENU_BACKGROUND_TILE
    ):
        return
    # FALLBACK: нет атласа — сплошная тёмная заливка (как ui.rs при отсутствии спрайта).
    solid(batch, font, 0.0, 0.0, w, h, BACKGROUND)


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


def calculate_scale(
    framebuffer: tuple[int, int],
    max_scale: int = 0,
    enforce_unicode: bool = False,
) -> int:
    """Порт ``window.rs::calculate_scale`` — максимальный GUI scale.

    Rust:
    ``while scale != max_scale && scale < width && scale < height
    && width / (scale + 1) >= 320 && height / (scale + 1) >= 240``.
    ``max_scale == 0`` означает «до упора» (auto).
    """
    width, height = int(framebuffer[0]), int(framebuffer[1])
    scale = 1
    while (
        scale != max_scale
        and scale < width
        and scale < height
        and width // (scale + 1) >= 320
        and height // (scale + 1) >= 240
    ):
        scale += 1
    if enforce_unicode and scale % 2 != 0:
        scale += 1
    return scale


def gui_scaled_size(framebuffer: tuple[int, int], gui_scale: int) -> tuple[int, int]:
    """Порт ``window.rs::gui_scaled_size`` (``Window.setGuiScale``).

    ``ceil(size / gui_scale)``: логический размер интерфейса, который
    получают экраны и ввод.
    """
    scale = max(1, int(gui_scale))
    width, height = int(framebuffer[0]), int(framebuffer[1])
    return math.ceil(width / scale), math.ceil(height / scale)


def effective_gui_scale(settings: "Settings", framebuffer: tuple[int, int]) -> int:
    """Действующий масштаб: ``0`` = auto (``calculate_scale``), иначе значение."""
    return int(settings.gui_scale) or calculate_scale(framebuffer, 0, False)


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
    # -- ванильные графические опции (settings.rs L226-253) --------------
    fullscreen: bool = False
    smooth_lighting: bool = True
    clouds: str = "true"
    cloud_range: int = 128
    particles: int = 0
    entity_distance: float = 1.0
    entity_shadows: bool = True
    biome_blend: int = 2
    graphics_preset: str = "fancy"
    mipmap_levels: int = 4
    weather_radius: int = 10
    chunk_fade: float = 0.75
    vignette: bool = True
    autosave_indicator: bool = True
    cutout_leaves: bool = True
    improved_transparency: bool = False
    attack_indicator: int = 1
    inactivity_fps_limit: str = "afk"
    prioritize_chunk_updates: int = 0
    # -- Horizon (graphics.rs::Graphics, extras.rs::Extras) --------------
    horizon: HorizonGraphics = field(default_factory=HorizonGraphics)
    extras: Extras = field(default_factory=Extras)
    #: ``Monitor.videoModes`` окна (заполняет игра); для строки Exclusive Mode.
    video_modes: list[Any] = field(default_factory=list)
    # Полный набор значений файла (typed-поля выше — его проекция).
    file: dict[str, Any] = field(default_factory=dict)

    def video_mode_index(self) -> int:
        """Индекс выбранного видеорежима (``-1``, если режимов нет)."""
        chosen = self.file.get("fullscreenResolution")
        for i, mode in enumerate(self.video_modes or []):
            if mode == chosen:
                return i
        return -1

    # -- чтение / запись (vanilla options.txt) ---------------------------

    @classmethod
    def from_file(cls, f: dict[str, Any]) -> "Settings":
        """Порт ``Settings::from_file`` — типизированный вид словаря опций."""
        def num(key: str, default: Any) -> Any:
            return f.get(key, default)

        def boolean(key: str, default: bool) -> bool:
            """``options_file::V::Bool`` — строка "true"/"false"."""
            value = f.get(key, default)
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() == "true"

        def name(key: str, default: str) -> str:
            value = f.get(key, default)
            return default if value is None else str(value)

        def integer(key: str, default: int) -> int:
            try:
                return int(f.get(key, default))
            except (TypeError, ValueError):
                return default

        def number(key: str, default: float) -> float:
            try:
                return float(f.get(key, default))
            except (TypeError, ValueError):
                return default

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
            vsync=boolean("enableVsync", True),
            view_bobbing=boolean("bobView", True),
            gui_scale=max(0, int(num("guiScale", GUI_SCALE_DEFAULT))),
            menu_blur=int(num("menuBackgroundBlurriness", MENU_BLUR_DEFAULT)),
            language=str(num("lang", LANGUAGE_DEFAULT)),
            fullscreen=boolean("fullscreen", False),
            smooth_lighting=boolean("ao", True),
            clouds=name("renderClouds", "true"),
            cloud_range=integer("cloudRange", 128),
            particles=integer("particles", 0),
            entity_distance=number("entityDistanceScaling", 1.0),
            entity_shadows=boolean("entityShadows", True),
            biome_blend=integer("biomeBlendRadius", 2),
            graphics_preset=name("graphicsPreset", "fancy"),
            mipmap_levels=integer("mipmapLevels", 4),
            weather_radius=integer("weatherRadius", 10),
            chunk_fade=number("chunkSectionFadeInTime", 0.75),
            vignette=boolean("vignette", True),
            autosave_indicator=boolean("showAutosaveIndicator", True),
            cutout_leaves=boolean("cutoutLeaves", True),
            improved_transparency=boolean("improvedTransparency", False),
            attack_indicator=integer("attackIndicator", 1),
            inactivity_fps_limit=name("inactivityFpsLimit", "afk"),
            prioritize_chunk_updates=integer("prioritizeChunkUpdates", 0),
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
        f["fullscreen"] = bool(self.fullscreen)
        f["ao"] = bool(self.smooth_lighting)
        f["renderClouds"] = str(self.clouds)
        f["cloudRange"] = int(self.cloud_range)
        f["particles"] = int(self.particles)
        f["entityDistanceScaling"] = float(self.entity_distance)
        f["entityShadows"] = bool(self.entity_shadows)
        f["biomeBlendRadius"] = int(self.biome_blend)
        f["graphicsPreset"] = str(self.graphics_preset)
        f["mipmapLevels"] = int(self.mipmap_levels)
        f["weatherRadius"] = int(self.weather_radius)
        f["chunkSectionFadeInTime"] = float(self.chunk_fade)
        f["vignette"] = bool(self.vignette)
        f["showAutosaveIndicator"] = bool(self.autosave_indicator)
        f["cutoutLeaves"] = bool(self.cutout_leaves)
        f["improvedTransparency"] = bool(self.improved_transparency)
        f["attackIndicator"] = int(self.attack_indicator)
        f["inactivityFpsLimit"] = str(self.inactivity_fps_limit)
        f["prioritizeChunkUpdates"] = int(self.prioritize_chunk_updates)
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
        """Строки списка (порт ``options_ui.rs::WKind::LanguageRow``).

        Выбранная строка — белая рамка 1px + чёрная заливка; подпись
        центрирована, ``y + 5`` (ряд 18px). Фон списка не заливается:
        за ним ``menu_background``.
        """
        for index, _item in self.visible_items():
            ry = self.row_y(index)
            if ry + self.item_height < self.y or ry > self.y + self.h:
                continue
            if index == self.selected:
                solid(batch, font, self.x, ry, self.w, self.item_height, LABEL_COLOR)
                solid(batch, font, self.x + 1.0, ry + 1.0, self.w - 2.0,
                      self.item_height - 2.0, BACKGROUND)
            if font is None:
                continue
            label = self.label(index)
            tw = font.width(label)
            tx = self.x + math.floor((self.w - tw) / 2.0)
            draw_text(batch, font, label, tx, ry + 5.0, LABEL_COLOR)


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
        # Виджеты хранят абсолютные координаты — пересобрать под новый размер.
        build = getattr(self, "build", None)
        if callable(build):
            build()

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

    def handle_move(self, mx: float, my: float) -> bool:
        """Курсор переместился (подсветка наведения). ``True``, если принято."""
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

    def handle_move(self, mx: float, my: float) -> bool:
        return self.current.handle_move(mx, my)


# ---------------------------------------------------------------------------
# главное меню
# ---------------------------------------------------------------------------

class MainMenu(Screen):
    """Главный экран (порт ``title.rs::Mode::Main``).

    Рисует логотип (спрайты ``gui/title/minecraft`` + ``edition``) и кнопки
    в стиле заголовка (левая/правая половины спрайта 200x20). Фон НЕ
    рисуется: за экраном панорама кубмапа (см. ``quadrix/render/panorama.py``
    и ``App.render``).
    """

    def __init__(
        self,
        width: float = 854.0,
        height: float = 480.0,
        on_quit: Optional[Callable[[], None]] = None,
        on_singleplayer: Optional[Callable[[], None]] = None,
        on_multiplayer: Optional[Callable[[], None]] = None,
        on_options: Optional[Callable[[], None]] = None,
        on_realms: Optional[Callable[[], None]] = None,
        on_friends: Optional[Callable[[], None]] = None,
        on_language: Optional[Callable[[], None]] = None,
        on_accessibility: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.on_quit = on_quit
        self.on_singleplayer = on_singleplayer
        self.on_multiplayer = on_multiplayer
        self.on_options = on_options
        self.on_realms = on_realms
        self.on_friends = on_friends
        self.on_language = on_language
        self.on_accessibility = on_accessibility
        self.buttons: list[Button] = []
        self.build()

    def build(self) -> None:
        """Собрать кнопки по геометрии Rust (``Title::buttons``, Mode::Main)."""
        self.buttons = []
        w = math.ceil(self.width)
        h = math.ceil(self.height)
        cx = math.floor(w / 2.0)
        y = math.floor(h / 4.0) + 48.0
        bw = MAIN_MENU_BUTTON_WIDTH
        step = MAIN_MENU_BUTTON_STEP
        hw = MAIN_MENU_HALF_WIDTH

        # title.rs L1776-1821: три полных, затем Options/Quit по 98.
        self.buttons.append(Button(
            cx - 100.0, y, bw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.singleplayer", "Singleplayer"),
            on_click=self._click_singleplayer, title_style=True,
        ))
        self.buttons.append(Button(
            cx - 100.0, y + step, bw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.multiplayer", "Multiplayer"),
            on_click=self._click_multiplayer, title_style=True,
        ))
        self.buttons.append(Button(
            cx - 100.0, y + 2.0 * step, bw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.online", "Minecraft Realms"),
            on_click=self._click_realms, title_style=True,
        ))
        self.buttons.append(Button(
            cx - 100.0, y + 4.0 * step, hw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.options", "Options..."),
            on_click=self._click_options, title_style=True,
        ))
        self.buttons.append(Button(
            cx + 2.0, y + 4.0 * step, hw, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("menu.quit", "Quit Game"),
            on_click=self._click_quit, title_style=True,
        ))
        # title.rs L1824-1847: иконки-кнопки 20x20 в строке y+72, шаг 24.
        openers = [
            self._click_friends,
            self._click_language,
            self._click_accessibility,
        ]
        for i, (key, plain, icon) in enumerate(MAIN_MENU_ICONS):
            self.buttons.append(Button(
                cx - 34.0 + i * 24.0, y + 72.0, 20.0, MAIN_MENU_BUTTON_HEIGHT,
                lang.get_or(key, plain),
                on_click=openers[i], title_style=True,
                icon=icon, icon_size=15.0,
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

    def _click_realms(self) -> None:
        if self.on_realms is not None:
            self.on_realms()

    def _click_options(self) -> None:
        if self.on_options is not None:
            self.on_options()

    def _click_quit(self) -> None:
        if self.on_quit is not None:
            self.on_quit()

    def _click_friends(self) -> None:
        if self.on_friends is not None:
            self.on_friends()

    def _click_language(self) -> None:
        if self.on_language is not None:
            self.on_language()

    def _click_accessibility(self) -> None:
        if self.on_accessibility is not None:
            self.on_accessibility()

    def title(self) -> str:
        """Текст-фолбэк логотипа (без атласа спрайтов)."""
        return lang.get_or("menu.title", "Minecraft")

    # -- рендер / ввод ---------------------------------------------------

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        self._render_logo(batch, font)
        for button in self.buttons:
            button.render(batch, font)

    def _render_logo(self, batch: Batch, font: Optional[Font]) -> None:
        """Логотип: ``title.rs::draw_logo`` (спрайт-регионы 256x44 + 128x14)."""
        atlas = getattr(batch, "atlas", None)
        cx = math.floor(math.ceil(self.width) / 2.0)
        if atlas is not None:
            drew = atlas.region(
                batch, "gui/title/minecraft", cx - 128.0, 30.0, 256.0, 44.0,
                256.0, 64.0,
            )
            drew = atlas.region(
                batch, "gui/title/edition", cx - 64.0, 30.0 + 44.0 - 7.0, 128.0, 14.0,
                128.0, 16.0,
            ) and drew
            if drew:
                return
        # FALLBACK: нет атласа — рисуем название текстом (логотип-спрайт недоступен).
        if font is not None:
            text = self.title()
            tx = (self.width - font.width(text)) / 2.0
            draw_text(batch, font, text, tx, 40.0, TITLE_COLOR)

    def handle_click(self, mx: float, my: float) -> bool:
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        handled = False
        for button in self.buttons:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        return handled


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
        framebuffer: Optional[tuple[int, int]] = None,
    ) -> None:
        super().__init__(width, height)
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        #: Размер кадрового буфера (для GUI scale); App передаёт реальный.
        self.framebuffer = framebuffer or (int(width), int(height))
        self.buttons: list[Button] = []
        self.online_button: Optional[Button] = None
        self.fov_slider: Optional[Slider] = None
        self.done_button: Optional[Button] = None
        self.build()

    def build(self) -> None:
        """Построить виджеты по геометрии Rust (``Page::Main`` L3053-3109)."""
        self.buttons = []
        w = self.width
        h = self.height
        cx = math.floor(w / 2.0)
        # FOV-слайдер: option_widget(Opt::Fov, cx-154, 29, 150).
        self.fov_slider = Slider(
            x=cx - 154.0,
            y=29.0,
            w=150.0,
            h=MAIN_MENU_BUTTON_HEIGHT,
            value=float(self.settings.fov),
            min=FOV_MIN,
            max=FOV_MAX,
            label=lang.get_or("options.fov", "FOV"),
            on_change=self._on_fov,
        )
        # Online: button(cx+4, 29, 150, options.online, Push(Online)).
        self.online_button = Button(
            cx + 4.0, 29.0, OPTIONS_BUTTON_WIDTH, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("options.online", "Online..."),
            on_click=self._make_open("online"),
        )
        # Сетка категорий: x = cx-158+4+(i%2)*158, y = gy + (i/2)*24,
        # gy = min(91, h-33-rows*24), rows = ceil(n/2).
        entries = OPTION_CATEGORIES
        rows = (len(entries) + 1) // 2
        gy = min(91.0, h - 33.0 - rows * OPTIONS_ROW_STEP)
        for i, (key, page) in enumerate(entries):
            bx = cx - 158.0 + 4.0 + (i % 2) * OPTIONS_COLUMN_STEP
            by = gy + (i // 2) * OPTIONS_ROW_STEP
            label = lang.get_or(key, key)
            self.buttons.append(
                Button(bx, by, OPTIONS_BUTTON_WIDTH, MAIN_MENU_BUTTON_HEIGHT,
                       label, on_click=self._make_open(page),
                       active=page is not None)
            )
        self.done_button = Button(
            cx - 100.0, h - 27.0, 200.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.done", "Done"), on_click=self._done,
        )

    def _make_open(self, page: Optional[str]) -> Callable[[], None]:
        def _open() -> None:
            if page is not None:
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
                                    width=self.width, height=self.height,
                                    framebuffer=self.framebuffer)
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
        draw_menu_background(batch, font, self.width, self.height)
        if font is not None:
            title = lang.get_or(OPTIONS_TITLE, "Options")
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 12.0, TITLE_COLOR)
        if self.fov_slider is not None:
            self.fov_slider.render(batch, font)
        if self.online_button is not None:
            self.online_button.render(batch, font)
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
        if self.online_button is not None and self.online_button.handle_click(mx, my):
            return True
        for button in self.buttons:
            if button.handle_click(mx, my):
                return True
        if self.done_button is not None and self.done_button.handle_click(mx, my):
            return True
        return False

    def handle_move(self, mx: float, my: float) -> bool:
        handled = False
        widgets = list(self.buttons)
        if self.online_button is not None:
            widgets.append(self.online_button)
        if self.done_button is not None:
            widgets.append(self.done_button)
        for button in widgets:
            inside = button.contains(mx, my)
            button.hovered = inside and button.active
            handled = handled or inside
        if self.fov_slider is not None:
            self.fov_slider.hovered = _in_rect(
                self.fov_slider.x, self.fov_slider.y, self.fov_slider.w,
                self.fov_slider.h, mx, my,
            )
        return handled


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
        self.build()

    def build(self) -> None:
        """Виджеты страницы; пересобираются при resize/смене GUI scale."""
        self.back_button = Button(
            math.floor(self.width / 2.0) - 100.0, self.height - 27.0, 200.0,
            MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.back", "Back"), on_click=self._back,
        )

    def _back(self) -> None:
        if self.stack is not None:
            self.stack.pop()

    def title_key(self) -> str:
        return PAGE_TITLES.get(self.page, "options." + self.page)

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        if font is not None:
            title = lang.get_or(self.title_key(), self.page.title())
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 12.0, TITLE_COLOR)
        self.back_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        return self.back_button.handle_click(mx, my)


class SoundScreen(OptionsSubScreen):
    """Music & Sounds: громкость мастера."""

    def __init__(self, settings=None, stack=None, width=854.0, height=480.0):
        super().__init__("sounds", settings, stack, width, height)
        self.page = "sound"

    def build(self) -> None:
        super().build()
        cx = math.floor(self.width / 2.0)
        self.slider = Slider(
            cx - 154.0, 29.0, 150.0, 20.0,
            value=float(self.settings.master_volume),
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
        self.toggle_sprint = False
        self.auto_jump = False
        super().__init__("controls", settings, stack, width, height)
        self.page = "controls"

    def build(self) -> None:
        super().build()
        s = self.settings
        cx = math.floor(self.width / 2.0)
        self.slider = Slider(
            cx - 154.0, 29.0, 150.0, 20.0, value=float(s.sensitivity),
            min=0.0, max=1.0,
            label=lang.get_or("options.sensitivity", "Sensitivity"),
            on_change=self._set_sensitivity,
        )
        self.checkboxes = [
            Checkbox(cx + 4.0, 29.0, lang.get_or("options.toggleSprint", "Toggle Sprint"),
                     value=self.toggle_sprint, on_change=self._set_toggle_sprint,
                     hit_width=120.0),
            Checkbox(cx + 4.0, 53.0, lang.get_or("options.autoJump", "Auto-Jump"),
                     value=self.auto_jump, on_change=self._set_auto_jump,
                     hit_width=120.0),
        ]

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
        on_apply: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(width, height)
        self.settings = settings if settings is not None else Settings()
        self.stack = stack
        #: Вызывается после применения языка (App перестраивает экраны).
        self.on_apply = on_apply
        self.root = Path(root)
        self.languages: list[LanguageInfo] = (
            languages if languages is not None else available_languages(self.root)
        )
        self.choice: str = self.settings.language
        self.build()

    def build(self) -> None:
        """Виджеты ``Page::Language``; пересобираются при resize/GUI scale."""
        query = self.search.value if hasattr(self, "search") else ""
        scroll = self.list.scroll if hasattr(self, "list") else 0.0
        cx = math.floor(self.width / 2.0)
        # options_ui.rs L3305-3382: заголовок y=4, поиск (cx-100,17,200x20),
        # список (cx-110, top=36, 220x18, шаг 18), предупреждение y=h-45,
        # Font (cx-154,h-28) + Done (cx+4,h-28).
        self.search = TextInput(
            cx - 100.0, 17.0, 200.0, h=20.0, max_length=64,
            on_change=self._on_search,
        )
        self.search.value = query
        items = list(self.languages)
        q = query.lower()
        if q:
            items = [
                info for info in items
                if q in info.label().lower() or q in info.code.lower()
            ]
        self.list = ScrollableList(
            x=cx - 110.0,
            y=36.0,
            w=LANGUAGE_ROW_WIDTH,
            h=self.height - 53.0 - 36.0,
            items=items,
            item_height=LANGUAGE_ROW_STEP,
            label_of=lambda info: info.label(),
            on_select=self._on_select,
        )
        self.list.selected = self._index_of(self.choice)
        self.list.scroll = min(scroll, self.list.max_scroll())
        self.font_button = Button(
            cx - 154.0, self.height - 28.0, 150.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("options.font", "Font..."), on_click=self._open_font,
        )
        self.done_button = Button(
            cx + 4.0, self.height - 28.0, 150.0, MAIN_MENU_BUTTON_HEIGHT,
            lang.get_or("gui.done", "Done"), on_click=self.apply,
        )

    def _index_of(self, code: str) -> Optional[int]:
        for i, info in enumerate(self.list.items):
            if info.code == code:
                return i
        return None

    def _on_select(self, index: int, info: LanguageInfo) -> None:
        """Клик по строке (``options_ui.rs::WKind::LanguageRow``).

        Rust запоминает выбор и применяет его при закрытии; здесь тот же
        результат виден сразу: клик по другой строке немедленно применяет
        язык (иначе интерфейс ничем не подтверждает выбор). Повторный клик
        по уже выбранной строке закрывает экран, как ``back()`` в Rust.
        """
        if info.code == self.settings.language:
            self.apply()
            return
        self.list.selected = index
        self.choice = info.code
        self.set_language(info.code)
        if self.on_apply is not None:
            self.on_apply(info.code)

    def _on_search(self, query: str) -> None:
        """Фильтр поиска (options_ui.rs L3337-3342): label или код."""
        q = query.lower()
        if q:
            self.list.items = [
                info for info in self.languages
                if q in info.label().lower() or q in info.code.lower()
            ]
        else:
            self.list.items = list(self.languages)
        self.list.scroll = 0.0
        self.list.selected = self._index_of(self.choice)

    def _open_font(self) -> None:
        if self.stack is not None:
            self.stack.push(OptionsSubScreen(
                "font", self.settings, self.stack, self.width, self.height,
            ))

    def set_language(self, code: str) -> Language:
        """Загрузить и сделать текущим язык ``code``; вернуть объект языка."""
        language = load_language(code, self.root)
        lang.set(language)
        self.choice = code
        self.settings.language = code
        # Подписи виджетов зафиксированы при создании — обновляем их сразу,
        # иначе после смены языка на этом же экране остаётся старый текст.
        if hasattr(self, "font_button"):
            self.font_button.label = lang.get_or("options.font", "Font...")
        if hasattr(self, "done_button"):
            self.done_button.label = lang.get_or("gui.done", "Done")
        return language

    def apply(self) -> Optional[Language]:
        """Применить выбранный язык и закрыть экран (``back()`` в Rust)."""
        selected = self.list.selected
        items = self.list.items
        if selected is not None and 0 <= selected < len(items):
            self.choice = items[selected].code
        language = self.set_language(self.choice)
        if self.on_apply is not None:
            self.on_apply(self.choice)
        if self.stack is not None:
            self.stack.pop()
        return language

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        draw_menu_background(batch, font, self.width, self.height)
        if font is not None:
            title = lang.get_or("options.language.title", "Select Language")
            tw = font.width(title)
            draw_text(batch, font, title, (self.width - tw) / 2.0, 4.0, TITLE_COLOR)
        self.search.render(batch, font)
        self.list.render(batch, font)
        if font is not None:
            warning = lang.get_or(
                "options.languageAccuracyWarning",
                "Language translations may not be 100% accurate",
            )
            if warning:
                ww = font.width(warning)
                draw_text(
                    batch, font, warning, (self.width - ww) / 2.0,
                    self.height - 45.0, LANGUAGE_WARNING_COLOR,
                )
        self.font_button.render(batch, font)
        self.done_button.render(batch, font)

    def handle_click(self, mx: float, my: float) -> bool:
        if self.search.handle_click(mx, my):
            return True
        if self.font_button.handle_click(mx, my):
            return True
        if self.list.handle_click(mx, my):
            return True
        if self.done_button.handle_click(mx, my):
            return True
        return False

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        if self.search.handle_key(key) or (ch is not None and self.search.handle_char(ch)):
            return True
        if key == "escape":
            return self.apply() is not None
        return False

    def handle_scroll(self, dy: float) -> bool:
        return self.list.handle_scroll(dy)


from quadrix.render.graphics_ui import GraphicsScreen  # noqa: E402  (цикл: импорт после Screen)


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
    "PAGE_TITLES",
    "MAIN_MENU_ICONS",
    "LANGUAGE_WARNING_COLOR",
    "MENU_BACKGROUND_SPRITE",
    "MENU_BACKGROUND_TILE",
    "draw_menu_background",
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
    "calculate_scale",
    "effective_gui_scale",
    "gui_scaled_size",
    "draw_text",
    "load_language",
    "solid",
]
