#!/usr/bin/env python3
"""[QuadRix] Тесты Gameplay PART 3: мультиплеер, подключение, реальный мир.

Проверяем GUI-путь многопользовательской игры:

    * ``MultiplayerScreen`` — список серверов и футер кнопок (Join/Direct/
      Add/Edit/Delete/Refresh/Back, id 40..46, как в ``multiplayer.rs``);
    * ``DirectConnectScreen`` — ввод адреса + Join (``parse_address``);
    * ``App.connect_server`` — создаёт ``Client`` фабрикой, поднимает
      ``RemoteConnection`` в фоне и открывает ``GameScreen`` с реальным
      ``ClientWorld`` (чанки сервера → меш);
    * WASD и клики идут через ``Client.tick`` / play-пакеты, а не напрямую;
    * ``disconnect`` возвращает в список серверов и закрывает соединение.

``Client`` подменён ``FakeClient``: сеть не нужна, тесты идут в CI.
"""

from __future__ import annotations

import threading

import numpy as np

from quadrix.core.geometry import Vec3
from quadrix.motion.core import MovementResources, PlayerMotion
from quadrix.render.app import App, GameScreen
from quadrix.render.game_world import ChunkTerrainRenderer, chunk_blocks
from quadrix.render.menu import MainMenu, Settings
from quadrix.render.multiplayer_screen import (
    AddServerScreen,
    DirectConnectScreen,
    MultiplayerScreen,
    ServerEntry,
    ServersStore,
    direct_address,
    parse_address,
)
from quadrix.world.chunk import Chunk


# ---------------------------------------------------------------------------
# фейковый клиент (сеть не нужна)
# ---------------------------------------------------------------------------

class FakeWorld:
    """Мир сервера: блоки + чанки (интерфейс ``ClientWorld``)."""

    def __init__(self) -> None:
        self.chunks: dict = {}
        self._blocks: dict = {}

    def set_block(self, pos, name: str) -> None:
        self._blocks[pos] = name

    def block(self, x: int, y: int, z: int) -> str:
        return self._blocks.get((x, y, z), "minecraft:air")


class FakeClient:
    """Мини-``Client``: жизненный цикл + запись отправленных пакетов.

    ``read_one`` спит на событии (иначе фоновый поток крутился бы вхолостую).
    """

    def __init__(self, host: str = "localhost", port: int = 25565) -> None:
        self.host = host
        self.port = port
        self.world = FakeWorld()
        self.motion = PlayerMotion.new(
            MovementResources(properties={}), Vec3(0.0, 64.0, 0.0)
        )
        self.pending_input = None
        self.pending_input_ticks = 0
        self.tick_calls = 0
        self.sent: list = []
        self.closed = 0
        self._stop = threading.Event()
        self._start_input_calls = 0

    # -- подключение --------------------------------------------------

    def prepare(self) -> None:
        return None

    def connect(self) -> None:
        return None

    def handshake(self) -> None:
        return None

    def login(self) -> None:
        return None

    def configure(self) -> None:
        return None

    def enter_play(self) -> None:
        return None

    def _start_input(self) -> None:
        self._start_input_calls += 1

    # -- цикл ---------------------------------------------------------

    def read_one(self) -> bool:
        self._stop.wait(0.05)
        return False

    def tick(self) -> None:
        self.tick_calls += 1

    def _send(self, body: bytes) -> None:
        self.sent.append(body)

    def close(self) -> None:
        self.closed += 1
        self._stop.set()


def _direct_screen(on_connect=None) -> DirectConnectScreen:
    return DirectConnectScreen(427.0, 240.0, on_connect=on_connect)


# ---------------------------------------------------------------------------
# MultiplayerScreen: список и футер
# ---------------------------------------------------------------------------

def test_multiplayer_screen(tmp_path) -> None:
    """Список серверов + 7 кнопок футера; Join/Edit/Delete только при выборе."""
    store = ServersStore(tmp_path / "servers.json")
    store.entries = [
        ServerEntry("Mine", "127.0.0.1:25566"),
        ServerEntry("Other", "example.org"),
    ]
    screen = MultiplayerScreen(427.0, 240.0, store=store)

    assert len(screen.buttons) == 7
    join, direct, add, edit, delete, refresh, back = screen.buttons
    assert join.label_plain() == "Join Server"
    assert direct.label_plain() == "Direct Connection"
    assert add.label_plain() == "Add Server"
    assert back.label_plain() == "Back"
    # Пока ничего не выбрано — Join/Edit/Delete неактивны.
    assert join.active is False
    assert edit.active is False
    assert delete.active is False

    # Клик по первой строке списка выбирает сервер и включает кнопки.
    assert screen.list is not None
    row_y = screen.list.row_y(0) + 1.0
    assert screen.handle_click(screen.list.x + 5.0, row_y) is True
    assert screen.selected_entry() == store.entries[0]
    assert screen.buttons[0].active is True

    # Back зовёт on_back.
    calls: list[int] = []
    screen.on_back = lambda: calls.append(1)
    screen.buttons[6].click()
    assert calls == [1]


