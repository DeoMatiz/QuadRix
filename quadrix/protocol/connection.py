# Порт horizon-protocol/src/connection.rs (блокирующее соединение) +
# недостающая в buf.py компрессия из frame.rs (zlib выше порога).
#
# В Rust Connection = ConnReader + ConnWriter, оба над одним Stream
# (TcpStream либо in-memory Pipe). Здесь то же самое в одном классе:
# один TCP-сокет, отдельные шифры чтения/записи и независимые пороги
# сжатия можно задать общим set_compression, как это делает
# Connection::set_compression.
#
# Сознательно НЕ портируется:
#   * Pipe / local-memory канал (интегрированный сервер) — соединение
#     поверх socket.socketpair() проверяется тестами;
#   * adapter/v*.rs (пере-нумерация ID старых версий) — отдельная задача;
#   * split/detach (неблокирующий poller) — высокая логика клиента.
#
# Кадр: VarInt-длина (≤ 3 байта, MAX_FRAME из buf.py) + тело.
# Тело при сжатии: VarInt(несжатая длина) + zlib(payload), если
# длина ≥ threshold; иначе VarInt(0) + payload (frame.rs::contents).
# Шифрование AES/CFB8 идёт поверх уже собранного кадра
# (frame.rs / connection.rs::frame_into).

from __future__ import annotations

import socket
import zlib
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple, Type

from quadrix.protocol.buf import (
    MAX_FRAME,
    ProtocolError,
    Reader,
    frame_header,
    write_varint,
)
from quadrix.protocol.crypto import Cfb8, Cipher
from quadrix.protocol import ids
from quadrix.protocol.packets import configuration, login, play, status
from quadrix.protocol.packets.handshake import LOGIN, STATUS, TRANSFER, Intention
from quadrix.protocol.packets.login import ServerHello

__all__ = [
    "PROTOCOL_VERSION",
    "MAX_UNCOMPRESSED",
    "READ_SIZE",
    "ConnectionState",
    "Counters",
    "Inflater",
    "contents",
    "prefixed",
    "frame_body",
    "Connection",
    "ClientConnection",
    "connection_pair",
]

# lib.rs:31 — horizon_core::version::PROTOCOL_VERSION, протокол 26.3.
PROTOCOL_VERSION: int = 777
# frame.rs:13 — CompressionDecoder.MAXIMUM_UNCOMPRESSED_LENGTH.
MAX_UNCOMPRESSED: int = 8_388_608
# connection.rs:591 — размер одного чтения из потока.
READ_SIZE: int = 1 << 16


class ConnectionState(Enum):
    """Состояния соединения (connection.rs / vanilla ConnectionProtocol).

    Значения совпадают со State из ids.py, чтобы имена не расходились.
    """

    HANDSHAKING = "handshaking"
    STATUS = "status"
    LOGIN = "login"
    CONFIGURATION = "configuration"
    PLAY = "play"


#: ConnectionState → ids.State (для таблиц ID пакетов).
_STATE = {
    ConnectionState.HANDSHAKING: ids.State.HANDSHAKE,
    ConnectionState.STATUS: ids.State.STATUS,
    ConnectionState.LOGIN: ids.State.LOGIN,
    ConnectionState.CONFIGURATION: ids.State.CONFIGURATION,
    ConnectionState.PLAY: ids.State.PLAY,
}

#: Какие clientbound-пакеты принимает каждое состояние.
_CLIENTBOUND = {
    ConnectionState.STATUS: status.Clientbound,
    ConnectionState.LOGIN: login.Clientbound,
    ConnectionState.CONFIGURATION: configuration.Clientbound,
    ConnectionState.PLAY: play.Clientbound,
}


@dataclass
class Counters:
    """Пакеты и байты in/out (connection.rs::Counters, для debug-экрана)."""

    received: int = 0
    sent: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


class Inflater:
    """Раздуватель zlib с состоянием между кадрами (frame.rs::Inflater).

    Rust держит один `Decompress` и сбрасывает его на каждый кадр;
    каждый кадр у Minecraft — самостоятельный zlib-поток (encoder
    создаётся заново в `contents`), поэтому и здесь на каждый вызов
    поднимается свежий `decompressobj`.
    """

    __slots__ = ()

    def inflate(self, data: bytes, size: int) -> bytes:
        """Раздуть zlib-поток ровно в `size` байт (frame.rs::inflate)."""
        if size < 0:
            raise ProtocolError("negative uncompressed length")
        obj = zlib.decompressobj()
        try:
            # Один байт сверх заявленного: поток длиннее — не влезет.
            out = obj.decompress(bytes(data), size + 1)
        except zlib.error as exc:  # noqa: BLE001 — любой плохой поток
            raise ProtocolError(f"Badly compressed packet - {exc}") from exc
        if len(out) != size or not obj.eof:
            raise ProtocolError(
                f"Badly compressed packet - actual length {len(out)} "
                f"does not match declared size {size}"
            )
        return out


