#!/usr/bin/env python3
"""QuadRix — CLI-клиент, подключающийся к LAN-серверу Horizon.

Порт horizon/crates/horizon-client/src/{main,client_lib,entry}.rs в части
CLI и последовательности подключения:

    handshake -> login -> configuration -> play

Что делает клиент:
  * ``send_handshake(host, port, LOGIN)``;
  * login: offline-mode шлёт ``LoginStart(name, offline_uuid(name))``,
    online-mode дополнительно ждёт ``EncryptionRequest``, шифрует
    shared secret публичным ключом сервера и включает AES/CFB8;
  * configuration: brand + ClientInformation, затем цикл до
    ``FinishConfiguration`` (реестры, теги, known packs, ресурс-паки);
  * play: читает clientbound-пакеты и разводит их по обработчикам
    (PlayerPosition / PlayerRotation, KeepAlive, LevelChunkWithLight,
    SetHealth, SetTime, SystemChat, Disconnect), а 20 раз в секунду
    тикает ``PlayerMotion`` и синхронизирует позицию на сервер.

Все сообщения начинаются с ``[QuadRix]``. При ошибке клиент печатает
понятное сообщение и завершается с кодом 1.

Запуск:
    python quadrix.py --host localhost --port 25565 --name TestPlayer
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from quadrix.core.geometry import Vec3
from quadrix.health import HealthResources, PlayerFloatIds, PlayerHealth
from quadrix.motion.core import (
    MovementResources,
    PlayerInput,
    PlayerMotion,
)
from quadrix.player_sync import (
    PositionSender,
    apply_server_position,
    sync_client_to_server,
)
from quadrix.protocol import ids
from quadrix.protocol.buf import ProtocolError, Writer
from quadrix.protocol.connection import Connection, ConnectionState
from quadrix.protocol.crypto import RsaPublicKey, generate_secret, offline_uuid
from quadrix.protocol.packets import configuration, login, play
from quadrix.protocol.packets.handshake import LOGIN
from quadrix.world.chunk import BlockEntity, Chunk, ChunkData as WorldChunkData
from quadrix.world.registry import BlockStateId, load_registry

__all__ = [
    "Client",
    "ClientError",
    "ClientWorld",
    "GuiUnavailable",
    "build_parser",
    "main",
    "parse_args",
    "run_gui",
]

#: Один такт игры: 20 Гц (как ``game.rs`` / ``motion.rs``).
TICK_RATE: int = 20
TICK_SECONDS: float = 1.0 / TICK_RATE

#: Директория подготовленных данных (Rust: ``root.join(...)``).
DEFAULT_DATA_DIR: str = ".local"

#: Бренд клиента: ``net.rs::brand`` пишет "vanilla".
CLIENT_BRAND: str = "vanilla"

#: Значение по умолчанию для view distance в ClientInformation.
DEFAULT_VIEW_DISTANCE: int = 8

#: Действие ResourcePackResponse: DECLINED (не тянем пак).
RESOURCE_PACK_DECLINED: int = 1


class ClientError(Exception):
    """Ошибка подключения/протокола с понятным человеку текстом."""


class GuiUnavailable(RuntimeError):
    """GUI не может открыть окно: нет дисплея, драйвера или пакетов glfw.

    Наследует ``RuntimeError`` намеренно: раньше ``run_gui`` превращал
    любую проблему GUI в код возврата 1.  Теперь недоступность дисплея
    отличается от прочих ошибок, чтобы ``main`` мог уйти в headless.
    """


def _log(message: str) -> None:
    """Напечатать строку с префиксом QuadRix."""
    print(f"[QuadRix] {message}", flush=True)


def _cache_movement_resources() -> None:
    """Прочитать movement-properties.nbt один раз, как это делает Rust.

    ``motion/core.py::travel`` (и ``jump_factor``) вызывает
    ``MovementResources.load(".local/horizon-client-motion")`` на каждом
    такте, а тот каждый раз парсит NBT на ~1800 блоков — это ~2.5 с на
    такт и ломает 20 Гц.  Rust читает ``movement-properties.nbt`` один
    раз при старте, поэтому оборачиваем загрузчик в кэш по пути.  Данные
    в ``.local`` неизменны, так что кэш корректен.
    """
    if getattr(MovementResources, "_quadrix_cached", False):
        return
    original = MovementResources.load
    cache: Dict[str, MovementResources] = {}

    @staticmethod
    def cached(root: object) -> MovementResources:
        key = str(Path(root))
        hit = cache.get(key)
        if hit is None:
            hit = original(root)
            cache[key] = hit
        return hit

    MovementResources.load = cached  # type: ignore[assignment]
    MovementResources._quadrix_cached = True  # type: ignore[attr-defined]


def _to_world_chunk_data(raw: "play.ChunkData") -> WorldChunkData:
    """``play.ChunkData`` (провод) -> ``world.chunk.ChunkData`` (декодер).

    Поля совпадают один в один (heightmaps, buffer, block_entities), но
    у протокольного класса нет ``sections()``.  Конвертируем, не
    переизобретая раскладку: ``Chunk.from_chunk_data`` ждёт именно
    мировой вариант, который умеет разбирать ``buffer``.
    """
    return WorldChunkData(
        heightmaps=list(raw.heightmaps),
        buffer=bytes(raw.buffer),
        block_entities=[
            BlockEntity(e.packed_xz, e.y, e.kind, e.tag)
            for e in raw.block_entities
        ],
    )


# ── Мир, собранный из пришедших чанков ────────────────────────────────


class ClientWorld:
    """Разрешение блоков по сохранённым чанкам.

    ``PlayerMotion.tick``/``travel`` ждут ``world.block(x, y, z) -> str``.
    Состояние секции — registry id; имя даёт :class:`BlockRegistry`.
    Чанка нет — возвращается ``minecraft:air`` (как у незагруженной
    колонки).
    """

    def __init__(self) -> None:
        self.chunks: Dict[Tuple[int, int], Chunk] = {}
        self.registry = None

    def set_registry(self, registry) -> None:
        self.registry = registry

    def add_chunk(self, chunk: Chunk) -> None:
        self.chunks[(chunk.x, chunk.z)] = chunk

    def block(self, x: int, y: int, z: int) -> str:
        chunk = self.chunks.get((x >> 4, z >> 4))
        if chunk is None:
            return "minecraft:air"
        state_id = chunk.get(x, y, z)
        if self.registry is None:
            return "minecraft:air"
        state = self.registry.state(BlockStateId(state_id))
        if state is None:
            return "minecraft:air"
        return state.name


# ── Клиент ────────────────────────────────────────────────────────────


class Client:
    """Синхронный CLI-клиент Horizon LAN.

    Шаги подключения вызываются по отдельности (``connect`` ->
    ``handshake`` -> ``login`` -> ``configure`` -> ``enter_play``),
    потому что так удобно и в ``main``, и в интеграционном тесте.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 25565,
        name: str = "TestPlayer",
        *,
        online_mode: bool = False,
        data_dir: str = DEFAULT_DATA_DIR,
        verbose: bool = False,
        connect_timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.name = name
        self.online_mode = bool(online_mode)
        self.data_dir = Path(data_dir)
        self.verbose = bool(verbose)
        self.connect_timeout = float(connect_timeout)
        self.control_host = "127.0.0.1"
        self.control_port = 25566
        self.control_server: Optional[ControlServer] = None

        self.conn: Optional[Connection] = None
        self.profile = None
        self.registries: Dict[str, object] = {}
        self.tags: Dict[str, object] = {}
        self.features: List[str] = []
        self.known_packs: List[object] = []
        self.cookies: Dict[str, bytes] = {}

        self.world = ClientWorld()
        self.motion: Optional[PlayerMotion] = None
        self.sync_state = PositionSender()
        self.health: Optional[PlayerHealth] = None

        self.running = False
        self.ticks = 0
        self.game_time = 0
        self.last_position: Optional[Tuple[float, float, float]] = None
        self.packets_seen = 0
        self.chunks_seen = 0
        self._loaded_sent = False

        self._registry = None
        self._manual_input: Optional[PlayerInput] = None
        # Ввод, взведённый control-сервером: Client.tick() сам выполнит
        # travel + tick + sync_client_to_server, поэтому сервер увидит движение.
        self.pending_input: Optional[PlayerInput] = None
        self.pending_input_ticks: int = 0
        self._input_thread: Optional[threading.Thread] = None
        self._auto_clock = 0
        # Замок отправки: сокет делят игровой поток (движение/клики) и
        # поток-читатель (KeepAlive/AcceptTeleportation в read_one).
        self._send_lock = threading.Lock()
        # Чат (Gameplay PART 4): пришедшие сообщения читает GUI-поток,
        # пишет поток-читатель — общий список под замком.
        self.chat_messages: List[str] = []
        self._chat_lock = threading.Lock()

    # -- ресурсы и мир -------------------------------------------------

    def prepare(self) -> None:
        """Загрузить локальные данные: движение, реестр блоков, здоровье."""
        _cache_movement_resources()
        motion_dir = self.data_dir / "horizon-client-motion"
        
        try:
            movement = MovementResources.load(motion_dir)
            self.motion = PlayerMotion.new(movement, Vec3(0.0, 64.0, 0.0))
        except (OSError, KeyError, ValueError) as exc:
            raise ClientError(
                f"не удалось загрузить movement-properties.nbt "
                f"({motion_dir}): {exc}"
            ) from exc

        registry_path = motion_dir / "block-registry.nbt"
        if registry_path.exists():
            try:
                self._registry = load_registry(registry_path)
                self.world.set_registry(self._registry)
            except (OSError, ValueError) as exc:
                _log(f"block-registry.nbt не прочитан, блоки = air: {exc}")
        else:
            _log(f"block-registry.nbt не найден ({registry_path}), блоки = air")

        self.health = self._load_health()

    def _load_health(self) -> PlayerHealth:
        """PlayerHealth из .local/horizon-client-health (fallback — пустой)."""
        root = self.data_dir / "horizon-client-health"
        try:
            resources = HealthResources.load(root)
        except (OSError, ValueError, KeyError) as exc:
            _log(f"health-данные не прочитаны ({root}): {exc}")
            resources = HealthResources(
                damage={}, ids=PlayerFloatIds(health=0, absorption=1)
            )
        return PlayerHealth.new(resources, {"minecraft:max_health": 20.0})

    # -- шаги подключения ---------------------------------------------

    def connect(self) -> None:
        """TCP-соединение с сервером (Rust: Connection::connect)."""
        if self.motion is None:
            self.prepare()
        try:
            self.conn = Connection.connect(
                self.host, self.port, timeout=self.connect_timeout
            )
        except ProtocolError as exc:
            raise ClientError(
                f"не удалось подключиться к {self.host}:{self.port} — {exc}"
            ) from exc
        self.conn.set_read_timeout(self.connect_timeout)
        _log(f"соединение установлено: {self.host}:{self.port}")

    def _require_conn(self) -> Connection:
        if self.conn is None:
            raise ClientError("соединение не открыто (сначала connect())")
        return self.conn

    def handshake(self) -> None:
        """ClientIntention с намерением LOGIN."""
        conn = self._require_conn()
        conn.send_handshake(self.host, self.port, LOGIN)
        _log(f"handshake: intent=LOGIN, protocol={conn.protocol}")

    def login(self) -> None:
        """Login: offline/online hello, шифрование, LoginFinished."""
        conn = self._require_conn()
        conn.send_login_start(self.name, offline_uuid(self.name))
        _log(f"login: LoginStart name={self.name} offline-uuid={offline_uuid(self.name):032x}")

        while True:
            packet_id, payload = conn.read_packet()
            packet = login.Clientbound.decode(packet_id, payload)
            name = type(packet).__name__
            self._log_packet("login", name, len(payload))

            if isinstance(packet, login.Compression):
                conn.set_compression(packet.threshold)
                _log(f"login: сжатие threshold={packet.threshold}")
            elif isinstance(packet, login.LoginFinished):
                self.profile = packet.profile
                conn.send_login_acknowledged()
                _log(
                    "login: LoginFinished player="
                    f"{packet.profile.name} uuid="
                    f"{packet.profile.uuid:032x} -> configuration"
                )
                return
            elif isinstance(packet, login.Disconnect):
                raise ClientError(f"сервер разорвал login: {packet.reason_json}")
            elif isinstance(packet, login.Hello):
                self._answer_encryption(packet)
            elif isinstance(packet, login.CustomQuery):
                answer = login.CustomQueryAnswer(
                    transaction=packet.transaction, payload=None
                )
                self._send(login.Serverbound.encode(answer))
            elif isinstance(packet, login.CookieRequest):
                response = login.CookieResponse(
                    key=packet.key, payload=self.cookies.get(packet.key)
                )
                self._send(login.Serverbound.encode(response))
            elif self.verbose:
                m = getattr(packet, "payload", b"")
                _log(f"login: {name} пропущен ({len(m)} байт)")

    def _answer_encryption(self, hello: "login.Hello") -> None:
        """Online-mode: зашифровать shared secret и включить AES/CFB8."""
        conn = self._require_conn()
        if not hello.should_authenticate:
            _log("login: EncryptionRequest без аутентификации (шифруем)")
        else:
            # Полноценный join требует сессии Mojang; у CLI её нет.
            _log(
                "login: server request authentication, но CLI без сессии "
                "Mojang — сервер может отказать"
            )
        key = RsaPublicKey.from_der(hello.public_key)
        secret = generate_secret()
        response = login.Key(
            key=key.encrypt(secret),
            challenge=key.encrypt(hello.challenge),
        )
        self._send(login.Serverbound.encode(response))
        conn.enable_encryption(secret)
        self.online_mode = True
        _log("login: AES/CFB8 включён")

    def configure(self) -> None:
        """Configuration: реестры/теги/known packs до FinishConfiguration."""
        conn = self._require_conn()

        brand_writer = Writer()
        brand_writer.string(CLIENT_BRAND)
        brand = configuration.CustomPayload(
            channel="minecraft:brand", data=bytes(brand_writer.data)
        )
        self._send(configuration.Serverbound.encode(brand))
        info = configuration.ClientInformation.new(DEFAULT_VIEW_DISTANCE)
        self._send(configuration.Serverbound.encode(info))
        _log(
            f"configuration: brand={CLIENT_BRAND!r} "
            f"view_distance={DEFAULT_VIEW_DISTANCE}"
        )

        while True:
            packet_id, payload = conn.read_packet()
            packet = configuration.Clientbound.decode(packet_id, payload)
            name = type(packet).__name__
            self._log_packet("configuration", name, len(payload))

            if isinstance(packet, configuration.FinishConfiguration):
                conn.send_finish_configuration()
                _log("configuration: FinishConfiguration -> play")
                return
            if isinstance(packet, configuration.KeepAlive):
                self._send(
                    configuration.Serverbound.encode(
                        configuration.KeepAlive(id=packet.id)
                    )
                )
            elif isinstance(packet, configuration.Ping):
                self._send(
                    configuration.Serverbound.encode(configuration.Ping(id=packet.id))
                )
            elif isinstance(packet, configuration.SelectKnownPacks):
                self.known_packs = list(packet.packs)
                # У CLI нет копии ванильного пака: отвечаем пустым списком,
                # и сервер пришлёт данные реестров целиком.
                reply = configuration.SelectKnownPacks(packs=[])
                self._send(configuration.Serverbound.encode(reply))
                _log(f"configuration: known packs предложено {len(packet.packs)}")
            elif isinstance(packet, configuration.RegistryData):
                self.registries[packet.registry] = packet
            elif isinstance(packet, configuration.UpdateTags):
                self.tags = {r.registry: r for r in packet.registries}
            elif isinstance(packet, configuration.UpdateEnabledFeatures):
                self.features = list(packet.features)
                _log(f"configuration: features={self.features}")
            elif isinstance(packet, configuration.ResourcePackPush):
                decline = configuration.ResourcePackResponse(
                    id=packet.id, action=RESOURCE_PACK_DECLINED
                )
                self._send(configuration.Serverbound.encode(decline))
                _log(f"configuration: resource pack {packet.url} отклонён")
            elif isinstance(packet, configuration.ResourcePackPop):
                _log("configuration: resource pack pop")
            elif isinstance(packet, configuration.CookieRequest):
                response = configuration.CookieResponse(
                    key=packet.key, payload=self.cookies.get(packet.key)
                )
                self._send(configuration.Serverbound.encode(response))
            elif isinstance(packet, configuration.StoreCookie):
                self.cookies[packet.key] = packet.payload
            elif isinstance(packet, configuration.Disconnect):
                raise ClientError(
                    f"сервер разорвал configuration: {packet.reason}"
                )
            elif isinstance(packet, configuration.Transfer):
                raise ClientError(
                    f"сервер просит transfer на {packet.host}:{packet.port}"
                )
            elif self.verbose:
                _log(f"configuration: {name} пропущен")

    def enter_play(self) -> None:
        """Войти в play-состояние и запустить tick-loop."""
        conn = self._require_conn()
        if conn.state is not ConnectionState.PLAY:
            conn.finish_configuration()
        self.running = True
        self._start_input()
        conn.set_read_timeout(TICK_SECONDS)
        _log("play: состояние PLAY, tick-loop 20 Гц")

    # -- play-loop -----------------------------------------------------

    def read_one(self) -> bool:
        """Прочитать и обработать один clientbound-пакет.

        ``False`` означает таймаут (пакетов пока нет). Прочие ошибки
        пробрасываются наружу.
        """
        conn = self._require_conn()
        try:
            packet_id, payload = conn.read_packet()
        except ProtocolError as exc:
            if "Timed out" in str(exc):
                return False
            raise
        self.packets_seen += 1
        try:
            packet = self.conn.decode_packet(packet_id, payload)
        except play.Unsupported:
            if self.verbose:
                _log(f"play: непортированный пакет id={packet_id}")
            return True
        self.handle_play(packet)
        return True

    def handle_play(self, packet) -> None:
        """Развести clientbound play-пакет по обработчикам."""
        if self.motion is None:
            return
        name = type(packet).__name__

        if isinstance(packet, play.PlayerPosition):
            apply_server_position(self.motion, packet)
            self.last_position = self.motion.position.components()
            # Сервер только что телепортировал нас: сбрасываем baseline
            # PositionSender на принятую позицию, иначе первый же
            # move-пакет уйдёт с огромной дельтой и сервер отклонит его
            # (multiplayer.disconnect.invalid_player_movement).
            self.sync_state.position = self.motion.position.components()
            self.sync_state.rotation = (
                float(self.motion.yaw),
                float(getattr(self.motion, "pitch", 0.0)),
            )
            self.sync_state.on_ground = bool(self.motion.on_ground)
            self.sync_state.reminder = 0
            self.sync_state._has_position = True
            accept = play.AcceptTeleportation(
                id=packet.teleport,
                x=float(self.motion.position.x),
                y=float(self.motion.position.y),
                z=float(self.motion.position.z),
                yaw=float(self.motion.yaw),
                pitch=float(getattr(self.motion, "pitch", 0.0)),
            )
            self._send(play.Serverbound.encode(accept))
            self._maybe_send_loaded()
            _log(
                "play: PlayerPosition -> "
                f"{self.motion.position.x:.2f} "
                f"{self.motion.position.y:.2f} "
                f"{self.motion.position.z:.2f}"
            )
        elif isinstance(packet, play.PlayerRotation):
            if packet.relative_yaw:
                self.motion.yaw = float(self.motion.yaw + packet.yaw)
            else:
                self.motion.yaw = float(packet.yaw)
            pitch = float(getattr(self.motion, "pitch", 0.0))
            if packet.relative_pitch:
                pitch = pitch + float(packet.pitch)
            else:
                pitch = float(packet.pitch)
            self.motion.pitch = pitch
            self._log_packet("play", name, 0)
        elif isinstance(packet, play.KeepAlive):
            self._send(play.Serverbound.encode(play.KeepAlive(id=packet.id)))
            self._log_packet("play", name, 0)
        elif isinstance(packet, play.LevelChunkWithLight):
            chunk = Chunk.from_chunk_data(
                packet.x, packet.z, _to_world_chunk_data(packet.chunk)
            )
            light = getattr(packet, "light", None)
            if light is not None:
                chunk.light = light
            self.world.add_chunk(chunk)
            self.chunks_seen += 1
            self._maybe_send_loaded()
            if self.verbose:
                _log(
                    f"play: LevelChunkWithLight chunk=({packet.x},{packet.z}) "
                    f"секций={len(chunk.sections)}"
                )
        elif isinstance(packet, play.ChunkBatchFinished):
            self._send(
                play.Serverbound.encode(
                    play.ChunkBatchReceived(chunks_per_tick=float(packet.size))
                )
            )
            self._log_packet("play", name, 0)
        elif isinstance(packet, play.SetHealth):
            if self.health is not None:
                self.health.set_health(packet.health)
                self.health.flash_health_change(packet.health)
                self.health.food["food"] = packet.food
                self.health.food["saturation"] = packet.saturation
            _log(
                f"play: SetHealth health={packet.health} "
                f"food={packet.food} saturation={packet.saturation}"
            )
        elif isinstance(packet, play.SetTime):
            self.game_time = packet.game_time
            _log(f"play: SetTime game_time={packet.game_time}")
        elif isinstance(packet, (play.SystemChat, play.DisguisedChat, play.PlayerChat)):
            text = self._chat_text(packet)
            if text:
                with self._chat_lock:
                    self.chat_messages.append(text)
            _log(f"chat: {text}")
        elif isinstance(packet, play.Disconnect):
            raise ClientError(f"сервер разорвал play: {packet.reason}")
        elif self.verbose:
            _log(f"play: {name} пропущен")

    # -- чат (Gameplay PART 4) -----------------------------------------

    def _chat_text(self, packet) -> str:
        """Плоский текст chat-пакета (NBT-компонент → строка).

        ``SystemChat.content``/``DisguisedChat.message``/``PlayerChat.
        unsigned_content`` — NBT ``Tag``; ``PlayerChat.content`` — готовый
        ``str``. Порт ``component::comp_text`` (``tag_to_json`` → ``Text.plain``).
        """
        from quadrix.core.component import comp_text, tag_to_json
        from quadrix.protocol.packets import play

        if isinstance(packet, play.PlayerChat):
            if packet.unsigned_content is not None:
                return comp_text(tag_to_json(packet.unsigned_content)).plain()
            return str(packet.content)
        if isinstance(packet, play.SystemChat):
            return comp_text(tag_to_json(packet.content)).plain()
        if isinstance(packet, play.DisguisedChat):
            return comp_text(tag_to_json(packet.message)).plain()
        return ""

    def send_chat(self, message: str) -> None:
        """Отправить сообщение чата серверу (``ServerboundChat``).

        FALLBACK: подпись сообщения (online-mode, ``signature``) не
        портирована — это offline-чат (``signature=None``). См. правило 7.
        """
        from quadrix.protocol.packets import play

        packet = play.Chat(
            message=message,
            timestamp=int(time.time() * 1000),
            salt=0,
            signature=None,
            last_seen=play.LastSeenUpdate(
                offset=0, acknowledged=b"\x00\x00\x00", checksum=0
            ),
        )
        self._send(play.Serverbound.encode(packet))

    # -- тики ----------------------------------------------------------

    def _maybe_send_loaded(self) -> None:
        """Сообщить PlayerLoaded, когда есть и позиция, и хотя бы один чанк.

        ``hub.rs::handleAcceptPlayerLoad`` до этого игнорирует движение
        игрока, поэтому отправляем ровно один раз.
        """
        if self._loaded_sent:
            return
        if self.last_position is None or self.chunks_seen == 0:
            return
        self._send(play.Serverbound.encode(play.PlayerLoaded()))
        self._loaded_sent = True
        _log("play: PlayerLoaded — клиент сообщил, что уровень загружен")

    def tick(self) -> None:
        """Один игровой такт: ввод, движение, синхронизация позиции."""
        if self.motion is None:
            return
        world = self.world
        if self.pending_input_ticks > 0 and self.pending_input is not None:
            inp = self.pending_input
            self.pending_input_ticks -= 1
            if self.pending_input_ticks == 0:
                self.pending_input = None
        else:
            inp = self._read_input()
        self.motion.travel(inp, world)
        self.motion.tick(TICK_SECONDS, world)
        if self.health is not None:
            self.health.advance_clock()

        # Двигаемся только после того, как сервер прислал свою позицию
        # И мы отправили PlayerLoaded: иначе сервер либо получит движение
        # из несуществующей точки, либо проигнорирует его до загрузки
        # уровня (hub.rs::handleAcceptPlayerLoad).  PlayerLoaded уходит
        # раньше первого MovePlayerPos.
        if self.last_position is not None and self._loaded_sent:
            packet = sync_client_to_server(self.motion, self.sync_state)
            if packet is not None:
                self._send(play.Serverbound.encode(packet))
        # ServerboundClientTickEndPacket завершает тик клиента.  Без него
        # сервер не сбрасывает ``position_this_tick``
        # (hub.rs::handleClientTickEnd) и на втором же пакете перемещения
        # за один серверный тик отключает с сообщением
        # multiplayer.disconnect.invalid_player_movement.
        self._send(play.Serverbound.encode(play.ClientTickEnd()))
        self.ticks += 1

    def run(self, max_ticks: int = 0) -> None:
        """Главный цикл классического клиента."""
        conn = self._require_conn()
        next_tick = time.monotonic() + TICK_SECONDS
        while self.running:
            self.read_one()
            now = time.monotonic()
            while now >= next_tick:
                self.tick()
                next_tick += TICK_SECONDS
                if max_ticks and self.ticks >= max_ticks:
                    self.running = False
                    break
            if self.control_server:
                self.control_server.poll()
        _log(f"play: выход; тиков={self.ticks}, пакетов={self.packets_seen}")

    # -- ввод ----------------------------------------------------------

    def _start_input(self) -> None:
        """Читать stdin, если это TTY; иначе — авто-движение."""
        is_tty = False
        try:
            is_tty = bool(sys.stdin is not None and sys.stdin.isatty())
        except (ValueError, OSError):
            is_tty = False
        if is_tty:
            self._input_thread = threading.Thread(
                target=self._stdin_loop, name="quadrix-stdin", daemon=True
            )
            self._input_thread.start()
            _log("ввод: интерактивный (WASD/space/shift, Ctrl-D — авто)")
        else:
            _log("ввод: не-TTY, без stdin — управление только через --daemon/quadrixctl")

    def _stdin_loop(self) -> None:
        """Построчно разбирать управление из stdin (демон-поток)."""
        while self.running:
            try:
                line = sys.stdin.readline()
            except (ValueError, OSError):
                break
            if not line:
                break
            text = line.strip().lower()
            if text in ("quit", "exit"):
                self.running = False
                break
            inp = PlayerInput()
            for token in text.split():
                if token == "w":
                    inp.forward += 1.0
                elif token == "s":
                    inp.forward -= 1.0
                elif token == "a":
                    inp.strafe -= 1.0
                elif token == "d":
                    inp.strafe += 1.0
                elif token == "jump":
                    inp.jump = True
                elif token == "sneak":
                    inp.sneak = True
                elif token == "sprint":
                    inp.sprint = True
            self._manual_input = inp

    def _read_input(self) -> PlayerInput:
        """Ввод этого такта: ручной, иначе no-op.

        Yaw/pitch здесь НЕ меняются: поворот приходит только от control-
        сервера (``look`` / ``turn``).  Автоповорот был тестовым кодом и
        ломал управление (yaw крутился сам по +1.5°/тик).
        ``pending_input`` от control-сервера обрабатывается в ``tick()``
        раньше этого метода.
        """
        if self._manual_input is not None:
            return self._manual_input
        self._auto_clock += 1
        return PlayerInput(forward=0.0, strafe=0.0, jump=False, sprint=False, sneak=False)

    # -- отправка / логирование ---------------------------------------

    def _send(self, body: bytes) -> None:
        """Отправить тело с VarInt-id (Rust: Connection::send).

        Замок не даёт кадрам двух потоков (игровой + читатель) переплестись.
        """
        conn = self._require_conn()
        with self._send_lock:
            conn.send(body)

    def _log_packet(self, state: str, name: str, size: int) -> None:
        """Напечатать факт пакета: всегда при --verbose, иначе важные."""
        if self.verbose or name in (
            "PlayerPosition",
            "PlayerRotation",
            "KeepAlive",
            "LevelChunkWithLight",
            "SetHealth",
            "SetTime",
            "SystemChat",
            "Disconnect",
        ):
            _log(f"{state}: {name} ({size} байт)")

    def close(self) -> None:
        """Закрыть соединение (идемпотентно)."""
        self.running = False
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.control_server is not None:
            self.control_server.stop()


