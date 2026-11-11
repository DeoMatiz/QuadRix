"""UI-примитивы QuadRix (GUI PART 1).

Фундамент GUI: шрифт (bitmap, как в Horizon ``font.rs``), квады, батч
(один draw call), кнопка и слайдер. Полные меню/настройки/HUD — PART 2/3.

Порт Horizon (Rust → Python):
    * ``horizon-client-render/src/font.rs``      — ``Glyph``, ``Font``,
      загрузка bitmap-провайдеров (``Font/default.json`` → ``include/default.json``),
      ``used_width``, ``advance = floor(0.5 + used*scale) + 1``.
    * ``horizon-client-render/src/hud.rs``       — ``Rect``, ``rgba``,
      ``HudBatch.quad`` / ``rect_uv``, ``styled_text`` (геометрия глифа).
    * ``horizon-client-render/src/ui.rs``        — ``button``, ``slider``
      (только примитивы; nine-slice спрайты — PART 2).

Данные берутся ровно из ``.local`` (см. AGENTS.md, layout FIXED):
    .local/horizon-client/26.3/assets/minecraft/font/default.json
    .local/horizon-client/26.3/assets/minecraft/textures/font/*.png

Здесь нет ни ``pass``, ни ``TODO``: то, что не входит в PART 1 (unihex,
ttf, nine-slice, стили), помечено ``# FALLBACK`` с объяснением.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from quadrix.core.text import Text

# ---------------------------------------------------------------------------
# пути ассетов (FIXED, см. AGENTS.md)
# ---------------------------------------------------------------------------

# Корень ресурсов (resource pack root): внутри него — ``assets/minecraft/...``.
PACK_ROOT = Path(".local/horizon-client/26.3")
ASSETS_ROOT = PACK_ROOT / "assets/minecraft"
FONT_DIR = ASSETS_ROOT / "font"
FONT_TEXTURE_DIR = ASSETS_ROOT / "textures/font"
DEFAULT_FONT = "minecraft:default"

# Шрифт по умолчанию и реальный PNG, который он использует для ASCII.
ASCII_PNG = FONT_TEXTURE_DIR / "ascii.png"


# ---------------------------------------------------------------------------
# упаковка цвета (точно как Horizon: ``hud.rs::rgba``)
# ---------------------------------------------------------------------------

def rgba(r: int, g: int, b: int, a: int) -> int:
    """Упаковать RGBA в u32 как Horizon: ``a<<24 | b<<16 | g<<8 | r``."""
    return (
        (int(a) & 0xFF) << 24
        | (int(b) & 0xFF) << 16
        | (int(g) & 0xFF) << 8
        | (int(r) & 0xFF)
    )


def rgba_channels(color: int) -> tuple[int, int, int, int]:
    """Обратная к ``rgba``: ``(r, g, b, a)``."""
    color = int(color) & 0xFFFFFFFF
    return (color & 0xFF, (color >> 8) & 0xFF, (color >> 16) & 0xFF, (color >> 24) & 0xFF)


# Частые цвета (как в ванильных виджетах).
WHITE = rgba(255, 255, 255, 255)
BLACK = rgba(0, 0, 0, 255)


# ---------------------------------------------------------------------------
# геометрия
# ---------------------------------------------------------------------------

@dataclass
class Rect:
    """UV-прямоугольник в атласе (порт ``hud::Rect``)."""

    u0: float
    v0: float
    u1: float
    v1: float


@dataclass
class Glyph:
    """Готовый к отрисовке глиф (порт ``font::Glyph``).

    ``rect`` — UV-прямоугольник в атласе шрифта (``None`` для пробела и
    отсутствующего символа). ``left/top/right/bottom`` — рамка глифа
    относительно пера, в GUI-пикселях.
    """

    rect: Optional[Rect] = None
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    advance: float = 0.0
    # Смещение тени/жирного (1 для bitmap/TrueType, 0 для space).
    offset: float = 0.0


@dataclass
class Quad:
    """Один прямоугольник UI: позиция, размер, UV и цвет RGBA.

    Поля совпадают с задачей PART 1 и с координатами ``HudBatch.quad``:
    (x, y) — левый верхний угол, (w, h) — размер, (u0..v1) — UV,
    ``color`` — упакованный u32 (см. ``rgba``).
    """

    x: float
    y: float
    w: float
    h: float
    u0: float
    v0: float
    u1: float
    v1: float
    color: int

    def positions(self) -> list[tuple[float, float]]:
        """Четыре угла в порядке HudBatch.quad: TL, TR, BR, BL."""
        return [
            (self.x, self.y),
            (self.x + self.w, self.y),
            (self.x + self.w, self.y + self.h),
            (self.x, self.y + self.h),
        ]

    def uvs(self) -> list[tuple[float, float]]:
        return [
            (self.u0, self.v0),
            (self.u1, self.v0),
            (self.u1, self.v1),
            (self.u0, self.v1),
        ]


@dataclass
class Layout:
    """Простейший прямоугольный layout (без flex)."""

    x: float
    y: float
    w: float
    h: float

    def contains(self, mx: float, my: float) -> bool:
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def centered(self, inner_w: float, inner_h: float) -> tuple[float, float]:
        """Левый верхний угол для центрированной вставки."""
        return (
            self.x + (self.w - inner_w) / 2.0,
            self.y + (self.h - inner_h) / 2.0,
        )


# ---------------------------------------------------------------------------
# загрузка данных шрифта (порт font.rs::load_bitmap / providers)
# ---------------------------------------------------------------------------

def _read_json(root: Path, resource: str) -> Optional[Any]:
    """Прочитать JSON по ``root/<resource>``; ``None`` при любой ошибке."""
    try:
        return json.loads((root / resource).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resource_path(resource_id: str, folder: str, ext: str) -> str:
    """``minecraft:font/ascii.png`` → ``assets/minecraft/font/ascii.png``.

    Точно как ``font.rs::resource_path`` (в т.ч. ``trim_end_matches(ext)``).
    """
    ns, sep, path = resource_id.partition(":")
    if not sep:
        ns, path = "minecraft", resource_id
    if ext and path.endswith(ext):
        path = path[: -len(ext)]
    return f"assets/{ns}/{folder}/{path}{ext}"


def _providers(root: Path, resource_id: str, depth: int = 0) -> list[dict[str, Any]]:
    """Развернуть ссылки (``reference``) определения шрифта, в порядке.

    Порт ``font.rs::providers``. ``filter`` в PART 1 игнорируется (нет
    опций uniform/jp), но объект провайдера переносится как есть.
    """
    if depth > 8:
        return []
    definition = _read_json(root, _resource_path(resource_id, "font", ".json"))
    if not definition:
        return []
    out: list[dict[str, Any]] = []
    for provider in definition.get("providers", []):
        if provider.get("type") == "reference":
            nested = _providers(root, provider.get("id", ""), depth + 1)
            for n in nested:
                merged = dict(n.get("filter", {}))
                merged.update(provider.get("filter", {}))
                if merged:
                    n = {**n, "filter": merged}
                out.append(n)
        else:
            out.append(provider)
    return out


def load_png_rgba(path: Path | str) -> np.ndarray:
    """Загрузить PNG как RGBA-массив ``(H, W, 4)`` uint8 (реальный файл)."""
    from PIL import Image

    with Image.open(Path(path)) as img:
        return np.asarray(img.convert("RGBA"), dtype=np.uint8)


def _used_width(pixels: np.ndarray, x: int, y: int, w: int, h: int) -> int:
    """Обрезанная ширина ячейки (порт ``font.rs::used_width``).

    Сканируем столбцы справа налево; берём последний столбец с ненулевой
    альфой + 1.
    """
    for dx in range(w - 1, -1, -1):
        column = pixels[y : y + h, x + dx : x + dx + 1, 3]
        if column.size and bool(np.any(column)):
            return dx + 1
    return 0


def _glyph_rect(
    x: int, y: int, w: int, h: int, atlas: tuple[int, int]
) -> Rect:
    """UV глифа с отступом 0.01 текселя (порт ``font.rs::glyph_rect``)."""
    aw, ah = atlas
    return Rect(
        u0=(x + 0.01) / aw,
        v0=(y + 0.01) / ah,
        u1=((x + w) - 0.01) / aw,
        v1=((y + h) - 0.01) / ah,
    )


@dataclass
class _Sheet:
    """Одна bitmap-таблица: пиксели и метрики ячейки."""

    image: np.ndarray
    rows: int
    cols: int
    height: float
    ascent: float
    atlas_y: int = 0

    @property
    def cell_w(self) -> int:
        # Rust: целочисленное деление sw / cols.
        return self.image.shape[1] // self.cols

    @property
    def cell_h(self) -> int:
        return self.image.shape[0] // self.rows

    @property
    def scale(self) -> float:
        return self.height / self.cell_h


# ---------------------------------------------------------------------------
# шрифт
# ---------------------------------------------------------------------------

class Font:
    """Bitmap-шрифт QuadRix (порт ``font.rs::Font`` для bitmap/space).

    ``# FALLBACK: unihex/ttf провайдеры pending — PART 2.`` default.json
    ссылается на unifont (unihex, только CJK); без него ASCII/латиница и
    кириллица работают полностью, прочие кодовые точки дают ``missing``.
    """

    def __init__(
        self,
        atlas_image: np.ndarray,
        glyphs: dict[str, Glyph],
        advances: dict[str, Glyph],
        missing: Glyph,
        white: Rect,
        root: Path,
    ) -> None:
        self.atlas_image = atlas_image
        self.atlas_size = (atlas_image.shape[1], atlas_image.shape[0])
        self._glyphs = glyphs
        self._advances = advances
        self.missing = missing
        self.white = white
        self.root = root

    # -- загрузка --------------------------------------------------------

    @classmethod
    def load(
        cls,
        root: Path | str = PACK_ROOT,
        font_id: str = DEFAULT_FONT,
    ) -> "Font":
        """Загрузить шрифт из ``.local`` (реальные PNG + default.json)."""
        root = Path(root)
        providers = _providers(root, font_id)

        space: dict[str, Glyph] = {}
        sheets: list[_Sheet] = []
        sheet_chars: list[list[list[str]]] = []

        for provider in providers:
            ptype = provider.get("type")
            if ptype == "space":
                for ch, adv in provider.get("advances", {}).items():
                    # Первый провайдер побеждает (Rust: провайдеры по порядку).
                    space.setdefault(ch, Glyph(advance=float(adv), offset=0.0))
            elif ptype == "bitmap":
                file = provider.get("file", "")
                png_path = root / _resource_path(file, "textures", "")
                if not png_path.exists():
                    print(f"[QuadRix] font sheet not found: {png_path}")
                    continue
                image = load_png_rgba(png_path)
                rows = [list(r) for r in provider.get("chars", [])]
                if not rows or not rows[0]:
                    continue
                sheets.append(
                    _Sheet(
                        image=image,
                        rows=len(rows),
                        cols=len(rows[0]),
                        height=float(provider.get("height", 8.0)),
                        ascent=float(provider.get("ascent", 7.0)),
                    )
                )
                sheet_chars.append(rows)
            # unihex/ttf — вне PART 1 (см. docstring).

        # Собираем единый атлас: таблицы стопкой сверху вниз, ширина — max.
        atlas_w = max((s.image.shape[1] for s in sheets), default=1)
        total_h = sum(s.image.shape[0] for s in sheets) + 1  # +1: белый пиксель
        atlas = np.zeros((total_h, atlas_w, 4), dtype=np.uint8)
        y = 0
        for sheet in sheets:
            sh, sw = sheet.image.shape[:2]
            sheet.atlas_y = y
            atlas[y : y + sh, :sw] = sheet.image
            y += sh
        # Белый 1x1-пиксель для сплошных заливок (порт ``font.white()``).
        atlas[y, 0] = (255, 255, 255, 255)
        white = _glyph_rect(0, y, 1, 1, (atlas_w, total_h))

        # Теперь считаем глифы (atlas-координаты известны).
        glyphs: dict[str, Glyph] = {}
        for sheet, rows in zip(sheets, sheet_chars):
            cell_w = sheet.cell_w
            cell_h = sheet.cell_h
            scale = sheet.scale
            top = 7.0 - sheet.ascent
            right = cell_w * scale
            bottom = top + cell_h * scale
            for r, row in enumerate(rows):
                for c, ch in enumerate(row):
                    if ch == "\x00" or ch in glyphs:
                        continue
                    x = c * cell_w
                    yy = r * cell_h
                    used = _used_width(sheet.image, x, yy, cell_w, cell_h)
                    advance = math.floor(0.5 + used * scale) + 1.0
                    glyphs[ch] = Glyph(
                        rect=_glyph_rect(
                            x, sheet.atlas_y + yy, cell_w, cell_h,
                            (atlas_w, total_h),
                        ),
                        left=0.0,
                        top=top,
                        right=right,
                        bottom=bottom,
                        advance=advance,
                        offset=1.0,
                    )

        missing = Glyph(
            rect=None,
            left=0.0,
            top=0.0,
            right=5.0,
            bottom=8.0,
            advance=6.0,
            offset=1.0,
        )
        print(
            f"[QuadRix] font: {font_id} atlas={atlas_w}x{total_h} "
            f"sheets={len(sheets)} glyphs={len(glyphs)}"
        )
        return cls(atlas, glyphs, space, missing, white, root)

    # -- метрики ---------------------------------------------------------

    def glyph(self, ch: str) -> Glyph:
        """Глиф символа: space → bitmap → missing (порядок провайдеров)."""
        if ch in self._advances:
            return self._advances[ch]
        return self._glyphs.get(ch, self.missing)

    def advance(self, ch: str) -> float:
        return self.glyph(ch).advance

    def width(self, text: str) -> int:
        """Ширина строки в GUI-пикселях (порт ``Font::width``, ceil)."""
        if "§" in text:
            return self.width_text(Text.legacy(text))
        return int(math.ceil(sum(self.glyph(c).advance for c in text)))

    def width_text(self, text: Text) -> int:
        """Ширина компонента: legacy-коды — форматирование, не глифы."""
        plain = text.resolved().plain()
        return int(math.ceil(sum(self.glyph(c).advance for c in plain)))

    # -- отрисовка -------------------------------------------------------

    def render(
        self, text: str, x: float, y: float, color: int = WHITE
    ) -> list[Quad]:
        """Текст → список ``Quad`` (вершины для батча).

        Геометрия как ``hud.rs::styled_text``: ``x0 = pen + left``,
        ``x1 = pen + right``, ``y0 = y + top``, ``y1 = y + bottom``.
        """
        if not text:
            return []
        quads: list[Quad] = []
        cursor = float(x)
        for ch in text:
            glyph = self.glyph(ch)
            if glyph.rect is not None:
                r = glyph.rect
                quads.append(
                    Quad(
                        x=cursor + glyph.left,
                        y=float(y) + glyph.top,
                        w=glyph.right - glyph.left,
                        h=glyph.bottom - glyph.top,
                        u0=r.u0,
                        v0=r.v0,
                        u1=r.u1,
                        v1=r.v1,
                        color=color,
                    )
                )
            cursor += glyph.advance
        return quads


# ---------------------------------------------------------------------------
# батч: накопить квады и отрисовать одним draw call
# ---------------------------------------------------------------------------

@dataclass
class Batch:
    """Накопитель UI-квадов. ``flush`` — один draw call.

    Формат вершины: ``pos(2f) uv(2f) color(4f)`` — как у ``ui.vert``/``ui.frag``.
    """

    quads: list[Quad] = field(default_factory=list)
    texture: Any = None

    def add_quad(self, quad: Quad) -> None:
        self.quads.append(quad)

    def add_quads(self, quads: list[Quad]) -> None:
        self.quads.extend(quads)

    def clear(self) -> None:
        self.quads.clear()

    def vertices(self) -> np.ndarray:
        """Массив вершин ``(6*N, 8)`` float32 (два треугольника на квад)."""
        n = len(self.quads)
        arr = np.empty((n * 6, 8), dtype=np.float32)
        i = 0
        for q in self.quads:
            positions = q.positions()
            uvs = q.uvs()
            r, g, b, a = rgba_channels(q.color)
            col = (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
            for corner in (0, 1, 2, 0, 2, 3):
                px, py = positions[corner]
                u, v = uvs[corner]
                arr[i] = (px, py, u, v, *col)
                i += 1
        return arr

    def flush(
        self,
        backend: Any,
        program: Any = None,
        texture: Any = None,
        **kwargs: Any,
    ) -> int:
        """Отрисовать накопленное одним вызовом ``backend.draw``.

        Возвращает число вершин (0, если нечего рисовать).
        """
        if not self.quads:
            return 0
        data = self.vertices()
        count = data.shape[0]
        backend.draw(
            data,
            program,
            texture if texture is not None else self.texture,
            vertex_format="2f 2f 4f",
            attributes=("in_pos", "in_uv", "in_color"),
            count=count,
            **kwargs,
        )
        self.quads.clear()
        return count


# ---------------------------------------------------------------------------
# виджеты PART 1: кнопка и слайдер (простые; nine-slice — PART 2)
# ---------------------------------------------------------------------------

# FALLBACK: nine-slice спрайты ванильных виджетов (_button, slider) pending —
# PART 2 (нужен спрайтовый атлас). Пока фон — сплошная заливка.
_BUTTON_BG = rgba(70, 70, 70, 255)
_BUTTON_BG_HOVER = rgba(96, 96, 96, 255)
_BUTTON_BG_DISABLED = rgba(46, 46, 46, 255)
_BUTTON_TEXT = rgba(255, 255, 255, 255)
_BUTTON_TEXT_DISABLED = rgba(160, 160, 160, 255)
_SLIDER_TRACK = rgba(40, 40, 40, 255)
_SLIDER_HANDLE = rgba(200, 200, 200, 255)


@dataclass
class Button:
    """Кнопка: прямоугольник, подпись и обработчик нажатия (порт ``ui::button``)."""

    x: float
    y: float
    w: float
    h: float
    label: Any
    on_click: Optional[Callable[[], None]] = None
    active: bool = True
    hovered: bool = False

    def label_plain(self) -> str:
        if isinstance(self.label, Text):
            return self.label.plain()
        return str(self.label)

    def contains(self, mx: float, my: float) -> bool:
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def click(self) -> bool:
        """Вызвать ``on_click`` (только если активна). ``True``, если клик принят."""
        if not self.active:
            return False
        if self.on_click is not None:
            self.on_click()
        return True

    def handle_click(self, mx: float, my: float) -> bool:
        """Клик мышью: нажатие принимается, если курсор внутри и кнопка активна."""
        if self.contains(mx, my):
            return self.click()
        return False

    def render(
        self,
        batch: Batch,
        font: Optional[Font] = None,
        *,
        shadow: bool = True,
    ) -> None:
        """Добавить квады кнопки: фон + (если есть шрифт) центрированную подпись."""
        if not self.active:
            bg = _BUTTON_BG_DISABLED
        elif self.hovered:
            bg = _BUTTON_BG_HOVER
        else:
            bg = _BUTTON_BG
        # Фон: белый пиксель атласа, чтобы пройти через текстуру шрифта.
        if font is not None:
            batch.add_quad(_solid(font, self.x, self.y, self.w, self.h, bg))
        else:
            batch.add_quad(
                Quad(self.x, self.y, self.w, self.h, 0.0, 0.0, 1.0, 1.0, bg)
            )
        if font is None:
            return
        label = self.label_plain()
        if not label:
            return
        text_w = font.width(label)
        tx = self.x + (self.w - text_w) / 2.0
        ty = self.y + (self.h - 8.0) / 2.0
        color = _BUTTON_TEXT if self.active else _BUTTON_TEXT_DISABLED
        if shadow and self.active:
            batch.add_quads(
                font.render(label, tx + 1.0, ty + 1.0, rgba(0, 0, 0, 160))
            )
        batch.add_quads(font.render(label, tx, ty, color))


@dataclass
class Slider:
    """Слайдер: значение в ``[min, max]``, ручка 8px (порт ``ui::slider``)."""

    x: float
    y: float
    w: float
    h: float = 20.0
    value: float = 0.0
    min: float = 0.0
    max: float = 1.0
    label: Any = ""
    on_change: Optional[Callable[[float], None]] = None
    active: bool = True
    dragging: bool = False
    handle_w: float = 8.0

    def fraction(self) -> float:
        """Доля 0..1 (как ванильный ``AbstractSliderButton.value``)."""
        span = self.max - self.min
        if span == 0.0:
            return 0.0
        return min(1.0, max(0.0, (self.value - self.min) / span))

    def set_value(self, value: float) -> None:
        """Установить значение с клампом; вызвать ``on_change``, если изменилось."""
        clamped = min(self.max, max(self.min, float(value)))
        if clamped != self.value:
            self.value = clamped
            if self.on_change is not None:
                self.on_change(clamped)

    def value_from_mouse(self, mx: float) -> float:
        """Значение по X-координате мыши (порт ``ui::slider_value``)."""
        track = max(1.0, self.w - self.handle_w)
        frac = min(1.0, max(0.0, (mx - (self.x + self.handle_w / 2.0)) / track))
        return self.min + frac * (self.max - self.min)

    def click(self, mx: float) -> bool:
        """Клик по дорожке: переставить значение. ``True``, если изменилось."""
        if not self.active:
            return False
        before = self.value
        self.set_value(self.value_from_mouse(mx))
        return self.value != before

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        """Дорожка + ручка (+ подпись, если есть шрифт)."""
        if font is None:
            batch.add_quad(
                Quad(self.x, self.y, self.w, self.h, 0.0, 0.0, 1.0, 1.0, _SLIDER_TRACK)
            )
            return
        batch.add_quad(_solid(font, self.x, self.y, self.w, self.h, _SLIDER_TRACK))
        hx = self.x + math.floor(self.fraction() * (self.w - self.handle_w))
        batch.add_quad(
            _solid(font, hx, self.y, self.handle_w, self.h, _SLIDER_HANDLE)
        )
        label = self.label.plain() if isinstance(self.label, Text) else str(self.label)
        if label:
            text_w = font.width(label)
            tx = self.x + (self.w - text_w) / 2.0
            ty = self.y + (self.h - 8.0) / 2.0
            batch.add_quads(font.render(label, tx, ty, _BUTTON_TEXT))


def _solid(
    font: Font, x: float, y: float, w: float, h: float, color: int
) -> Quad:
    """Сплошной прямоугольник через белый пиксель атласа шрифта."""
    r = font.white
    return Quad(x, y, w, h, r.u0, r.v0, r.u1, r.v1, color)


__all__ = [
    "ASSETS_ROOT",
    "ASCII_PNG",
    "Batch",
    "Button",
    "DEFAULT_FONT",
    "FONT_DIR",
    "FONT_TEXTURE_DIR",
    "PACK_ROOT",
    "Font",
    "Glyph",
    "Layout",
    "Quad",
    "Rect",
    "Slider",
    "WHITE",
    "BLACK",
    "load_png_rgba",
    "rgba",
    "rgba_channels",
]