# ---------------------------------------------------------------------------
# DirectConnectScreen: ввод адреса
# ---------------------------------------------------------------------------

def test_direct_connect() -> None:
    """Ввод символов → адрес; Join зовёт on_connect с trim-адресом."""
    connected: list[str] = []
    screen = _direct_screen(on_connect=connected.append)

    for ch in "127.0.0.1:25566":
        screen.handle_key("", ch)
    assert screen.value == "127.0.0.1:25566"
    assert parse_address(screen.value) == ("127.0.0.1", 25566)

    assert screen.join() is True
    assert connected == ["127.0.0.1:25566"]

    # Backspace чистит ввод, пустой адрес не соединяет.
    for _ in range(len(screen.value) + 2):
        screen.handle_key("backspace")
    assert screen.value == ""
    assert screen.join() is False
    assert connected == ["127.0.0.1:25566"]
    # Enter по пустому полю — тоже отказ.
    assert screen.handle_key("enter") is False


def test_parse_address_edge_cases() -> None:
    """parse_address: дефолт-порт, IPv6, отказ ведущего '+'."""
    assert parse_address("localhost") == ("localhost", 25565)
    assert parse_address("a:25566") == ("a", 25566)
    assert parse_address("[::1]:25565") == ("::1", 25565)
    assert parse_address("[::1]") == ("::1", 25565)
    assert parse_address("") is None
    assert parse_address("h:+2") is None
    assert parse_address(":25565") is None
    assert direct_address("  host:25565  ") == "host:25565"


# ---------------------------------------------------------------------------
# AddServerScreen: сохранение сервера
# ---------------------------------------------------------------------------

def test_add_server_saves(tmp_path) -> None:
    """Done сохраняет сервер в список по адресу."""
    store = ServersStore(tmp_path / "servers.json")
    screen = AddServerScreen(427.0, 240.0, store=store)
    for ch in "My Server":
        screen.handle_key("", ch)
    screen.handle_click(screen.address_input.x + 2.0,
                        screen.address_input.y + 2.0)
    for ch in "localhost:25566":
        screen.handle_key("", ch)

    assert screen.done() is not None
    assert len(store.entries) == 1
    assert store.entries[0].name == "My Server"
    assert store.entries[0].address == "localhost:25566"


# ---------------------------------------------------------------------------
# App.connect_server: создание клиента и GameScreen
# ---------------------------------------------------------------------------

def test_connect_creates_client() -> None:
    """connect_server зовёт фабрику(host, port) и открывает GameScreen."""
    app = App.init(None, Settings())
    app.open_multiplayer()
    created: list[tuple[str, int]] = []

    def factory(host: str, port: int):
        created.append((host, port))
        return FakeClient(host, port)

    app.client_factory = factory
    game = app.connect_server("127.0.0.1:25566")

    assert created == [("127.0.0.1", 25566)]
    assert isinstance(game, GameScreen)
    assert app.screen_stack.current is game
    assert app.game is game
    assert game.client is not None
    assert game.remote is not None
    assert game.kind == "multiplayer"
    # Соединение поднимается в фоне (не блокирует рендер).
    assert game.remote.connected is True
    game.disconnect()
    assert game.remote is None


def test_connect_bad_address_no_client() -> None:
    """Пустой/некорректный адрес — без клиента и без нового экрана."""
    app = App.init(None, Settings())
    app.open_multiplayer()
    created: list = []
    app.client_factory = lambda host, port: created.append((host, port))
    depth = app.screen_stack.depth()

    assert app.connect_server("bad:+addr") is None
    assert created == []
    assert app.screen_stack.depth() == depth


# ---------------------------------------------------------------------------
# Реальный мир: чанки сервера → меш GameScreen
# ---------------------------------------------------------------------------

def test_client_world_to_game() -> None:
    """GameScreen берёт мир/движение клиента; чанки → меш terrain."""
    client = FakeClient()
    chunk = Chunk.empty(0, 0)
    # Один твёрдый блок на высоте min_y — меш не пустой.
    solid_id = 1
    chunk.set(0, chunk.min_y, 0, solid_id)
    client.world.chunks[(0, 0)] = chunk

    game = GameScreen(client=client, width=64.0, height=48.0)

    assert game.world is client.world
    assert game.player_motion is client.motion
    assert isinstance(game.terrain, ChunkTerrainRenderer)
    assert game.terrain.vertices is not None
    assert game.terrain.vertices.shape[0] > 0

    # chunk_blocks собирает секции в (16, height, 16)[x, y, z].
    blocks = chunk_blocks(chunk)
    assert blocks.shape == (16, chunk.min_y + 16 - chunk.min_y, 16) or blocks.ndim == 3
    assert blocks[0, 0, 0] == solid_id