# ── CLI ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Собрать argparse: --host, --port, --name, режим и отладка."""
    parser = argparse.ArgumentParser(
        prog="quadrix.py",
        description="QuadRix — CLI-клиент Horizon LAN (handshake->play).",
    )
    parser.add_argument("--host", default="localhost", help="адрес сервера")
    parser.add_argument("--port", type=int, default=25565, help="порт сервера")
    parser.add_argument("--name", default="TestPlayer", help="имя игрока")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--online-mode",
        action="store_true",
        help="online-mode: шифрование через сессию Mojang",
    )
    mode.add_argument(
        "--offline-mode",
        action="store_true",
        help="offline-mode (по умолчанию): LoginStart с offline UUID",
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help="директория подготовленных данных (.local)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="логировать каждый пакет"
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=0,
        help="остановиться после N игровых тактов (0 — бесконечно)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=10.0,
        help="таймаут подключения, секунды",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="запустить control server (TCP JSON-lines)",
    )
    parser.add_argument(
        "--control-host",
        default="127.0.0.1",
        help="host control server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=25566,
        help="port control server (default: 25566)",
    )
    display = parser.add_mutually_exclusive_group()
    display.add_argument(
        "--headless",
        action="store_true",
        help="headless-режим без окна (по умолчанию — GUI)",
    )
    display.add_argument(
        "--gui",
        action="store_true",
        help="явно запустить окно GUI (App: меню → игра); это режим по умолчанию",
    )
    display.add_argument(
        "--no-gui",
        action="store_true",
        help="alias для --headless: headless-режим без окна",
    )
    parser.add_argument(
        "--width", type=int, default=854, help="ширина окна GUI (default: 854)"
    )
    parser.add_argument(
        "--height", type=int, default=480, help="высота окна GUI (default: 480)"
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Разобрать argv и нормализовать режимы GUI/headless/daemon.

    Правила (AGENTS.md: GUI — режим по умолчанию):

    * ни ``--gui``, ни ``--headless``/``--no-gui`` не заданы → GUI;
    * ``--headless`` или ``--no-gui`` → headless (``args.headless=True``);
    * ``--daemon`` подразумевает headless: окно и control-сервер
      несовместимы, поэтому daemon всегда выигрывает у ``--gui``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # --no-gui — просто более старый alias для --headless.
    if args.no_gui:
        args.headless = True

    # --daemon требует headless: окно и control-сервер несовместимы.
    # Если пользователь просил --gui, предупреждаем и уходим в headless.
    if args.daemon:
        if args.gui:
            _log("--daemon и --gui несовместимы; --daemon implies headless")
        elif not args.headless:
            _log("--daemon implies headless")
        args.headless = True
        args.gui = False

    return args


def run_gui(args: argparse.Namespace) -> int:
    """Запустить окно GUI: главный цикл ``App`` (порт ``entry.rs::main``).

    Если окно не создаётся (нет дисплея/драйвера/пакетов ``glfw``),
    поднимается :class:`GuiUnavailable` — ``main`` тогда переходит на
    headless-путь вместо аварийного завершения.
    """
    from quadrix.render.app import App
    from quadrix.render.backend import BackendType, create_backend
    from quadrix.render.menu import Settings

    settings = Settings()
    options_path = Path(args.data_dir) / "options.txt"
    if options_path.exists():
        try:
            settings = Settings.load(options_path)
        except (OSError, ValueError) as exc:
            _log(f"options.txt не прочитан ({options_path}): {exc}")

    # Создание бэкенда и окна — единственное место, где отсутствие
    # дисплея неотличимо от реальной ошибки: превращаем его в
    # GuiUnavailable, чтобы main мог уйти в headless.
    try:
        backend = create_backend(
            BackendType.MODERNGL, args.width, args.height, "QuadRix"
        )
        app = App.init(
            backend, settings, width=backend.width, height=backend.height
        )
    except RuntimeError as exc:
        raise GuiUnavailable(str(exc)) from exc

    # GUI-подключение: список серверов и фабрика Client (addr, port) -> Client.
    app.servers_store.path = Path(args.data_dir).parent / "servers.json"
    app.servers_store.load()

    def _make_client(host: str, port: int) -> "Client":
        return Client(
            host=host,
            port=port,
            name=args.name,
            online_mode=args.online_mode,
            data_dir=args.data_dir,
            verbose=args.verbose,
            connect_timeout=args.connect_timeout,
        )

    app.client_factory = _make_client

    try:
        app.setup()
        app.loop(max_ticks=args.ticks)
        return 0
    except RuntimeError as exc:
        _log(f"GUI недоступен: {exc}")
        return 1
    finally:
        app.shutdown()


def main(argv: Optional[List[str]] = None) -> int:
    """Точка входа CLI. Возвращает код выхода."""
    # Windows-консоль по умолчанию не UTF-8: делаем вывод читаемым.
    from contextlib import suppress

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with suppress(ValueError, OSError):
                reconfigure(encoding="utf-8")
    args = parse_args(argv)

    # GUI — режим по умолчанию. Если окно не открывается (нет дисплея,
    # драйвера или пакетов glfw), предупреждаем и продолжаем как headless,
    # а не завершаемся с ошибкой.
    if not args.headless:
        try:
            return run_gui(args)
        except GuiUnavailable as exc:
            _log(f"no display, falling back to headless ({exc})")

    client = Client(
        host=args.host,
        port=args.port,
        name=args.name,
        online_mode=args.online_mode,
        data_dir=args.data_dir,
        verbose=args.verbose,
        connect_timeout=args.connect_timeout,
    )
    if args.daemon:
        from quadrix.control.server import ControlServer
        client.control_server = ControlServer(
            host=args.control_host,
            port=args.control_port,
            client=client,
        )
        client.control_server.start()

    try:
        client.connect()
        client.handshake()
        client.login()
        client.configure()
        client.enter_play()
        client.run(max_ticks=args.ticks)
        return 0
    except ClientError as exc:
        _log(f"ошибка: {exc}")
        return 1
    except ProtocolError as exc:
        _log(f"ошибка протокола: {exc}")
        return 1
    except KeyboardInterrupt:
        _log("прервано пользователем")
        return 0
    except OSError as exc:
        _log(f"ошибка ввода-вывода: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
