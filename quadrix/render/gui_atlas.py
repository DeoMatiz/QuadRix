"""Спрайтовый атлас GUI QuadRix (порт Horizon ``ui.rs`` + ``hud.rs``).

В отличие от ``font.rs`` (атлас шрифта, PART 1), меню рисует ванильные
**спрайты** ``assets/minecraft/textures/gui/**``: кнопки, слайдеры,
флажки, логотип, фон из «земли», иконки. Horizon держит их в отдельном
``HudAtlas`` (пиксельная фильтрация, NEAREST). Мы собираем нужные PNG в
один упакованный атлас и даём функции ровно по Rust:

    * ``sub`` / ``tile`` / ``draw_nine_slice`` / ``nine_slice``  — ui.rs
    * ``sprite_scaled`` / ``sprite_region`` / ``tiled``          — hud.rs
    * ``scaling`` (border из ``.png.mcmeta``)                    — ui.rs

Координаты берём ровно из ``.local`` (layout FIXED, см. AGENTS.md):
    .local/horizon-client/26.3/assets/minecraft/textures/gui/...

FALLBACK: если PNG нет — спрайт просто не регистрируется, и вызывающий
код рисует сплошную заливку (как ``ui.rs`` при отсутствии спрайта).
Логотип ``gui/title/edition`` в Horizon пересобирается из ванильного
арта в «RUST EDITION» (``title_edition.rs``); мы грузим ``edition.png``
как есть и помечаем это ниже.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from quadrix.render.ui import Quad, load_png_rgba, rgba

# Корень ресурсов (FIXED).
PACK_ROOT = Path(".local/horizon-client/26.3")
TEXTURES = PACK_ROOT / "assets/minecraft/textures"

#: Ключ текстуры для ``Batch.textures``: все спрайтовые квады ссылаются
#: на него, шрифтовые — на ``None``.
GUI_TEXTURE = "gui"

#: Спрайт -> (путь относительно textures, border l,t,r,b).
#: Border — из ``.png.mcmeta`` (``gui.scaling.border``), иначе из
#: ``ui.rs::scaling`` (fallback: button [3;4], slider_handle [2,2,2,3],
#: прочее [1;4]).
SPRITES: dict[str, tuple[str, Optional[tuple[int, int, int, int]]]] = {
    "gui/sprites/widget/button": ("gui/sprites/widget/button.png", (3, 3, 3, 3)),
    "gui/sprites/widget/button_highlighted": (
        "gui/sprites/widget/button_highlighted.png",
        (3, 3, 3, 3),
    ),
    "gui/sprites/widget/button_disabled": (
        "gui/sprites/widget/button_disabled.png",
        (3, 3, 3, 3),
    ),
    "gui/sprites/widget/slider": ("gui/sprites/widget/slider.png", (1, 1, 1, 1)),
    "gui/sprites/widget/slider_highlighted": (
        "gui/sprites/widget/slider_highlighted.png",
        (1, 1, 1, 1),
    ),
    "gui/sprites/widget/slider_handle": (
        "gui/sprites/widget/slider_handle.png",
        (2, 2, 2, 3),
    ),
    "gui/sprites/widget/slider_handle_highlighted": (
        "gui/sprites/widget/slider_handle_highlighted.png",
        (2, 2, 2, 3),
    ),
    "gui/sprites/widget/checkbox": ("gui/sprites/widget/checkbox.png", None),
    "gui/sprites/widget/checkbox_highlighted": (
        "gui/sprites/widget/checkbox_highlighted.png",
        None,
    ),
    "gui/sprites/widget/checkbox_selected": (
        "gui/sprites/widget/checkbox_selected.png",
        None,
    ),
    "gui/sprites/widget/checkbox_selected_highlighted": (
        "gui/sprites/widget/checkbox_selected_highlighted.png",
        None,
    ),
    "gui/menu_background": ("gui/menu_background.png", None),
    "gui/menu_list_background": ("gui/menu_list_background.png", None),
    "gui/header_separator": ("gui/header_separator.png", None),
    "gui/footer_separator": ("gui/footer_separator.png", None),
    "gui/title/minecraft": ("gui/title/minecraft.png", None),
    "gui/title/edition": ("gui/title/edition.png", None),
    "gui/sprites/icon/language": ("gui/sprites/icon/language.png", None),
    "gui/sprites/icon/accessibility": ("gui/sprites/icon/accessibility.png", None),
    "gui/sprites/friends/friends": ("gui/sprites/friends/friends.png", None),
    # -- Gameplay PART 2: hotbar и инвентарь -----------------------------
    "gui/sprites/hud/hotbar": ("gui/sprites/hud/hotbar.png", None),
    "gui/sprites/hud/hotbar_selection": (
        "gui/sprites/hud/hotbar_selection.png",
        None,
    ),
    "gui/sprites/container/slot": ("gui/sprites/container/slot.png", None),
    "gui/container/inventory": ("gui/container/inventory.png", None),
}

#: Логический размер в GUI-пикселях там, где он не равен размеру PNG
#: (``LogoRenderer``/``title_edition``: 1024x256 рисуется как 256x64).
LOGICAL: dict[str, tuple[int, int]] = {
    "gui/title/minecraft": (256, 64),
    "gui/title/edition": (128, 16),
}

#: Упаковка: максимальная ширина атласа (стеллажами).
_ATLAS_WIDTH = 512
_PAD = 1


@dataclass
class Sprite:
    """Спрайт в атласе: UV, логический размер, border и размер PNG."""

    u0: float
    v0: float
    u1: float
    v1: float
    logical_w: int
    logical_h: int
    tex_w: int
    tex_h: int
    border: Optional[tuple[int, int, int, int]]


def _border_value(raw: Any) -> Optional[tuple[int, int, int, int]]:
    """``gui.scaling.border`` из mcmeta: одно число или объект l/t/r/b."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        n = int(raw)
        return (n, n, n, n)
    if isinstance(raw, dict):
        return (
            int(raw.get("left", 0)),
            int(raw.get("top", 0)),
            int(raw.get("right", 0)),
            int(raw.get("bottom", 0)),
        )
    return None