# ── Кадрирование и сжатие (frame.rs) ─────────────────────────────────


def contents(body: bytes, threshold: Optional[int]) -> bytes:
    """Что идёт после префикса длины (frame.rs::contents).

    threshold ``None`` — без сжатия; иначе при `len(body) < threshold`
    пишется ведущий 0 (несжатое тело), иначе VarInt(длина) + zlib.
    """
    raw = bytes(body)
    if threshold is None:
        inner = raw
    elif len(raw) < threshold:
        inner = b"\x00" + raw
    else:
        v = bytearray()
        write_varint(v, len(raw))
        v += zlib.compress(raw)
        inner = bytes(v)
    if len(inner) > MAX_FRAME:
        raise ProtocolError(f"packet too large: {len(inner)} bytes")
    return inner


def prefixed(inner: bytes) -> bytes:
    """Добавить префикс длины к содержимому кадра (frame.rs::prefixed)."""
    out = bytearray()
    write_varint(out, len(inner))
    out += bytes(inner)
    return bytes(out)


def frame_body(frame: bytes, threshold: Optional[int], inflater: Inflater) -> bytes:
    """Тело пакета из кадра (frame.rs::body, сжатый путь).

    Возвращает body (id + payload) либо ``b""`` для пустого
    сжатого кадра (vanilla его пропускает).
    """
    if threshold is None:
        return bytes(frame)
    r = Reader(frame)
    size = r.varint()
    if size == 0:
        return bytes(frame[r.position():])
    if size < 0:
        raise ProtocolError("negative uncompressed length")
    if size < threshold:
        raise ProtocolError(
            f"Badly compressed packet - size of {size} is below server "
            f"threshold of {threshold}"
        )
    if size > MAX_UNCOMPRESSED:
        raise ProtocolError(
            f"Badly compressed packet - size of {size} is larger than "
            f"protocol maximum"
        )
    return inflater.inflate(frame[r.position():], size)


# ── Соединение (connection.rs) ───────────────────────────────────────


