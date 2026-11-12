#!/usr/bin/env python3
"""[QuadRix] Чат: список сообщений и экран ввода (Gameplay PART 4).

Порт ``horizon/crates/horizon-client-render/src/chat.rs``:

    * ``Chat`` (список сообщений: 100 строк, затухание 200 тиков,
      прокрутка) и ``time_alpha``;
    * ``ChatScreen`` (поле ввода у нижнего края ``4, h-12, w-4, 12``,
      фокус, 256 символов, Escape/Enter/Up/Down);
    * ``normalize_chat_message`` (trim → схлопывание пробелов →
      обрезка до 256 UTF-16 единиц).

Здесь портирована логика **без обёртки по ширине** (font.wrap_components):
одно сообщение — одна строка. FALLBACK: перенос длинных сообщений и
подсветка команд (CommandSuggestions) — следующая сессия.

Список держит :class:`ChatLog` (его читает ``GameScreen``), а экран ввода —
:class:`ChatScreen`. Ввод отправляется через ``GameScreen.submit_chat``
(``play.Chat``); см. ``quadrix/render/app.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from quadrix.render.menu import Screen, TextInput, draw_text
from quadrix.render.ui import rgba

__all__ = [
    "MAX_CHAT_LINES",
    "CHAT_FADE_TICKS",
    "ChatLine",
    "ChatLog",
    "ChatScreen",
    "normalize_chat_message",
    "time_alpha",
]

#: ``ChatComponent`` хранит 100 строк (``lines.truncate(100)``).
MAX_CHAT_LINES: int = 100
#: Полное затухание строки (``200.0`` в ``time_alpha``).
CHAT_FADE_TICKS: float = 200.0
#: Максимум символов поля ввода (``input.max_length = 256``).
CHAT_MAX_LENGTH: int = 256
#: Максимум сообщений истории (``recent.len() >= 100``).
MAX_RECENT: int = 100

#: Высота строки чата (``ChatOptions::line_height`` = ``9 * (spacing + 1)``).
CHAT_LINE_HEIGHT: float = 9.0

#: Цвет строки чата (белый; прозрачность — из ``time_alpha``).
CHAT_TEXT_COLOR = rgba(255, 255, 255, 255)
#: Цвет фона поля ввода.
CHAT_INPUT_BACKGROUND = rgba(0, 0, 0, 170)
#: Цвет фона открытого чата (``background_opacity`` 0.5).
CHAT_BACKGROUND = rgba(0, 0, 0, 127)


def _log(message: str) -> None:
    """Единый лог QuadRix (префикс обязателен)."""
    print("[QuadRix] chat: " + message)


# ---------------------------------------------------------------------------
# time_alpha (chat.rs::time_alpha)
# ---------------------------------------------------------------------------

def time_alpha(ticks: float, added: float) -> float:
    """``ChatComponent.AlphaCalculator.timeBased``.

    Непрозрачно 180 тиков, затем квадратичное затухание за 20:
    ``t = (1 - (ticks - added) / 200) * 10``, обрезается в ``[0, 1]``,
    возвращается ``t * t``.
    """
    t = 1.0 - (float(ticks) - float(added)) / CHAT_FADE_TICKS
    t = min(1.0, max(0.0, t * 10.0))
    return t * t


# ---------------------------------------------------------------------------
# normalize_chat_message (chat.rs::normalize_chat_message)
# ---------------------------------------------------------------------------

_JAVA_WHITESPACE_EXTRA = frozenset(
    "\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f"
)
#: Пробелы, которые Java НЕ считает whitespace (неразрывные).
_JAVA_NON_WHITESPACE = frozenset("\u00a0\u2007\u202f")


def _java_whitespace(ch: str) -> bool:
    """``Character.isWhitespace`` (приближённо, как ``ui.rs::java_whitespace``)."""
    if ch in _JAVA_WHITESPACE_EXTRA:
        return True
    if ch in _JAVA_NON_WHITESPACE:
        return False
    return ch.isspace()


def _normalize_space(text: str) -> str:
    """``StringUtils.normalizeSpace``: один пробел на серию whitespace."""
    out: list[str] = []
    space = False
    for ch in text:
        if _java_whitespace(ch):
            space = bool(out)
        else:
            if space:
                out.append(" ")
                space = False
            out.append(ch)
    return "".join(out)


def _truncate_utf16(text: str, max_units: int) -> str:
    """``StringUtil.truncateStringIfNecessary(s, 256, false)``.

    Java считает UTF-16-единицы (``String.length``); режем на границе
    символа, чтобы не оставить половину суррогатной пары.
    """
    units = 0
    for index, ch in enumerate(text):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > max_units:
            return text[:index]
    return text


def normalize_chat_message(message: str) -> str:
    """``ChatScreen.normalizeChatMessage``.

    Сначала ``String.trim`` (код-поинты ``<= U+0020``), затем схлопывание
    пробелов, затем обрезка до 256 UTF-16-единиц (ровно столько вмещает
    ``ServerboundChatPacket``). Именно это уходит на сервер, а не то, что
    набрано.
    """
    trimmed = message.strip("".join(chr(c) for c in range(0x21)))
    return _truncate_utf16(_normalize_space(trimmed), CHAT_MAX_LENGTH)


# ---------------------------------------------------------------------------
# ChatLog (chat.rs::Chat)
# ---------------------------------------------------------------------------

@dataclass
class ChatLine:
    """Одна строка чата: текст и тик добавления (для затухания)."""

    text: str
    added: int = 0


class ChatLog:
    """Список сообщений чата (``Chat`` + ``ChatComponent``).

    Хранит до :data:`MAX_CHAT_LINES` строк (новейшая первая) и историю
    отправленного (:attr:`recent`, до :data:`MAX_RECENT`).
    """

    def __init__(self) -> None:
        self.lines: list[ChatLine] = []
        self.recent: list[str] = []

    # -- сообщения -------------------------------------------------------

    def add(self, text: str, ticks: int) -> ChatLine:
        """Добавить строку (``ChatComponent.addMessage``): наперед, до 100."""
        line = ChatLine(str(text), int(ticks))
        self.lines.insert(0, line)
        del self.lines[MAX_CHAT_LINES:]
        return line

    def add_recent(self, message: str) -> None:
        """``ChatComponent.addRecentChat``: история без повторов подряд, до 100."""
        if not self.recent or self.recent[-1] != message:
            self.recent.append(message)
            if len(self.recent) > MAX_RECENT:
                del self.recent[0]

    def clear(self) -> None:
        """Очистить строки (прокрутка/смена мира)."""
        self.lines = []

    # -- затухание / окно ------------------------------------------------

    def visible(
        self,
        ticks: int,
        focused: bool,
        max_lines: int = 10,
    ) -> list[tuple[ChatLine, float]]:
        """Видимые строки: ``[(строка, alpha), ...]``, новейшая первая.

        В фокусе alpha = 1.0 для всех (Rust ``Chat::layout``); вне фокуса —
        :func:`time_alpha`, и строки с alpha ≈ 0 отбрасываются.
        """
        out: list[tuple[ChatLine, float]] = []
        for line in self.lines[: max(0, int(max_lines))]:
            alpha = 1.0 if focused else time_alpha(ticks, line.added)
            if alpha > 1.0e-5:
                out.append((line, alpha))
        return out


# ---------------------------------------------------------------------------
# ChatScreen (chat.rs::ChatScreen)
# ---------------------------------------------------------------------------

class ChatScreen(Screen):
    """Экран ввода чата (порт ``ChatScreen``).

    Поле ввода ``4, h-12, w-4, 12`` (как ``TextField::new``), фокус и 256
    символов. Клавиши: Escape — закрыть, Enter — отправить нормализованное,
    Up/Down — история (``recent``), Backspace/Delete/Left/Right — поле.
    """

    #: Высота поля ввода (``h`` в ``TextField::new``).
    INPUT_HEIGHT: float = 12.0

    def __init__(
        self,
        initial: str = "",
        chat: Optional[ChatLog] = None,
        width: float = 854.0,
        height: float = 480.0,
        on_submit: Optional[Any] = None,
        on_close: Optional[Any] = None,
    ) -> None:
        super().__init__(width, height)
        self.chat = chat if chat is not None else ChatLog()
        self.input = TextInput(
            x=4.0,
            y=float(height) - self.INPUT_HEIGHT,
            w=float(width) - 4.0,
            h=self.INPUT_HEIGHT,
            max_length=CHAT_MAX_LENGTH,
            focused=True,
        )
        # Начальное значение (Rust ``input.set_value(m, initial)``).
        self.input.value = str(initial)[:CHAT_MAX_LENGTH]
        self.input.cursor = len(self.input.value)
        self.on_submit = on_submit
        self.on_close = on_close
        #: Позиция в истории (``history_pos`` начинается с ``recent.len()``).
        self.history_pos: int = len(self.chat.recent)
        #: Буфер введённого до ухода в историю (``history_buffer``).
        self.history_buffer: str = ""

    # -- значение --------------------------------------------------------

    def value(self) -> str:
        """Текущий текст поля (``ChatScreen.value``)."""
        return self.input.value

    def normalized(self) -> str:
        """Нормализованное сообщение (``ChatScreen.normalized``)."""
        return normalize_chat_message(self.input.value)

    # -- ввод ------------------------------------------------------------

    def move_in_history(self, direction: int) -> bool:
        """``ChatScreen.moveInHistory``: Up (-1) / Down (+1) по ``recent``."""
        maximum = len(self.chat.recent)
        new = min(max(0, self.history_pos + int(direction)), maximum)
        if new == self.history_pos:
            return False
        if new == maximum:
            # Вернулись к тому, что было набрано до входа в историю.
            self.history_pos = maximum
            self.input.value = self.history_buffer
        else:
            if self.history_pos == maximum:
                self.history_buffer = self.input.value
            self.input.value = self.chat.recent[new]
            self.history_pos = new
        self.input.cursor = len(self.input.value)
        return True

    def submit(self) -> None:
        """Отправить сообщение и закрыть экран (``ChatAction::Submit``)."""
        message = self.normalized()
        if self.on_submit is not None:
            self.on_submit(message)
        self.close()

    def close(self) -> None:
        """Закрыть экран (``ChatAction::Close`` → ``close_chat``)."""
        if self.on_close is not None:
            self.on_close()

    def handle_key(self, key: str, ch: Optional[str] = None) -> bool:
        """``ChatScreen.keyPressed``: Escape/Enter/Up/Down, иначе поле."""
        if key == "escape":
            self.close()
            return True
        if key in ("enter", "numpadenter", "return"):
            self.submit()
            return True
        if key == "up":
            return self.move_in_history(-1)
        if key == "down":
            return self.move_in_history(1)
        if self.input.handle_key(key):
            return True
        if ch:
            inserted = False
            for single in ch:
                if self.input.handle_char(single):
                    inserted = True
            return inserted
        return False

    def handle_click(self, mx: float, my: float) -> bool:
        """Клик по полю ввода (``ChatScreen.mouseClicked``)."""
        return bool(self.input.handle_click(mx, my))

    # -- отрисовка -------------------------------------------------------

    def render(self, batch: Any, font: Optional[Any] = None) -> None:
        """Поле ввода чата у нижнего края (фон + текст + каретка)."""
        # Затемняем область поля, затем рисуем TextInput.
        self.input.render(batch, font)
        if font is not None:
            # Подсказка-метка (без неё пустой чат неотличим от игры).
            from quadrix.core import lang

            hint = lang.get_or("chat.editBox", "Type a message...")
            if not self.input.value:
                draw_text(
                    batch, font, hint,
                    self.input.x + 4.0, self.input.y + 2.0,
                    rgba(160, 160, 160, 160),
                )


def chat_lines_per_page(focused: bool) -> int:
    """``Chat::lines_per_page``: строк в окне (Rust ``height_px``/``line_height``).

    Вне фокуса ``height_px = 70/160*160 + 20 = 90`` → 10 строк; в фокусе
    ``160 + 20 = 180`` → 20 строк.
    """
    height_px = (160.0 + 20.0) if focused else (70.0 / 160.0 * 160.0 + 20.0)
    return int(height_px / CHAT_LINE_HEIGHT)


__all__ += ["chat_lines_per_page"]