def _scaling(
    png_path: Path,
    default_border: Optional[tuple[int, int, int, int]],
    tex_w: int,
    tex_h: int,
) -> tuple[int, int, Optional[tuple[int, int, int, int]]]:
    """Прочитать ``.png.mcmeta`` (logical width/height + border).

    Порт ``ui.rs::nine_slice_metadata``: если метаданных нет — логический
    размер равен размеру PNG, а границы берутся из ``ui.rs::scaling``
    (``default_border``); отсутствие границ → растягивание целого спрайта.
    """
    meta = png_path.with_name(png_path.name + ".mcmeta")
    logical_w, logical_h, border = tex_w, tex_h, default_border
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        scaling = (data.get("gui") or {}).get("scaling") or {}
        if "width" in scaling:
            logical_w = int(scaling["width"])
        if "height" in scaling:
            logical_h = int(scaling["height"])
        border = _border_value(scaling.get("border"))
    return logical_w, logical_h, border


def _shelf_pack(
    images: list[tuple[str, np.ndarray]],
) -> tuple[np.ndarray, dict[str, tuple[int, int, int, int]]]:
    """Разложить картинки стеллажами; вернуть атлас и ``id -> (x,y,w,h)``."""
    # Сортировка по высоте убыв. — компактнее для разных по размеру спрайтов.
    order = sorted(images, key=lambda item: -item[1].shape[0])
    # Ширина атласа — не меньше самого широкого спрайта (логотип 1024x256).
    widest = max((image.shape[1] for _id, image in images), default=_ATLAS_WIDTH)
    width = max(_ATLAS_WIDTH, widest + 2 * _PAD)
    placements: dict[str, tuple[int, int, int, int]] = {}
    x = _PAD
    y = _PAD
    row_h = 0
    for sprite_id, image in order:
        h, w = image.shape[:2]
        if x + w + _PAD > width:
            x = _PAD
            y += row_h + _PAD
            row_h = 0
        placements[sprite_id] = (x, y, w, h)
        x += w + _PAD
        row_h = max(row_h, h)
    total_h = y + row_h + _PAD
    atlas = np.zeros((total_h, width, 4), dtype=np.uint8)
    for sprite_id, image in images:
        px, py, w, h = placements[sprite_id]
        atlas[py : py + h, px : px + w] = image
    return atlas, placements


