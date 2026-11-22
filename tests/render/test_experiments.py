#!/usr/bin/env python3
"""[QuadRix] Тесты Experiments + ConfirmExperimentalFeatures (WC6).

Порт ``horizon/crates/horizon-client/src/title/experiments.rs`` и
``title/confirm_experiments.rs``: ``feature_packs`` (PART ``datapack.rs``) на
реальном ``.local`` (3 пака), ``repository_flags``/``confirm_entries``,
геометрия и рендер обоих экранов, плюс связка CreateWorldScreen id 30 и
``offer_data_packs`` (title.rs).

FALLBACK'и (bold-стиль DetailsScreen, world-паки ``file/``, экран Data Packs)
описаны в ``quadrix/render/experiments.py`` и ``PORTING_STATE.yaml``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from quadrix.core import lang
from quadrix.render import create_world as cw
from quadrix.render.experiments import (
    BUTTON,
    BUTTON_CONFIRM,
    COLUMN_SPACING,
    DETAILS,
    FLAG_HEIGHT,
    FOOTER,
    GRID,
    HEADER,
    ROW,
    WARNING,
    ConfirmClick,
    ConfirmExperimentsScreen,
    ExperimentsScreen,
    Flag,
    Outcome,
    block_top,
    confirm_click,
    confirm_entries,
    content_top,
    details_rect,
    experiments_click,
    feature_packs,
    footer,
    footer_pair,
    footer_single,
    grid_left,
    grid_top,
    message_lines,
    repository_flags,
    switch_rect,
    warning_lines,
)
from quadrix.render.menu import Screen, ScreenStack, load_language
from quadrix.render.ui import Batch, Font
from quadrix.render.world_screens import CreateWorldScreen

ROOT = Path(".local/horizon-client/26.3")
PACK_IDS = ["minecart_improvements", "redstone_experiments", "trade_rebalance"]


@pytest.fixture(scope="module")
def font() -> Font:
    return Font.load()


@pytest.fixture()
def english():
    previous = lang.current()
    lang.set(load_language("en_us"))
    yield
    if previous is not None:
        lang.set(previous)


# ---------------------------------------------------------------------------
# feature_packs (datapack.rs::feature_packs)
# ---------------------------------------------------------------------------

def test_feature_packs_real_sorted() -> None:
    packs = feature_packs(ROOT)
    assert [p.id for p in packs] == PACK_IDS  # sorted by id
    for pack in packs:
        assert pack.path.joinpath("pack.mcmeta").exists()


def test_feature_packs_missing_root_is_empty() -> None:
    assert feature_packs(Path("missing-root")) == []


def test_datapack_features_reads_enabled() -> None:
    packs = {p.id: p for p in feature_packs(ROOT)}
    assert packs["redstone_experiments"].features() == ["minecraft:redstone_experiments"]
    assert packs["trade_rebalance"].features() == ["minecraft:trade_rebalance"]


# ---------------------------------------------------------------------------
# repository_flags / constants
# ---------------------------------------------------------------------------

def test_repository_flags_titles_and_enabled(english) -> None:
    flags = repository_flags(ROOT, ["redstone_experiments"])
    assert [f.id for f in flags] == PACK_IDS
    by_id = {f.id: f for f in flags}
    assert by_id["minecart_improvements"].title == "Minecart Improvements"
    assert by_id["redstone_experiments"].title == "Redstone Experiments"
    assert by_id["trade_rebalance"].description == "Updated trades for Villagers"
    assert by_id["redstone_experiments"].enabled is True
    assert by_id["minecart_improvements"].enabled is False


def test_layout_constants() -> None:
    assert (HEADER, FOOTER) == (33.0, 33.0)
    assert (GRID, BUTTON) == (299.0, 44.0)
    assert WARNING == 310.0
    assert FLAG_HEIGHT == 20.0 + 4.0 + 18.0
    assert content_top() == 63.0
    assert grid_left(854.0) == math.trunc((854.0 - 299.0) / 2.0)


def test_footer_two_buttons() -> None:
    (x, y), (x2, y2) = footer(854.0, 480.0)
    assert x == math.trunc((854.0 - 308.0) / 2.0)
    assert y == 480.0 - FOOTER + 6.0
    assert x2 == x + 158.0 and y2 == y


def test_warning_and_grid_geometry(english, font: Font) -> None:
    lines = warning_lines(font)
    assert len(lines) >= 2  # реальный en_us: предупреждение переносится
    assert all(font.width(line) <= WARNING for line in lines)
    assert grid_top(font) == content_top() + 9.0 * len(lines) + 15.0
    # i-й switch смещён на FLAG_HEIGHT, кнопка 44 справа от сетки.
    x0, y0 = switch_rect(font, 854.0, 0)
    x1, y1 = switch_rect(font, 854.0, 1)
    assert x1 == x0 and y1 == y0 + FLAG_HEIGHT
    assert x0 == grid_left(854.0) + GRID - BUTTON


# ---------------------------------------------------------------------------
# experiments_click
# ---------------------------------------------------------------------------

def test_experiments_click_targets(english, font: Font) -> None:
    flags = repository_flags(ROOT, [])
    size = (854.0, 480.0)
    bx, by = switch_rect(font, 854.0, 0)
    assert experiments_click(flags, font, (bx + 1.0, by + 1.0), size) == ("switch", 0)
    (dx, dy), (cx, cy) = footer(*size)
    assert experiments_click(flags, font, (dx + 1.0, dy + 1.0), size) == (
        "outcome", Outcome.DONE,
    )
    assert experiments_click(flags, font, (cx + 1.0, cy + 1.0), size) == (
        "outcome", Outcome.CANCEL,
    )
    assert experiments_click(flags, font, (1.0, 1.0), size) is None


# ---------------------------------------------------------------------------
# ExperimentsScreen
# ---------------------------------------------------------------------------

def test_experiments_screen_loads_real_packs(english) -> None:
    screen = ExperimentsScreen(resources=ROOT, enabled=["trade_rebalance"])
    assert [f.id for f in screen.flags] == PACK_IDS
    assert screen.selected_ids() == ["trade_rebalance"]


def test_experiments_screen_toggle_and_done(english) -> None:
    captured: list[list[Flag]] = []
    screen = ExperimentsScreen(resources=ROOT, on_done=captured.append)
    bx, by = switch_rect(screen._font(), screen.width, 2)
    assert screen.handle_click(bx + 1.0, by + 1.0) is True
    assert screen.flags[2].enabled is True
    # Done в футере.
    (dx, dy), (cx, cy) = footer(screen.width, screen.height)
    assert screen.handle_click(dx + 1.0, dy + 1.0) is True
    assert len(captured) == 1 and captured[0][2].enabled is True


def test_experiments_screen_cancel_via_escape(english) -> None:
    called: list[int] = []
    screen = ExperimentsScreen(resources=ROOT, on_cancel=lambda: called.append(1))
    assert screen.handle_key("escape") is True
    assert called == [1]


def test_experiments_screen_render_adds_quads(english, font: Font) -> None:
    screen = ExperimentsScreen(resources=ROOT)
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads


# ---------------------------------------------------------------------------
# confirm_entries / геометрия
# ---------------------------------------------------------------------------

def test_confirm_entries_filter(english) -> None:
    entries = confirm_entries(ROOT, ["vanilla", "redstone_experiments"])
    assert [e.title for e in entries] == ["Redstone Experiments"]
    assert entries[0].flags == "redstone_experiments"  # namespace отброшен
    # не выбранный пак не попадает.
    assert confirm_entries(ROOT, ["vanilla"]) == []


def test_confirm_message_and_geometry(english, font: Font) -> None:
    lines = message_lines(font)
    assert len(lines) >= 1
    assert block_top(len(lines), 480.0) == max((480.0 - (9.0 + len(lines) * 9.0 + ROW + ROW)) / 2.0, 0.0)
    dx, dy = details_rect(len(lines), 854.0, 480.0)
    assert dx == math.trunc((854.0 - DETAILS) / 2.0)
    assert dy == block_top(len(lines), 480.0) + 9.0 + ROW
    (px, py), (bx, by) = footer_pair(854.0, 480.0)
    assert by == py == 480.0 - 45.0
    assert bx == px + BUTTON_CONFIRM + COLUMN_SPACING
    assert footer_single(854.0, 480.0) == [(math.trunc((854.0 - BUTTON_CONFIRM) / 2.0), 480.0 - 45.0)]


def test_confirm_click_targets(english, font: Font) -> None:
    entries = confirm_entries(ROOT, ["redstone_experiments"])
    size = (854.0, 480.0)
    dx, dy = details_rect(len(message_lines(font)), *size)
    assert confirm_click(entries, False, font, (dx + 1.0, dy + 1.0), size) is ConfirmClick.DETAILS
    (px, py), (bx, by) = footer_pair(*size)
    assert confirm_click(entries, False, font, (px + 1.0, py + 1.0), size) is ConfirmClick.PROCEED
    assert confirm_click(entries, False, font, (bx + 1.0, by + 1.0), size) is ConfirmClick.BACK
    # в Details — только Back.
    sx, sy = footer_single(*size)[0]
    assert confirm_click(entries, True, font, (sx + 1.0, sy + 1.0), size) is ConfirmClick.BACK
    assert confirm_click(entries, True, font, (1.0, 1.0), size) is None


# ---------------------------------------------------------------------------
# ConfirmExperimentsScreen
# ---------------------------------------------------------------------------

def test_confirm_screen_new_from_selection(english) -> None:
    screen = ConfirmExperimentsScreen(resources=ROOT, selected=["vanilla", "trade_rebalance"])
    assert [e.title for e in screen.entries] == ["Villager Trade Rebalance"]
    assert screen.pending == ["vanilla", "trade_rebalance"]
    assert screen.details is False


def test_confirm_screen_details_then_back(english) -> None:
    screen = ConfirmExperimentsScreen(resources=ROOT, selected=["redstone_experiments"])
    size = (screen.width, screen.height)
    dx, dy = details_rect(len(message_lines(screen._font())), *size)
    assert screen.handle_click(dx + 1.0, dy + 1.0) is True
    assert screen.details is True
    # Back в Details возвращает к предупреждению, экран не закрывается.
    sx, sy = footer_single(*size)[0]
    assert screen.handle_click(sx + 1.0, sy + 1.0) is True
    assert screen.details is False


def test_confirm_screen_proceed_calls_callback(english) -> None:
    applied: list[list[str]] = []
    screen = ConfirmExperimentsScreen(
        resources=ROOT, selected=["redstone_experiments"],
        on_proceed=applied.append,
    )
    (px, py), _ = footer_pair(screen.width, screen.height)
    assert screen.handle_click(px + 1.0, py + 1.0) is True
    assert applied == [["redstone_experiments"]]


def test_confirm_screen_back_calls_on_back(english) -> None:
    called: list[int] = []
    screen = ConfirmExperimentsScreen(
        resources=ROOT, selected=["redstone_experiments"], on_back=lambda: called.append(1),
    )
    assert screen.handle_key("escape") is True
    assert called == [1]


def test_confirm_screen_render_both_pages(english, font: Font) -> None:
    screen = ConfirmExperimentsScreen(resources=ROOT, selected=["redstone_experiments"])
    batch = Batch()
    screen.render(batch, font)
    assert batch.quads
    screen.details = True
    batch.clear()
    screen.render(batch, font)
    assert batch.quads


# ---------------------------------------------------------------------------
# связка с CreateWorldScreen (title.rs)
# ---------------------------------------------------------------------------

def _create_world_screen() -> tuple[CreateWorldScreen, ScreenStack]:
    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=2))
    stack = ScreenStack(screen)
    screen.stack = stack
    return screen, stack


def test_create_world_experiments_opens_screen(english) -> None:
    screen, stack = _create_world_screen()
    screen._on_button(30)
    assert isinstance(stack.current, ExperimentsScreen)
    assert stack.depth() == 2


def test_create_world_experiments_done_merges_data_packs(english) -> None:
    screen, stack = _create_world_screen()
    screen.options.data_packs = ["vanilla"]
    screen._on_button(30)
    exp = stack.current
    assert isinstance(exp, ExperimentsScreen)
    # включить minecart_improvements (0) и trade_rebalance (2)
    font = exp._font()
    for i in (0, 2):
        bx, by = switch_rect(font, exp.width, i)
        exp.handle_click(bx + 1.0, by + 1.0)
    (dx, dy), _ = footer(exp.width, exp.height)
    exp.handle_click(dx + 1.0, dy + 1.0)
    assert stack.depth() == 1
    # включённые дописываются в обратном порядке экрана.
    assert screen.options.data_packs == [
        "vanilla", "trade_rebalance", "minecart_improvements",
    ]


def test_create_world_experiments_cancel_keeps_selection(english) -> None:
    screen, stack = _create_world_screen()
    screen.options.data_packs = ["vanilla", "redstone_experiments"]
    screen._on_button(30)
    exp = stack.current
    assert isinstance(exp, ExperimentsScreen)
    # выключить redstone_experiments, но нажать Cancel (Escape).
    bx, by = switch_rect(exp._font(), exp.width, 1)
    exp.handle_click(bx + 1.0, by + 1.0)
    assert exp.handle_key("escape") is True
    assert stack.depth() == 1
    assert screen.options.data_packs == ["vanilla", "redstone_experiments"]


def test_create_world_experiments_without_stack_is_safe(capsys) -> None:
    screen = CreateWorldScreen(854.0, 480.0, options=cw.WorldOptions(tab=2))
    screen._on_button(30)
    assert "[QuadRix]" in capsys.readouterr().out


def test_create_world_offer_data_packs_without_feature_applies(english) -> None:
    screen, stack = _create_world_screen()
    screen.offer_data_packs(["vanilla", "file/t.zip"])
    assert stack.depth() == 1
    assert screen.options.data_packs == ["vanilla", "file/t.zip"]


def test_create_world_offer_data_packs_with_feature_asks(english) -> None:
    screen, stack = _create_world_screen()
    screen.offer_data_packs(["vanilla", "redstone_experiments"])
    assert isinstance(stack.current, ConfirmExperimentsScreen)
    assert stack.depth() == 2
    # выбор ещё не применён — ждёт Proceed.
    assert screen.options.data_packs == ["vanilla"]
    confirm = stack.current
    (px, py), _ = footer_pair(confirm.width, confirm.height)
    confirm.handle_click(px + 1.0, py + 1.0)
    assert stack.depth() == 1
    assert screen.options.data_packs == ["vanilla", "redstone_experiments"]
