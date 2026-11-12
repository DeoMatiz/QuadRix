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
    #: Ключ текстуры в ``Batch.textures``. ``None`` — атлас шрифта
    #: (PART 1); строка (например ``"gui"``) — спрайтовый атлас.
    texture: Any = None

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
    #: Ключ текстуры -> GPU-текстура. Квады с ``texture="gui"`` биндят
    #: ``textures["gui"]``; квады с ``texture=None`` — ``self.texture``.
    textures: dict[Any, Any] = field(default_factory=dict)
    #: Спрайтовый атлас (``GuiAtlas``), откуда кнопки/слайдеры берут UV.
    atlas: Any = None

    def add_quad(self, quad: Quad) -> None:
        self.quads.append(quad)

    def add_quads(self, quads: list[Quad]) -> None:
        self.quads.extend(quads)

    def clear(self) -> None:
        self.quads.clear()

    @staticmethod
    def _vertices(quads: list[Quad]) -> np.ndarray:
        """Массив вершин ``(6*N, 8)`` float32 (два треугольника на квад)."""
        n = len(quads)
        arr = np.empty((n * 6, 8), dtype=np.float32)
        i = 0
        for q in quads:
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

    def vertices(self, quads: Optional[list[Quad]] = None) -> np.ndarray:
        """Массив вершин ``(6*N, 8)`` float32 (два треугольника на квад)."""
        return self._vertices(self.quads if quads is None else quads)

    def flush(
        self,
        backend: Any,
        program: Any = None,
        texture: Any = None,
        **kwargs: Any,
    ) -> int:
        """Отрисовать накопленное. Квады группируются по текстуре (в порядке
        художника), на каждую группу — один ``backend.draw``.

        Возвращает число вершин (0, если нечего рисовать).
        """
        if not self.quads:
            return 0
        default_tex = texture if texture is not None else self.texture
        # UI — 2D: после Y-флипа проекции квады обходят по часовой стрелке,
        # поэтому отсечение граней выключаем, а прозрачность включаем.
        options: dict[str, Any] = {
            "depth_test": False,
            "cull_face": False,
            "blend": True,
        }
        options.update(kwargs)
        total = 0
        i = 0
        n = len(self.quads)
        while i < n:
            key = self.quads[i].texture
            j = i + 1
            while j < n and self.quads[j].texture == key:
                j += 1
            group = self.quads[i:j]
            data = self._vertices(group)
            count = data.shape[0]
            gpu_tex = default_tex if key is None else self.textures.get(key, default_tex)
            backend.draw(
                data,
                program,
                gpu_tex,
                vertex_format="2f 2f 4f",
                attributes=("in_pos", "in_uv", "in_color"),
                count=count,
                **options,
            )
            total += count
            i = j
        self.quads.clear()
        return total


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
    """Кнопка: прямоугольник, подпись и обработчик нажатия (порт ``ui::button``).

    Спрайты: ``gui/sprites/widget/button[_highlighted|_disabled]`` —
    nine-slice (настройки) или половинный растяг (главное меню,
    ``title.rs``). Если атласа нет — FALLBACK: сплошная заливка.
    """

    x: float
    y: float
    w: float
    h: float
    label: Any
    on_click: Optional[Callable[[], None]] = None
    active: bool = True
    hovered: bool = False
    #: ``True`` — стиль главного меню (левая/правая половины спрайта).
    title_style: bool = False
    #: Иконка-спрайт (кнопки-иконки главного меню); подпись не рисуется.
    icon: Optional[str] = None
    icon_size: float = 15.0

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
        """Добавить квады кнопки: спрайт (или фон) + подпись/иконку.

        Как ``title.rs`` (L3249-3276): фон-спрайт рисуется ВСЕГДА (в том
        числе для кнопок-иконок), затем либо иконка (без подписи), либо
        подпись.
        """
        atlas = getattr(batch, "atlas", None)
        color = _BUTTON_TEXT if self.active else _BUTTON_TEXT_DISABLED
        drawn = False
        if atlas is not None:
            sprite = atlas.button_sprite(self.active, self.hovered)
            if self.title_style:
                drawn = atlas.title_button(batch, sprite, self.x, self.y, self.w, self.h)
            else:
                drawn = atlas.nine_slice(batch, sprite, self.x, self.y, self.w, self.h)
        if not drawn:
            # FALLBACK: сплошная заливка (нет атласа/спрайта).
            if not self.active:
                bg = _BUTTON_BG_DISABLED
            elif self.hovered:
                bg = _BUTTON_BG_HOVER
            else:
                bg = _BUTTON_BG
            if font is not None:
                batch.add_quad(_solid(font, self.x, self.y, self.w, self.h, bg))
            else:
                batch.add_quad(
                    Quad(self.x, self.y, self.w, self.h, 0.0, 0.0, 1.0, 1.0, bg)
                )
        if self.icon is not None:
            # Кнопка-иконка: спрайт уже нарисован, подпись не рисуется.
            self._render_icon(batch, atlas)
            return
        self._render_label(batch, font, color, shadow)

    def _render_label(
        self, batch: Batch, font: Optional[Font], color: int, shadow: bool
    ) -> None:
        if font is None:
            return
        label = self.label_plain()
        if not label:
            return
        text_w = font.width(label)
        # title.rs draw_label_at: центр кнопки, y + floor((h - 8) / 2).
        tx = self.x + (self.w - text_w) / 2.0
        ty = self.y + math.floor((self.h - 8.0) / 2.0)
        if shadow and self.active:
            batch.add_quads(
                font.render(label, tx + 1.0, ty + 1.0, rgba(0, 0, 0, 160))
            )
        batch.add_quads(font.render(label, tx, ty, color))

    def _render_icon(self, batch: Batch, atlas: Any) -> None:
        sprite = self.icon
        if sprite is None:
            return
        size = self.icon_size
        # CenteredIcon: центр кнопки минус половина иконки (title.rs L3266).
        ix = self.x + math.floor(self.w / 2.0) - math.floor(size / 2.0)
        iy = self.y + 10.0 - math.floor(size / 2.0)
        if atlas is not None and atlas.blit(batch, sprite, ix, iy, size, size):
            return
        # FALLBACK: без атласа рисуем заливку в цвете кнопки.
        batch.add_quad(
            Quad(ix, iy, size, size, 0.0, 0.0, 1.0, 1.0, _BUTTON_BG)
        )


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
    hovered: bool = False
    focused: bool = False
    can_change_value: bool = False

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

    def contains(self, mx: float, my: float) -> bool:
        """Курсор внутри виджета (порт ``ui.rs::hovered``)."""
        return self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h

    def handle_click(self, mx: float, my: float) -> bool:
        """Нажатие ЛКМ: взять ручку и тянуть (порт ``options_ui.rs`` L4251-4257).

        Rust при нажатии ставит ``dragging = Some(opt)`` и сразу считает
        значение по позиции курсора. Без явного ``release`` ручка оставалась
        бы прикованной к мыши — см. :meth:`handle_release`.
        """
        if not self.active or not self.contains(mx, my):
            return False
        self.dragging = True
        self.focused = True
        self.can_change_value = True
        self.set_value(self.value_from_mouse(mx))
        return True

    def handle_drag(self, mx: float) -> bool:
        """Движение мыши при зажатой кнопке: тянем ручку (порт ``drag_slider``).

        Rust обновляет значение только пока ``dragging == Some(opt)``; после
        отпускания мыши ``handle_release`` снимает флаг, и движение больше
        значение не меняет.
        """
        if not self.active or not self.dragging:
            return False
        before = self.value
        self.set_value(self.value_from_mouse(mx))
        return self.value != before

    def handle_release(self) -> bool:
        """Отпускание ЛКМ: снять ручку (порт ``options_ui.rs::release``).

        Rust: ``self.dragging.take()`` — ручка отпускается всегда, даже если
        значение не менялось. Возвращает ``True``, если слайдер был в drag.
        """
        was = self.dragging
        self.dragging = False
        self.can_change_value = False
        return was

    def render(self, batch: Batch, font: Optional[Font] = None) -> None:
        """Дорожка + ручка + подпись (порт ``ui::slider_ext``).

        Спрайты ``gui/sprites/widget/slider`` и ``slider_handle``; без
        атласа — FALLBACK: сплошная заливка.
        """
        atlas = getattr(batch, "atlas", None)
        hx = self.x + math.floor(self.fraction() * (self.w - self.handle_w))
        track_sprite, handle_sprite = self._sprites()
        drawn = False
        if atlas is not None:
            t = atlas.nine_slice(batch, track_sprite, self.x, self.y, self.w, self.h)
            h = atlas.nine_slice(batch, handle_sprite, hx, self.y, self.handle_w, self.h)
            drawn = t and h
        if not drawn:
            if font is not None:
                batch.add_quad(_solid(font, self.x, self.y, self.w, self.h, _SLIDER_TRACK))
                batch.add_quad(_solid(font, hx, self.y, self.handle_w, self.h, _SLIDER_HANDLE))
            else:
                batch.add_quad(
                    Quad(self.x, self.y, self.w, self.h, 0.0, 0.0, 1.0, 1.0, _SLIDER_TRACK)
                )
                batch.add_quad(
                    Quad(hx, self.y, self.handle_w, self.h, 0.0, 0.0, 1.0, 1.0, _SLIDER_HANDLE)
                )
        if font is None:
            return
        label = self.label.plain() if isinstance(self.label, Text) else str(self.label)
        if label:
            text_w = font.width(label)
            tx = self.x + (self.w - text_w) / 2.0
            ty = self.y + (self.h - 8.0) / 2.0
            batch.add_quads(font.render(label, tx, ty, _BUTTON_TEXT))

    def _sprites(self) -> tuple[str, str]:
        """``ui.rs::slider_sprites_ext`` — дорожка и ручка."""
        track = (
            "gui/sprites/widget/slider_highlighted"
            if self.dragging or (self.active and self.focused and not self.can_change_value)
            else "gui/sprites/widget/slider"
        )
        handle = (
            "gui/sprites/widget/slider_handle_highlighted"
            if self.active and (self.hovered or self.can_change_value or self.dragging)
            else "gui/sprites/widget/slider_handle"
        )
        return track, handle


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
