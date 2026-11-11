#!/usr/bin/env python3
"""Тесты CLI-разбора ``quadrix.py``: GUI по умолчанию, --headless, --daemon.

GUI стал режимом по умолчанию, поэтому важно закрепить контракт:

* без флагов → GUI (``headless=False``);
* ``--headless`` / ``--no-gui`` → headless;
* ``--gui`` → явный GUI;
* ``--daemon`` подразумевает headless (окно и control-сервер несовместимы);
* ``--gui --daemon`` → побеждает daemon (headless).

Модуль ``quadrix.py`` загружается по пути, потому что пакет ``quadrix/``
перекрывал бы имя при обычном ``import``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

#: Корень репозитория: tests/integration/test_cli.py -> ../..
ROOT = Path(__file__).resolve().parents[2]


def _load_entry() -> ModuleType:
    """Загрузить ``quadrix.py`` по пути (не как пакет ``quadrix``)."""
    spec = importlib.util.spec_from_file_location(
        "quadrix_entry_cli", ROOT / "quadrix.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("не удалось загрузить quadrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Entry point: parse_args, build_parser, GuiUnavailable, run_gui.
entry = _load_entry()


def test_gui_is_default() -> None:
    """Без флагов режим — GUI: headless=False и gui=False (не задан явно)."""
    args = entry.parse_args([])
    assert args.headless is False
    assert args.gui is False


def test_headless_flag() -> None:
    """--headless включает headless-режим."""
    args = entry.parse_args(["--headless"])
    assert args.headless is True


def test_gui_flag_explicit() -> None:
    """--gui — явный GUI, headless остаётся выключенным."""
    args = entry.parse_args(["--gui"])
    assert args.headless is False
    assert args.gui is True


def test_no_gui_is_alias_for_headless() -> None:
    """--no-gui — старый alias, тоже ведёт в headless."""
    args = entry.parse_args(["--no-gui"])
    assert args.headless is True


def test_daemon_implies_headless() -> None:
    """--daemon несовместим с окном: он подразумевает headless."""
    args = entry.parse_args(["--daemon"])
    assert args.headless is True


def test_gui_with_daemon_prefers_daemon() -> None:
    """--gui --daemon: daemon выигрывает, режим становится headless."""
    args = entry.parse_args(["--gui", "--daemon"])
    assert args.headless is True
    assert args.gui is False


def test_gui_unavailable_is_runtime_error() -> None:
    """GuiUnavailable наследует RuntimeError — main ловит его для fallback."""
    assert issubclass(entry.GuiUnavailable, RuntimeError)