class GuiAtlas:
    """Упакованный атлас ванильных GUI-спрайтов (порт ``HudAtlas``)."""

    def __init__(
        self,
        image: np.ndarray,
        sprites: dict[str, Sprite],
        width: int,
        height: int,
    ) -> None:
        self.image = image
        self.sprites = sprites
        self.width = width
        self.height = height

    # -- загрузка --------------------------------------------------------

    @classmethod
    def load(cls, root: Path | str = PACK_ROOT) -> "GuiAtlas":
        """Загрузить спрайты из ``.local`` и упаковать в один атлас."""
        textures_root = Path(root) / "assets/minecraft/textures"
        loaded: list[tuple[str, np.ndarray]] = []
        for sprite_id, (rel, _border) in SPRITES.items():
            path = textures_root / rel
            if not path.exists():
                # FALLBACK: нет PNG — спрайт не регистрируем (рисуем цвет).
                print(f"[QuadRix] gui atlas: нет спрайта {rel}")
                continue
            try:
                loaded.append((sprite_id, load_png_rgba(path)))
            except Exception as exc:  # noqa: BLE001 - битый PNG не критичен
                print(f"[QuadRix] gui atlas: не прочитан {rel}: {exc}")

        if not loaded:
            empty = np.zeros((1, 1, 4), dtype=np.uint8)
            return cls(empty, {}, 1, 1)

        atlas, placements = _shelf_pack(loaded)
        height, width = atlas.shape[:2]
        sprites: dict[str, Sprite] = {}
        for sprite_id, image in loaded:
            px, py, w, h = placements[sprite_id]
            rel, default_border = SPRITES[sprite_id]
            logical_w, logical_h, border = _scaling(
                textures_root / rel, default_border, w, h
            )
            # LOGICAL — переопределения для спрайтов, у которых mcmeta нет
            # (логотипы title грузятся как есть, но рисуются в меньшем размере).
            if sprite_id in LOGICAL:
                logical_w, logical_h = LOGICAL[sprite_id]
            sprites[sprite_id] = Sprite(
                u0=px / width,
                v0=py / height,
                u1=(px + w) / width,
                v1=(py + h) / height,
                logical_w=logical_w,
                logical_h=logical_h,
                tex_w=w,
                tex_h=h,
                border=border,
            )
        print(
            f"[QuadRix] gui atlas: {width}x{height} спрайтов={len(sprites)}"
        )
        return cls(atlas, sprites, width, height)

    # -- геометрия (ui.rs::sub / tile) -----------------------------------

    def _sub(
        self, s: Sprite, x: float, y: float, w: float, h: float
    ) -> tuple[float, float, float, float]:
        """Регион ``[x,y,w,h]`` в логических единицах спрайта -> UV."""
        du = (s.u1 - s.u0) / s.logical_w
        dv = (s.v1 - s.v0) / s.logical_h
        return (s.u0 + x * du, s.v0 + y * dv, s.u0 + (x + w) * du, s.v0 + (y + h) * dv)

    def _quad(
        self, x: float, y: float, w: float, h: float, uv: tuple[float, float, float, float],
        color: int,
    ) -> Quad:
        u0, v0, u1, v1 = uv
        return Quad(x, y, w, h, u0, v0, u1, v1, color, GUI_TEXTURE)

    def _tile(
        self, batch: Any, s: Sprite,
        sx: float, sy: float, sw: float, sh: float,
        dx: float, dy: float, dw: float, dh: float, color: int,
    ) -> None:
        """``ui.rs::tile`` — повтор региона ``src`` по ``dst``, срез края."""
        if sw <= 0.0 or sh <= 0.0 or dw <= 0.0 or dh <= 0.0:
            return
        y = 0.0
        while y < dh:
            h = min(sh, dh - y)
            x = 0.0
            while x < dw:
                w = min(sw, dw - x)
                batch.add_quad(
                    self._quad(dx + x, dy + y, w, h, self._sub(s, sx, sy, w, h), color)
                )
                x += sw
            y += sh

    # -- nine-slice (ui.rs::nine_slice / draw_nine_slice) ----------------

    def nine_slice(
        self, batch: Any, sprite_id: str, x: float, y: float, w: float, h: float,
        color: int = 0xFFFFFFFF,
    ) -> bool:
        """Нарисовать nine-slice спрайт. ``False``, если спрайта нет."""
        s = self.sprites.get(sprite_id)
        if s is None:
            return False
        self._draw_nine_slice(batch, s, x, y, w, h, color)
        return True

    def _draw_nine_slice(
        self, batch: Any, s: Sprite, x: float, y: float, w: float, h: float, color: int,
    ) -> None:
        if s.border is None:
            batch.add_quad(self._quad(x, y, w, h, (s.u0, s.v0, s.u1, s.v1), color))
            return
        # Отсутствие метаданных -> логический размер = размер PNG.
        lw, lh = float(s.logical_w), float(s.logical_h)
        sw, sh = lw, lh
        l, t, rr, b = (float(v) for v in s.border)
        half_w, half_h = float(int(w / 2.0)), float(int(h / 2.0))
        l, rr = min(l, half_w), min(rr, half_w)
        t, b = min(t, half_h), min(b, half_h)

        def part(tx: float, ty: float, dst: tuple[float, float, float, float]) -> None:
            if dst[2] != 0.0 and dst[3] != 0.0:
                batch.add_quad(
                    self._quad(dst[0], dst[1], dst[2], dst[3],
                               self._sub(s, tx, ty, dst[2], dst[3]), color)
                )

        def inner(dst: tuple[float, float, float, float],
                  src: tuple[float, float, float, float]) -> None:
            if dst[2] <= 0.0 or dst[3] <= 0.0:
                return
            self._tile(batch, s, src[0], src[1], src[2], src[3],
                       dst[0], dst[1], dst[2], dst[3], color)

        if w == sw and h == sh:
            part(0.0, 0.0, (x, y, w, h))
            return
        if h == sh:
            part(0.0, 0.0, (x, y, l, h))
            inner((x + l, y, w - rr - l, h), (l, 0.0, sw - rr - l, sh))
            part(sw - rr, 0.0, (x + w - rr, y, rr, h))
            return
        if w == sw:
            part(0.0, 0.0, (x, y, w, t))
            inner((x, y + t, w, h - b - t), (0.0, t, sw, sh - b - t))
            part(0.0, sh - b, (x, y + h - b, w, b))
            return
        cw, ch = w - rr - l, h - b - t
        scw, sch = sw - rr - l, sh - b - t
        part(0.0, 0.0, (x, y, l, t))
        inner((x + l, y, cw, t), (l, 0.0, scw, t))
        part(sw - rr, 0.0, (x + w - rr, y, rr, t))
        part(0.0, sh - b, (x, y + h - b, l, b))
        inner((x + l, y + h - b, cw, b), (l, sh - b, scw, b))
        part(sw - rr, sh - b, (x + w - rr, y + h - b, rr, b))
        inner((x, y + t, l, ch), (0.0, t, l, sch))
        inner((x + l, y + t, cw, ch), (l, t, scw, sch))
        inner((x + w - rr, y + t, rr, ch), (sw - rr, t, rr, sch))

    # -- title-кнопки (title.rs: левая/правая половина спрайта) ----------

    def title_button(
        self, batch: Any, sprite_id: str, x: float, y: float, w: float, h: float,
        color: int = 0xFFFFFFFF,
    ) -> bool:
        """Кнопка главного меню: левая и правая половины 200x20 спрайта.

        ``title.rs`` (L3248): «Nine-slice approximation: left and right
        halves of the 200-wide sprite» — не настоящий nine-slice.
        """
        s = self.sprites.get(sprite_id)
        if s is None:
            return False
        half = w / 2.0
        left = (s.u0, s.v0, s.u0 + (s.u1 - s.u0) * (half / s.logical_w), s.v1)
        right = (s.u1 - (s.u1 - s.u0) * (half / s.logical_w), s.v0, s.u1, s.v1)
        batch.add_quad(self._quad(x, y, half, h, left, color))
        batch.add_quad(self._quad(x + half, y, half, h, right, color))
        return True

    # -- stretched / region / tiled (hud.rs) -----------------------------

    def blit(
        self, batch: Any, sprite_id: str, x: float, y: float, w: float, h: float,
        color: int = 0xFFFFFFFF,
    ) -> bool:
        """``hud.rs::sprite_scaled`` — весь спрайт растянут в ``w x h``."""
        s = self.sprites.get(sprite_id)
        if s is None:
            return False
        batch.add_quad(self._quad(x, y, w, h, (s.u0, s.v0, s.u1, s.v1), color))
        return True

    def region(
        self, batch: Any, sprite_id: str,
        x: float, y: float, w: float, h: float,
        logical_w: float, logical_h: float, color: int = 0xFFFFFFFF,
    ) -> bool:
        """``hud.rs::sprite_region`` — верхний левый угол ``w x h`` (логич.)."""
        s = self.sprites.get(sprite_id)
        if s is None:
            return False
        u1 = s.u0 + (s.u1 - s.u0) * w / logical_w
        v1 = s.v0 + (s.v1 - s.v0) * h / logical_h
        batch.add_quad(self._quad(x, y, w, h, (s.u0, s.v0, u1, v1), color))
        return True

    def tiled(
        self, batch: Any, sprite_id: str,
        x: float, y: float, w: float, h: float, size: float,
        color: int = 0xFFFFFFFF,
    ) -> bool:
        """``ui.rs::tiled_sized`` — целый спрайт, повторённый квадратом ``size``.

        Rust ``sub(r, [size,size], [0,0,size,size])`` всегда даёт весь UV
        спрайта, поэтому каждая плитка — это весь спрайт, растянутый в
        ``size`` GUI-пикселей (меню-фон: 16px текстура, плитка 32px).
        """
        s = self.sprites.get(sprite_id)
        if s is None:
            return False
        if size <= 0.0 or w <= 0.0 or h <= 0.0:
            return True
        uv = (s.u0, s.v0, s.u1, s.v1)
        yy = 0.0
        while yy < h:
            th = min(size, h - yy)
            xx = 0.0
            while xx < w:
                tw = min(size, w - xx)
                batch.add_quad(self._quad(x + xx, y + yy, tw, th, uv, color))
                xx += size
            yy += size
        return True

    # -- выбор спрайта кнопки/слайдера ----------------------------------

    @staticmethod
    def button_sprite(active: bool, hover: bool) -> str:
        """Спрайт кнопки (ui.rs::button): disabled / highlighted / обычный."""
        if not active:
            return "gui/sprites/widget/button_disabled"
        if hover:
            return "gui/sprites/widget/button_highlighted"
        return "gui/sprites/widget/button"

    @staticmethod
    def checkbox_sprite(value: bool, hover: bool) -> str:
        if value:
            return (
                "gui/sprites/widget/checkbox_selected_highlighted"
                if hover
                else "gui/sprites/widget/checkbox_selected"
            )
        return (
            "gui/sprites/widget/checkbox_highlighted"
            if hover
            else "gui/sprites/widget/checkbox"
        )


@functools.lru_cache(maxsize=4)
def _load_cached(root: str) -> Optional[GuiAtlas]:
    """Загрузка атласа с кэшем (PNG-упаковка недёшева, root не меняется)."""
    try:
        return GuiAtlas.load(root)
    except Exception as exc:  # noqa: BLE001 - меню не должно падать из-за PNG
        print(f"[QuadRix] gui atlas не загружен: {exc}")
        return None


def load_gui_atlas(root: Path | str = PACK_ROOT) -> Optional[GuiAtlas]:
    """Загрузить атлас; ``None`` при любой ошибке (рисуем цветом)."""
    return _load_cached(str(root))


__all__ = [
    "GUI_TEXTURE",
    "GuiAtlas",
    "LOGICAL",
    "PACK_ROOT",
    "SPRITES",
    "Sprite",
    "TEXTURES",
    "load_gui_atlas",
    "rgba",
]