def test_chunk_mesh_bounded_by_radius() -> None:
    """Меш ограничен ``RADIUS_CHUNKS`` вокруг игрока (память/время, PART 3)."""
    from quadrix.render.game_world import RADIUS_CHUNKS

    world = FakeWorld()
    for cx, cz in ((0, 0), (1, 0), (100, 100)):
        world.chunks[(cx, cz)] = Chunk.empty(cx, cz)

    renderer = ChunkTerrainRenderer(world, radius=2)
    assert ChunkTerrainRenderer(world).radius == RADIUS_CHUNKS
    assert renderer.refresh(center=(0.0, 0.0, 0.0)) is True
    assert renderer._keys == ((0, 0), (1, 0))

    # Переход к далёким чанкам пересобирает меш: в радиусе только они.
    assert renderer.refresh(center=(100 * 16.0, 0.0, 100 * 16.0)) is True
    assert renderer._keys == ((100, 100),)

    # Тот же центр (тот же набор) — пересборки нет.
    assert renderer.refresh(center=(100 * 16.0, 0.0, 100 * 16.0)) is False

    # radius=None — без ограничения (все пришедшие чанки).
    all_renderer = ChunkTerrainRenderer(world, radius=None)
    all_renderer.refresh(center=(0.0, 0.0, 0.0))
    assert all_renderer._keys == ((0, 0), (1, 0), (100, 100))


# ---------------------------------------------------------------------------
# WASD через Client.tick
# ---------------------------------------------------------------------------

def test_wasd_remote() -> None:
    """W → ``pending_input.forward`` и ``Client.tick`` (не напрямую travel)."""
    client = FakeClient()
    game = GameScreen(client=client, width=64.0, height=48.0)

    game.handle_key_down("key.keyboard.w")
    game.update(0.05)

    assert client.tick_calls == 1
    assert client.pending_input is not None
    assert client.pending_input.forward == 1.0
    # yaw синхронизирован с поворотом игрока.
    assert client.motion.yaw == game.rotation.y_rot


# ---------------------------------------------------------------------------
# Клик через play-пакеты
# ---------------------------------------------------------------------------

def test_click_remote() -> None:
    """ЛКМ → два PlayerAction (0 старт, 2 стоп); ПКМ → UseItemOn."""
    client = FakeClient()
    client.world.set_block((0, 2, 3), "minecraft:stone")
    game = GameScreen(client=client, width=64.0, height=48.0)
    game.camera.position = (0.5, 2.5, 0.5)
    game.camera.yaw = 0.0
    game.camera.pitch = 0.0

    from quadrix.protocol.packets import play

    assert game.handle_mouse_click(0) is True
    actions = [p for p in (_decode(body) for body in client.sent)
               if isinstance(p, play.PlayerAction)]
    assert [a.action for a in actions] == [0, 2]
    assert actions[0].pos == (0, 2, 3)

    # ПКМ: UseItemOn по тому же блоку.
    game.camera.pitch = 0.0
    assert game.handle_mouse_click(1) is True
    uses = [p for p in (_decode(body) for body in client.sent)
            if isinstance(p, play.UseItemOn)]
    assert len(uses) == 1
    assert uses[0].pos == (0, 2, 3)


def _decode(body: bytes):
    """Разобрать serverbound body обратно в пакет (для проверки)."""
    from quadrix.protocol.buf import Reader
    from quadrix.protocol.packets import play

    reader = Reader(bytes(body))
    packet_id = reader.varint()
    cls = play.SERVERBOUND_ID_TO_CLASS[packet_id]
    return cls.read(reader)


# ---------------------------------------------------------------------------
# disconnect: возврат в список серверов
# ---------------------------------------------------------------------------

def test_disconnect_returns() -> None:
    """disconnect закрывает клиента и возвращает MultiplayerScreen."""
    app = App.init(None, Settings())
    app.open_multiplayer()
    clients: list[FakeClient] = []

    def factory(host: str, port: int):
        client = FakeClient(host, port)
        clients.append(client)
        return client

    app.client_factory = factory
    game = app.connect_server("127.0.0.1:25566")
    assert game is not None
    client = clients[0]

    game.disconnect()

    assert app.game is None
    assert isinstance(app.screen_stack.current, MultiplayerScreen)
    assert client.closed == 1
    # Повторный disconnect — no-op.
    game.disconnect()
    assert client.closed == 1
