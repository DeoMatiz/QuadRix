"""Тесты спрайтового атласа GUI QuadRix (порт Horizon ``ui.rs`` / ``hud.rs``).

Грузим реальные PNG из ``.local`` (layout FIXED) и проверяем упаковку,
nine-slice, половинный растяг кнопок главного меню (``title.rs``),
плитку фона (``ui.rs::tiled_sized``) и выбор спрайтов кнопки/флажка.
"""

from __future__ import annotations

import functools

import numpy as np
import pytest

from quadrix.render.gui_atlas import (
    GUI_TEXTURE,
    SPRITES,
    GuiAtlas,
    load_gui_atlas,
)
from quadrix.render.ui import Batch


@functools.lru_cache(maxsize=1)
def _atlas() -> GuiAtlas:
    """Атлас из ``.local`` (упаковка PNG недёшева — грузим один раз)."""
    atlas = load_gui_atlas()
    assert atlas is not None
    return atlas


# ---------------------------------------------------------------------------
# загрузка / метаданные
# ---------------------------------------------------------------------------

def test_load_real_atlas_has_every_sprite() -> None:
    atlas = _atlas()
    assert set(atlas.sprites) == set(SPRITES)
    assert len(atlas.sprites) == 20
    assert atlas.width > 0 and atlas.height > 0
    assert atlas.image.shape[2] == 4


def test_title_sprites_reuse_mcmeta_logical_size() -> None:
    atlas = _atlas()
    mc = atlas.sprites["gui/title/minecraft"]
    assert (mc.tex_w, mc.tex_h) == (1024, 256)
    assert (mc.logical_w, mc.logical_h) == (256, 64)  # draw_logo рисует 256x44 из 256x64
    ed = atlas.sprites["gui/title/edition"]
    assert (ed.tex_w, ed.tex_h) == (512, 64)
    assert (ed.logical_w, ed.logical_h) == (128, 16)


def test_button_and_slider_borders_from_mcmeta() -> None:
    atlas = _atlas()
    assert atlas.sprites["gui/sprites/widget/button"].border == (3, 3, 3, 3)
    assert atlas.sprites["gui/sprites/widget/slider"].border == (1, 1, 1, 1)
    # slider_handle: l/t/r/b = 2,2,2,3 (``.png.mcmeta``).
    assert atlas.sprites["gui/sprites/widget/slider_handle"].border == (2, 2, 2, 3)
    # menu_background без метаданных → border None (растягивается целиком).
    assert atlas.sprites["gui/menu_background"].border is None


# ---------------------------------------------------------------------------
# nine-slice (ui.rs::nine_slice)
# ---------------------------------------------------------------------------

def test_nine_slice_exact_size_is_one_quad() -> None:
    atlas = _atlas()
    batch = Batch()
    assert atlas.nine_slice(
        batch, "gui/sprites/widget/button", 5.0, 6.0, 200.0, 20.0
    ) is True
    # w == logical_w и h == logical_h → один квад (ветка ``part`` целого).
    assert len(batch.quads) == 1
    q = batch.quads[0]
    assert (q.x, q.y, q.w, q.h) == (5.0, 6.0, 200.0, 20.0)
    assert q.texture == GUI_TEXTURE


def test_nine_slice_stretched_splits_corners_and_edges() -> None:
    atlas = _atlas()
    batch = Batch()
    assert atlas.nine_slice(
        batch, "gui/sprites/widget/button", 0.0, 0.0, 400.0, 100.0
    ) is True
    # 4 угла + 4 края (у меню 200x20 нет тайлинга при border 3) + центр.
    assert len(batch.quads) >= 9
    assert all(q.texture == GUI_TEXTURE for q in batch.quads)
    # Углы по 3x3 в левом верхнем/правом нижнем углах.
    quad = lambda x, y, w, h: any(
        (q.x, q.y, q.w, q.h) == (x, y, w, h) for q in batch.quads
    )
    assert quad(0.0, 0.0, 3.0, 3.0)
    assert quad(397.0, 97.0, 3.0, 3.0)


def test_nine_slice_missing_sprite_returns_false() -> None:
    atlas = _atlas()
    assert atlas.nine_slice(Batch(), "gui/does_not_exist", 0, 0, 10, 10) is False


# ---------------------------------------------------------------------------
# title-кнопки (title.rs: половинный растяг)
# ---------------------------------------------------------------------------

def test_title_button_draws_two_halves() -> None:
    atlas = _atlas()
    batch = Batch()
    assert atlas.title_button(
        batch, "gui/sprites/widget/button", 10.0, 20.0, 200.0, 20.0
    ) is True
    assert len(batch.quads) == 2
    left, right = batch.quads
    assert (left.x, left.w) == (10.0, 100.0)
    assert (right.x, right.w) == (110.0, 100.0)
    # Левая половина — левые UV, правая — правые (u0 растёт).
    assert left.u1 <= right.u0 or left.u0 < right.u0
    assert left.u0 < right.u0


# ---------------------------------------------------------------------------
# tiled / region / blit (hud.rs + ui.rs::tiled_sized)
# ---------------------------------------------------------------------------

def test_tiled_repeats_whole_sprite_per_size() -> None:
    atlas = _atlas()
    batch = Batch()
    # menu_background 16x16, плитка 32 GUI-пикселя.
    assert atlas.tiled(
        batch, "gui/menu_background", 0.0, 0.0, 64.0, 32.0, 32.0
    ) is True
    assert len(batch.quads) == 2  # 64/32 = 2 колонки, 32/32 = 1 строка
    for q in batch.quads:
        assert (q.w, q.h) == (32.0, 32.0)


def test_region_uses_logical_dimensions() -> None:
    atlas = _atlas()
    s = atlas.sprites["gui/title/minecraft"]
    batch = Batch()
    assert atlas.region(
        batch, "gui/title/minecraft", 0.0, 0.0, 256.0, 44.0, 256.0, 64.0
    ) is True
    assert len(batch.quads) == 1
    q = batch.quads[0]
    # Логическая ширина 256 → весь UV по ширине; высота 44 из 64.
    assert q.u0 == pytest.approx(s.u0)
    assert q.u1 == pytest.approx(s.u1)
    full_v = s.v1 - s.v0
    assert (q.v1 - q.v0) == pytest.approx(full_v * 44.0 / 64.0)


def test_blit_stretches_whole_sprite() -> None:
    atlas = _atlas()
    s = atlas.sprites["gui/sprites/friends/friends"]
    batch = Batch()
    assert atlas.blit(batch, "gui/sprites/friends/friends", 1.0, 2.0, 15.0, 15.0)
    q = batch.quads[0]
    assert (q.x, q.y, q.w, q.h) == (1.0, 2.0, 15.0, 15.0)
    assert (q.u0, q.v0, q.u1, q.v1) == (s.u0, s.v0, s.u1, s.v1)


# ---------------------------------------------------------------------------
# выбор спрайта
# ---------------------------------------------------------------------------

def test_button_and_checkbox_sprite_selection() -> None:
    assert GuiAtlas.button_sprite(True, True) == "gui/sprites/widget/button_highlighted"
    assert GuiAtlas.button_sprite(True, False) == "gui/sprites/widget/button"
    assert GuiAtlas.button_sprite(False, False) == "gui/sprites/widget/button_disabled"
    assert GuiAtlas.checkbox_sprite(False, False) == "gui/sprites/widget/checkbox"
    assert (
        GuiAtlas.checkbox_sprite(True, True)
        == "gui/sprites/widget/checkbox_selected_highlighted"
    )