class Connection:
    """Блокирующее соединение поверх TCP-сокета (connection.rs::Connection).

    ``sock`` — уже подключённый сокет (как TcpStream); для серверной
    стороны — сокет, принятый из accept. Чтение и запись синхронные.
    """

    __slots__ = (
        "sock",
        "state",
        "protocol",
        "counters",
        "_buffer",
        "_inflater",
        "_encrypt",
        "_decrypt",
        "_threshold",
        "_read_timeout",
        "_closed",
    )

    def __init__(
        self,
        sock: socket.socket,
        *,
        state: ConnectionState = ConnectionState.HANDSHAKING,
        protocol: int = PROTOCOL_VERSION,
    ) -> None:
        self.sock = sock
        self.state = state
        self.protocol = protocol
        self.counters = Counters()
        # Несъеденные байты (connection.rs: ConnReader.buffer).
        self._buffer = bytearray()
        self._inflater = Inflater()
        self._encrypt: Optional[Cfb8] = None
        self._decrypt: Optional[Cfb8] = None
        self._threshold: Optional[int] = None
        self._read_timeout: Optional[float] = None
        self._closed = False

    # -- фабрики и утилиты --

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        timeout: float = 5.0,
        *,
        protocol: int = PROTOCOL_VERSION,
    ) -> "Connection":
        """Подключиться к серверу (connection.rs::connect)."""
        try:
            sock = socket.create_connection((host, int(port)), timeout=timeout)
        except OSError as exc:
            raise ProtocolError(f"[QuadRix] Connection refused: {exc}") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return cls(sock, protocol=protocol)

    @classmethod
    def from_socket(
        cls,
        sock: socket.socket,
        *,
        state: ConnectionState = ConnectionState.HANDSHAKING,
        protocol: int = PROTOCOL_VERSION,
    ) -> "Connection":
        """Обернуть существующий сокет (connection.rs::from_stream)."""
        # socketpair и in-memory сокеты TCP_NODELAY не принимают.
        with suppress(OSError):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return cls(sock, state=state, protocol=protocol)

    def peer_address(self) -> Optional[Tuple[str, int]]:
        """Адрес удалённой стороны, если сокет его знает."""
        try:
            return self.sock.getpeername()
        except OSError:
            return None

    def is_memory(self) -> bool:
        """Соединение через память (в порте всегда False, сокет — TCP)."""
        return False

    # -- шифрование и сжатие --

    def set_compression(self, threshold: int) -> None:
        """Порог сжатия (connection.rs::set_compression).

        Отрицательный порог выключает сжатие, как
        ClientboundLoginCompressionPacket в vanilla.
        """
        self._threshold = None if int(threshold) < 0 else int(threshold)

    @property
    def threshold(self) -> Optional[int]:
        """Текущий порог сжатия (``None`` — сжатие выключено)."""
        return self._threshold

    def enable_encryption(self, secret: bytes) -> None:
        """Ключ обоих направлений (connection.rs::enable_encryption).

        Один shared secret; чтение и запись получают свои CFB8.
        Байты, уже прочитанные сверх последнего пакета, тоже были
        зашифрованы — их расшифровываем сразу.
        """
        self._decrypt = Cfb8(secret, secret)
        self._encrypt = Cfb8(secret, secret)
        if self._buffer:
            self._buffer = bytearray(self._decrypt.decrypt(bytes(self._buffer)))

    def enable_cipher(self, cipher: Cipher) -> None:
        """Включить шифрование готовой парой (Cipher из crypto.py)."""
        self._encrypt = Cfb8(cipher.secret, cipher.secret)
        self._decrypt = Cfb8(cipher.secret, cipher.secret)
        if self._buffer:
            self._buffer = bytearray(self._decrypt.decrypt(bytes(self._buffer)))

    # -- низкий уровень сокета --

    def _recv_chunk(self) -> bytes:
        """Прочитать кусок из сокета, расшифровать, положить в буфер.

        Возвращает число прочитанных байт через len результата; пустой
        результат означает конец потока.
        """
        try:
            chunk = self.sock.recv(READ_SIZE)
        except socket.timeout as exc:
            raise ProtocolError("Timed out") from exc
        except OSError as exc:
            raise ProtocolError(f"[QuadRix] read failed: {exc}") from exc
        if not chunk:
            return b""
        self.counters.bytes_in += len(chunk)
        if self._decrypt is not None:
            chunk = self._decrypt.decrypt(chunk)
        return chunk

    def _read_more(self, need: int) -> None:
        """Дочитать буфер минимум до `need` байт (connection.rs::fill)."""
        while len(self._buffer) < need:
            chunk = self._recv_chunk()
            if not chunk:
                raise ProtocolError("[QuadRix] Unexpected end of stream")
            self._buffer += chunk

    def read_raw(self, length: int) -> bytes:
        """Ровно `length` сырых байт, без кадрирования (connection.rs::read_raw)."""
        self._read_more(length)
        out = bytes(self._buffer[:length])
        del self._buffer[:length]
        return out

    def write_raw(self, data: bytes) -> None:
        """Сырые байты, без кадрирования (connection.rs::write_raw)."""
        raw = bytes(data)
        if self._encrypt is not None:
            raw = self._encrypt.encrypt(raw)
        try:
            self.sock.sendall(raw)
        except OSError as exc:
            raise ProtocolError(f"[QuadRix] write failed: {exc}") from exc
        self.counters.bytes_out += len(raw)

    # -- чтение / запись пакетов --

    def read_packet(self) -> Tuple[int, bytes]:
        """Блокирующе прочитать пакет: (id, payload) (connection.rs::recv).

        Пустые сжатые кадры (vanilla их пишет) пропускаются.
        """
        while True:
            header = frame_header(bytes(self._buffer))
            if header is None:
                self._read_more(len(self._buffer) + 1)
                continue
            prefix, length = header
            need = prefix + length
            if len(self._buffer) < need:
                self._read_more(need)
                continue
            frame = bytes(self._buffer[prefix:need])
            del self._buffer[:need]
            body = frame_body(frame, self._threshold, self._inflater)
            if not body:
                # Пустой сжатый кадр: vanilla его пропускает.
                continue
            r = Reader(body)
            packet_id = r.varint()
            self.counters.received += 1
            return packet_id, r.rest()

    # Rust-имя recv — то же, что read_packet.
    recv = read_packet

    def write_packet(self, packet_id: int, payload: bytes = b"") -> None:
        """Записать пакет (connection.rs::send + frame_into)."""
        body = bytearray()
        write_varint(body, int(packet_id))
        body += bytes(payload)
        inner = contents(bytes(body), self._threshold)
        framed = prefixed(inner)
        if self._encrypt is not None:
            framed = self._encrypt.encrypt(framed)
        try:
            self.sock.sendall(framed)
        except OSError as exc:
            raise ProtocolError(f"[QuadRix] write failed: {exc}") from exc
        self.counters.sent += 1
        self.counters.bytes_out += len(framed)

    # Rust-имя send — то же, что write_packet (тело уже с id).
    def send(self, body: bytes) -> None:
        """Отправить тело как есть: VarInt id + payload (connection.rs::send)."""
        r = Reader(body)
        packet_id = r.varint()
        self.write_packet(packet_id, r.rest())

    # -- таймауты и закрытие --

    def set_read_timeout(self, timeout: Optional[float]) -> None:
        """Таймаут чтения в секундах, ``None`` — блокировать (connection.rs)."""
        self._read_timeout = timeout
        self.sock.settimeout(timeout)

    def close(self) -> None:
        """Корректно закрыть соединение (connection.rs::shutdown/close)."""
        if self._closed:
            return
        self._closed = True
        # Сокет мог быть уже закрыт собеседником — это не ошибка.
        with suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            self.sock.close()

    # Rust-имя shutdown.
    shutdown = close

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- state machine --

    def next_state(self, intent: int) -> ConnectionState:
        """Следующее состояние после Intention (connection.rs-логика)."""
        if intent == STATUS:
            return ConnectionState.STATUS
        if intent in (LOGIN, TRANSFER):
            return ConnectionState.LOGIN
        raise ProtocolError(f"[QuadRix] unknown intent {intent}")

    def set_state(self, state: ConnectionState) -> None:
        """Сменить состояние вручную."""
        self.state = state

    def login_success(self) -> None:
        """После LoginFinished сервер ждёт Configuration (vanilla)."""
        self.state = ConnectionState.CONFIGURATION

    def finish_configuration(self) -> None:
        """FinishConfiguration → Play (vanilla)."""
        self.state = ConnectionState.PLAY

    # -- готовые пакеты состояния --

    def send_handshake(self, host: str, port: int, intent: int) -> None:
        """ClientIntention: первый пакет соединения (handshake.rs::Intention)."""
        packet = Intention(self.protocol, host, int(port), int(intent))
        packet_id = ids.handshake.serverbound.INTENTION
        self.write_packet(packet_id, packet.encode())
        self.state = self.next_state(intent)

    # Имя из задания.
    handshake = send_handshake

    def send_status_request(self) -> None:
        """StatusRequest: пустой пакет запроса статуса (status.rs)."""
        packet_id = ids.status.serverbound.STATUS_REQUEST
        self.write_packet(packet_id, b"")

    def send_ping(self, time_ms: int) -> None:
        """PingRequest: 64-битное время (status.rs)."""
        from quadrix.protocol.buf import Writer

        w = Writer()
        w.i64(time_ms)
        packet_id = ids.status.serverbound.PING_REQUEST
        self.write_packet(packet_id, bytes(w.data))

    def send_login_start(self, name: str, uuid: int = 0) -> None:
        """LoginStart (Rust: ServerHello): имя и UUID (0 — offline)."""
        packet = ServerHello(name, int(uuid))
        packet_id = ids.login.serverbound.HELLO
        self.write_packet(packet_id, packet.encode())

    def send_login_acknowledged(self) -> None:
        """LoginAcknowledged + переход в Configuration (login.rs)."""
        packet_id = ids.login.serverbound.LOGIN_ACKNOWLEDGED
        self.write_packet(packet_id, b"")
        self.login_success()

    def send_finish_configuration(self) -> None:
        """FinishConfiguration + переход в Play (configuration.rs)."""
        packet_id = ids.configuration.serverbound.FINISH_CONFIGURATION
        self.write_packet(packet_id, b"")
        self.finish_configuration()

    # -- разбор принятых пакетов --

    def decode_packet(self, packet_id: int, payload: bytes):
        """Разобрать входящий пакет по текущему состоянию (clientbound)."""
        packet_set = _CLIENTBOUND.get(self.state)
        if packet_set is None:
            raise ProtocolError(
                f"[QuadRix] нет clientbound-пакетов для {self.state.value}"
            )
        return packet_set.decode(packet_id, payload)

    def await_packet(
        self,
        expected: Type,
        *,
        timeout: Optional[float] = None,
        decoder: Optional[Callable[[int, bytes], object]] = None,
    ):
        """Ждать пакет класса `expected` до таймаута (client-side API).

        Прочие пакеты разбираются (через `decoder` либо текущее
        состояние) и пропускаются. По таймауту поднимается
        ProtocolError("Timed out").
        """
        decode = decoder if decoder is not None else self.decode_packet
        previous = self._read_timeout
        if timeout is not None:
            self.set_read_timeout(timeout)
        try:
            while True:
                packet_id, payload = self.read_packet()
                packet = decode(packet_id, payload)
                if isinstance(packet, expected):
                    return packet
        finally:
            if timeout is not None:
                self.set_read_timeout(previous)


#: Имя из задания: клиентское соединение.
ClientConnection = Connection


def connection_pair(
    *,
    protocol: int = PROTOCOL_VERSION,
) -> Tuple[Connection, Connection]:
    """Две соединённые стороны поверх socket.socketpair().

    Возвращает (client, server) — оба конца одного in-memory канала,
    как Pipe::pair(), но на настоящих сокетах.
    """
    left, right = socket.socketpair()
    return (
        Connection.from_socket(left, protocol=protocol),
        Connection.from_socket(right, protocol=protocol),
    )
