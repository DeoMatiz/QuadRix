#!/usr/bin/env python3
"""[QuadRix] Тесты Gameplay PART 4: чат (открытие, ввод, история, отправка).

Проверяем ``quadrix/render/chat_screen.py`` (``ChatLog`` + ``ChatScreen``,
порт ``chat.rs``) и его связку с ``GameScreen`` (``app.py``): T открывает
чат, ``play.Chat`` уходит серверу, Up/Down листают историю, пришедший
SystemChat попадает в оверлей.

``FakeClient`` подменяет ``Client``: сеть не нужна, тесты идут в CI.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path
from types import ModuleType

from quadrix.core.geometry import Vec3
from quadrix.motion.core import MovementResources, PlayerMotion
from quadrix.render.app import GameScreen
from quadrix.render.chat_screen import (
    ChatLog,
    ChatScreen,
    chat_lines_per_page,
    normalize_chat_message,
    time_alpha,
)
from quadrix.render.game_world import FlatWorld
from quadrix.render.menu import ScreenStack
from quadrix.world.nbt import Tag, TagType

ROOT = Path(__file__).resolve().parents[2]


def _load_entry() -> ModuleType:
    """Загрузить ``quadrix.py`` по пути (как тесты интеграции)."""
    spec = importlib.util.spec_from_file_location(
        "quadrix_entry_chat", ROOT / "quadrix.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("не удалось загрузить quadrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = _load_entry()


# ---------------------------------------------------------------------------
# фейковый клиент (сеть не нужна)
# ---------------------------------------------------------------------------

class FakeWorld:
    """Мир сервера: чанки (интерфейс ``ClientWorld``)."""

    def __init__(self) -> None:
        self.chunks: dict = {}

    def get_block(self, pos) -> str:
        return "minecraft:air"


class FakeClient:
    """Мини-``Client``: движение + запись отправленных пакетов + чат."""

    def __init__(self) -> None:
        self.world = FakeWorld()
        self.motion = PlayerMotion.new(
            MovementResources(properties={}), Vec3(0.0, 64.0, 0.0)
        )
        self.pending_input = None
        self.pending_input_ticks = 0
        self.sent: list[bytes] = []
        self.chat_messages: list[str] = []
        self._chat_lock = threading.Lock()

    def tick(self) -> None:
        return None

    def _send(self, body: bytes) -> None:
        self.sent.append(body)

    def close(self) -> None:
        return None


def _decode(body: bytes):
    """Разобрать serverbound body обратно в пакет (для проверки)."""
    from quadrix.protocol.buf import Reader
    from quadrix.protocol.packets import play

    reader = Reader(bytes(body))
    packet_id = reader.varint()
    cls = play.SERVERBOUND_ID_TO_CLASS[packet_id]
    return cls.read(reader)


def _game(**kwargs) -> GameScreen:
    kwargs.setdefault("world", FlatWorld(ground_top=1))
    kwargs.setdefault("width", 64.0)
    kwargs.setdefault("height", 48.0)
    game = GameScreen(**kwargs)
    game.stack = ScreenStack(game)
    return game


# ---------------------------------------------------------------------------
# normalize_chat_message / time_alpha
# ---------------------------------------------------------------------------

def test_normalize_collapses_spaces() -> None:
    """Trim + схлопывание пробелов: ``"  a   b "`` → ``"a b"``."""
    assert normalize_chat_message("  hello   world  ") == "hello world"
    assert normalize_chat_message("\thello\tworld\n") == "hello world"
    assert normalize_chat_message("   ") == ""


def test_normalize_truncates_utf16() -> None:
    """Обрезка до 256 UTF-16-единиц (как ServerboundChatPacket)."""
    assert len(normalize_chat_message("a" * 300)) == 256
    # 129 эмодзи (2 единицы каждый) обрезаются до 128 (=256 единиц).
    assert len(normalize_chat_message("\U0001f600" * 129)) == 128


def test_time_alpha_fade() -> None:
    """Непрозрачно 180 тиков, затем гаснет (к 200 — 0)."""
    assert time_alpha(0, 0) == 1.0
    assert time_alpha(180, 0) > 0.99
    assert 0.0 < time_alpha(190, 0) < 1.0
    assert time_alpha(200, 0) == 0.0


def test_chat_log_window_and_fade() -> None:
    """ChatLog: новейшая первой, вне фокуса гаснет (окно строк)."""
    chat = ChatLog()
    chat.add("a", 0)
    chat.add("b", 100)
    chat.add_recent("b")
    assert [line.text for line in chat.lines] == ["b", "a"]
    assert chat.recent == ["b"]

    # В фокусе — обе строки, alpha 1.0.
    focused = chat.visible(150, focused=True)
    assert [line.text for line, _a in focused] == ["b", "a"]
    assert all(a == 1.0 for _l, a in focused)

    # Вне фокуса старая строка уже погасла (250 тиков), новая видна.
    unfocused = chat.visible(250, focused=False)
    assert [line.text for line, _a in unfocused] == ["b"]

    assert chat_lines_per_page(False) == 10
    assert chat_lines_per_page(True) == 20


# ---------------------------------------------------------------------------
# ChatScreen: ввод, Enter, Escape, история
# ---------------------------------------------------------------------------

def test_chat_screen_type_and_submit() -> None:
    """Ввод символов → значение; Enter отправляет нормализованное и закрывает."""
    submitted: list[str] = []
    closed: list[int] = []
    screen = ChatScreen(
        initial="",
        on_submit=submitted.append,
        on_close=lambda: closed.append(1),
    )
    for ch in "  hello   world ":
        screen.handle_key("", ch)
    assert screen.value() == "  hello   world "

    assert screen.handle_key("enter") is True
    assert submitted == ["hello world"]
    assert closed == [1]


def test_chat_screen_escape_closes() -> None:
    """Escape закрывает экран и не отправляет сообщение."""
    submitted: list[str] = []
    closed: list[int] = []
    screen = ChatScreen(
        initial="draft",
        on_submit=submitted.append,
        on_close=lambda: closed.append(1),
    )
    assert screen.handle_key("escape") is True
    assert submitted == []
    assert closed == [1]


def test_chat_screen_history() -> None:
    """Up/Down листают ``recent``; Down из истории возвращает набранное."""
    chat = ChatLog()
    chat.add_recent("first")
    chat.add_recent("second")
    screen = ChatScreen(initial="", chat=chat)

    screen.handle_key("up")
    assert screen.value() == "second"
    screen.handle_key("up")
    assert screen.value() == "first"
    screen.handle_key("down")
    assert screen.value() == "second"
    screen.handle_key("down")
    assert screen.value() == ""


def test_chat_screen_backspace() -> None:
    """Backspace удаляет символ до курсора."""
    screen = ChatScreen(initial="abc")
    assert screen.handle_key("backspace") is True
    assert screen.value() == "ab"


# ---------------------------------------------------------------------------
# GameScreen: открытие чата и локальное эхо (офлайн)
# ---------------------------------------------------------------------------

def test_game_t_opens_chat() -> None:
    """T открывает чат, кладёт экран на стек и отпускает курсор."""
    pointers: list[bool] = []
    game = _game(on_pointer=pointers.append)
    assert game.chat_screen is None

    assert game.handle_key("t") is True
    assert game.chat_screen is not None
    assert game.stack.current is game.chat_screen
    assert pointers == [False]


def test_game_offline_chat_echo() -> None:
    """Офлайн: Enter добавляет сообщение в лог локально (сервера нет)."""
    game = _game()
    game.handle_key("t")
    for ch in "hello":
        game.handle_key("", ch)
    assert game.chat_screen.value() == "hello"

    assert game.handle_key("enter") is True
    assert game.chat_screen is None
    assert game.stack.current is game
    assert game.chat.recent == ["hello"]
    assert any("hello" in line.text for line in game.chat.lines)


def test_game_slash_opens_command() -> None:
    """/ открывает чат с командным префиксом."""
    game = _game()
    assert game.handle_key("slash") is True
    assert game.chat_screen is not None
    assert game.chat_screen.value() == "/"


def test_game_chat_history_reuse() -> None:
    """Отправленное сообщение доступно из истории (Up)."""
    game = _game()
    game.handle_key("t")
    for ch in "hi":
        game.handle_key("", ch)
    game.handle_key("enter")

    game.handle_key("t")
    game.handle_key("up")
    assert game.chat_screen.value() == "hi"


# ---------------------------------------------------------------------------
# GameScreen + сервер: play.Chat и оверлей
# ---------------------------------------------------------------------------

def test_game_send_chat_packet() -> None:
    """Enter в мультиплеере отправляет ``play.Chat`` (offline, signature=None)."""
    from quadrix.protocol.packets import play

    client = FakeClient()
    game = _game(client=client)
    game.handle_key("t")
    for ch in "hi there":
        game.handle_key("", ch)
    game.handle_key("enter")

    chats = [p for p in (_decode(b) for b in client.sent)
             if isinstance(p, play.Chat)]
    assert len(chats) == 1
    assert chats[0].message == "hi there"
    assert chats[0].signature is None
    assert chats[0].last_seen.offset == 0


def test_game_poll_chat_overlay() -> None:
    """Пришедшие ``client.chat_messages`` попадают в оверлей и очищаются."""
    client = FakeClient()
    game = _game(client=client)
    client.chat_messages.append("Server says hi")

    game.update(0.05)

    assert client.chat_messages == []
    assert any(line.text == "Server says hi" for line in game.chat.lines)

    batch = _CaptureBatch()
    game.render(batch, None)
    assert batch.quads  # HUD/чат что-то нарисовали


class _CaptureBatch:
    """Мим Batch: считает добавленные квады (render без дисплея)."""

    def __init__(self) -> None:
        self.quads: list = []
        self.atlas = None

    def add_quad(self, quad) -> None:
        self.quads.append(quad)

    def add_quads(self, quads) -> None:
        self.quads.extend(quads)


# ---------------------------------------------------------------------------
# Client: разбор chat-пакетов (NBT-компонент → плоский текст)
# ---------------------------------------------------------------------------

def test_client_system_chat_to_messages() -> None:
    """SystemChat(NBT) → ``Client.chat_messages``."""
    from quadrix.protocol.packets import play

    client = entry.Client(name="TestPlayer")
    client.motion = object()  # handle_play требует motion не-None.
    packet = play.SystemChat(
        content=Tag(TagType.String, str_val="Hello"), overlay=False
    )
    client.handle_play(packet)
    assert client.chat_messages == ["Hello"]


def test_client_player_chat_plain() -> None:
    """PlayerChat с готовым ``content`` (str) → ``chat_messages``."""
    from quadrix.protocol.packets import play

    client = entry.Client(name="TestPlayer")
    client.motion = object()
    packet = play.PlayerChat(
        global_index=0,
        sender=0,
        index=0,
        signature=None,
        content="player says hi",
        timestamp=0,
        salt=0,
        last_seen=[],
        unsigned_content=None,
        filter=(0, []),
        chat_type=None,
    )
    client.handle_play(packet)
    assert client.chat_messages == ["player says hi"]


def test_client_send_chat_encodes() -> None:
    """``Client.send_chat`` шлёт ServerboundChat (encode без сети)."""
    from quadrix.protocol.packets import play

    client = entry.Client(name="TestPlayer")
    sent: list[bytes] = []
    client._send = sent.append  # type: ignore[assignment]
    client.send_chat("yo")

    assert len(sent) == 1
    packet = _decode(sent[0])
    assert isinstance(packet, play.Chat)
    assert packet.message == "yo"
